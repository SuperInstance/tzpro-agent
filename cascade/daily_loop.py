"""cascade/daily_loop.py — D1, the daily analyst.

Closes the day: reads the day's H1 briefings + all M10 records + the
retained novel notes, then writes a paired report:

  cascade_out/briefings/day_<DATE>.md     human narrative (searchable prose)
  cascade_out/briefings/day_<DATE>.json   structured agentic brief

Why both: the .md is what a human skims or searches; the .json is what a
downstream agent (or a re-analysis pass) consumes without re-parsing prose.

Designed for offline-mode too: degrades to a small "skeleton" summary when
ollama isn't reachable, so we always get *some* artifact for the day rather
than a hole in the chain.

Run from cascade/daemon.py (EOD) or standalone:

    python -m cascade.daily_loop --date 2026-07-21
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

from . import config, ollama_client as oll, twin_sink

log = logging.getLogger("cascade.d1")

# ── Prompts ────────────────────────────────────────────────────────────────
PROMPT_NARRATIVE = """You are the ship's end-of-day analyst, writing the daily
narrative for the captain of an Alaskan troller.

Below are today's hourly briefings and the canonical 10-minute sounder records.

Write a 4-section markdown brief, plain pilot-house language, NO preamble,
NO offers of help, NO meta-commentary about the data:

1. DAY SHAPE — what the grounds looked like (use lat/lon track); major moves
2. HOTSPOTS — places we'd come back to (give coords + reasons, ranked)
3. WHAT CHANGED — bottom type, thermocline, fish behavior, anything we noticed
4. TOMORROW — one paragraph: what to fish first, what to test, what to avoid

End with a fenced JSON block:
```json
{"hotspots": [{"lat": <n>, "lon": <n>, "rank": 1, "reason": "..."}],
 "key_events": ["..."],
 "suggest_gaze": "<one-line or empty>"}
```
"""
PROMPT_STRUCTURED = """You are extracting a structured daily brief from a day's
10-minute echogram records. Below is a JSON array of records.

Output ONLY a JSON object:
{
  "date": "<YYYY-MM-DD>",
  "summary": "<one sentence day-level takeaway>",
  "hotspots": [
    {"lat": <n>, "lon": <n>, "rank": <1-N>, "reason": "<<=20 words>",
     "evidence_count": <int>, "ts_first": "<ISO>", "ts_last": "<ISO>"}
  ],
  "key_events": [{"ts": "<ISO>", "kind": "<school|change|novelty|other>",
                  "description": "<=20 words"}],
  "anomalies": [{"ts": "<ISO>", "description": "<=20 words"}],
  "next_investigate": [{"topic": "<feature or question>",
                        "lat": <n|null>, "lon": <n|null>,
                        "rationale": "<=20 words"}]
}

Rank hotspots by how many records or novel notes mention them. No commentary
outside the JSON.
"""


def _text_prompt(prompt: str, model: str, max_tokens: int) -> str | None:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "options": {"num_predict": max_tokens, "temperature": 0.3},
    }).encode()
    req = urllib.request.Request(
        f"{config.OLLAMA_URL}/api/chat", data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=config.INFER_TIMEOUT_S) as r:
            resp = json.loads(r.read().decode())
        return ((resp.get("message") or {}).get("content") or "").strip() or None
    except Exception as e:
        log.warning("D1 inference failed: %s", e)
        return None


def _list_records(date: str) -> list[dict]:
    """All M10 records that started on `date` (UTC date in the ts_utc sidecar)."""
    recs: list[dict] = []
    if not config.DIR_RECORDS.is_dir():
        return recs
    for f in sorted(config.DIR_RECORDS.glob("*_record.json")):
        try:
            r = json.loads(f.read_text())
        except Exception:
            continue
        ts = (r.get("ts_utc") or "")[:10]
        if ts == date:
            recs.append(r)
    return recs


def _list_novel(date: str) -> list[dict]:
    """All retained novel M1 notes for `date` (UTC date in ts_utc)."""
    notes: list[dict] = []
    if not (config.DIR_NOVEL).is_dir():
        return notes
    for f in sorted(config.DIR_NOVEL.glob("*.json")):
        try:
            n = json.loads(f.read_text())
        except Exception:
            continue
        ts = (n.get("ts_utc") or "")[:10]
        if ts == date:
            notes.append(n)
    return notes


def _list_h1_briefings(date: str) -> list[dict]:
    """All H1 briefings for `date` (UTC date in ts_utc)."""
    out: list[dict] = []
    if not config.DIR_BRIEFINGS.is_dir():
        return out
    for f in sorted(config.DIR_BRIEFINGS.glob("briefing_*.md")):
        try:
            txt = f.read_text()
        except Exception:
            continue
        ts = time.strftime("%Y-%m-%d", time.gmtime(
            time.mktime(time.strptime(f.stem.split("_", 1)[1], "%Y%m%d_%H%M"))
        )) if False else None  # not worth the dance, use file mtime as proxy
        mtime_utc = time.strftime("%Y-%m-%d", time.gmtime(f.stat().st_mtime))
        if mtime_utc == date:
            stem_ts = f.stem.replace("briefing_", "")
            stamp_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                      time.gmtime(f.stat().st_mtime))
            out.append({"file": f.name, "ts_utc": stamp_utc, "body": txt})
    return out


_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_tail_json(md_text: str) -> dict:
    """Pull a trailing ```json block out of the narrative if present."""
    m = _FENCE_RE.findall(md_text)
    if not m:
        return {}
    try:
        return json.loads(m[-1])
    except Exception:
        return {}


def _count_words(*blobs: str) -> int:
    return sum(len(b.split()) for b in blobs if b)


def _structured_minimal(records: list[dict], novel: list[dict], date: str) -> dict:
    """A non-LLM skeleton: useful when ollama is offline.

    Counts hotspot mentions, extracts key events from novel notes, and
    suggests 'any school/depth anomaly' for tomorrow.
    """
    hotspots: Counter = Counter()
    anomalies: list[dict] = []
    key_events: list[dict] = []

    for n in novel:
        lat, lon = n.get("lat"), n.get("lon")
        if lat is not None and lon is not None:
            # 0.01° bucket (~1.1 km) so we don't smear distinct spots
            key = (round(float(lat), 2), round(float(lon), 2))
            hotspots[key] += 1
        feats = [str(f) for f in (n.get("features") or [])]
        cap = (n.get("caption") or "").strip().rstrip(".")
        if cap:
            kind = "novelty"
            if any("blob" in f or "school" in f for f in feats):
                kind = "school"
            elif any("bottom" in f or "hardness" in f for f in feats):
                kind = "change"
            key_events.append({
                "ts": n.get("ts_utc", ""),
                "kind": kind,
                "description": cap[:120] if cap else "(untitled)",
            })

    return {
        "date": date,
        "summary": f"Skeleton brief: {len(records)} records, {len(novel)} retained novel notes.",
        "hotspots": [
            {"lat": k[0], "lon": k[1], "rank": i + 1,
             "reason": f"mentioned {v} times in novel notes",
             "evidence_count": v}
            for i, (k, v) in enumerate(hotspots.most_common(10))
        ],
        "key_events": key_events[:50],
        "anomalies": anomalies,
        "next_investigate": [],
    }


def write_daily(date: str | None = None) -> Path | None:
    """Write day_<DATE>.md + day_<DATE>.json. Returns path to MD."""
    if date is None:
        date = time.strftime("%Y-%m-%d", time.gmtime())
    config.ensure_dirs()

    records = _list_records(date)
    novel = _list_novel(date)
    h1s = _list_h1_briefings(date)

    if not (records or novel or h1s):
        log.info("D1: nothing for %s — skipping", date)
        return None

    # ── Narrative (.md) ─────────────────────────────────────────────────
    blocks = ["# H1 BRIEFINGS (today)\n"]
    if h1s:
        for h in h1s:
            blocks.append(f"## {h['ts_utc']}\n\n{h['body']}\n")
    else:
        blocks.append("*(none — ollama offline or no M10 records)*\n")

    # Slim down payload so the model doesn't choke; keep fields a human
    # reading the prompt would value.
    slim_records = [{
        "ts_utc": r.get("ts_utc"),
        "lat": r.get("lat"), "lon": r.get("lon"),
        "summary": r.get("summary"),
        "bottom_fm": r.get("bottom_fm"), "bottom_type": r.get("bottom_type"),
        "schools": r.get("schools"),
        "thermocline_fm": r.get("thermocline_fm"),
        "anomalies": r.get("anomalies"),
    } for r in records[-200:]]

    blocks.append(f"# M10 RECORDS ({len(slim_records)})\n\n```json\n"
                  + json.dumps(slim_records, indent=1)
                  + "\n```\n")

    blocks.append(f"# NOVEL NOTES ({len(novel)})\n\n"
                  + "\n".join(f"- {n.get('ts_utc')} {n.get('lat')},"
                              f"{n.get('lon')}: {n.get('caption','')[:150]}"
                              for n in novel[:30])
                  + "\n")

    payload_md = "\n".join(blocks)

    narrative: str | None = None
    if oll.vision_available():
        narrative = _text_prompt(PROMPT_NARRATIVE + "\n\nDATA:\n"
                                 + payload_md[:60_000],
                                 config.MODEL_H1,
                                 max_tokens=2000)

    if not narrative:
        # Offline skeleton narrative — better than a hole in the chain.
        skel = _structured_minimal(records, novel, date)
        narrative = (
            f"# Daily Brief — {date}\n\n"
            f"**Status:** ollama offline — skeleton brief generated.\n\n"
            f"## Day shape\n{skel['summary']}\n\n"
            f"## Hotspots (top 5)\n"
            + "\n".join(f"- {h['lat']}, {h['lon']} (×{h['evidence_count']})"
                        for h in skel['hotspots'][:5])
            + "\n\n## Key events\n"
            + "\n".join(f"- {e['ts']} *{e['kind']}*: {e['description']}"
                        for e in skel['key_events'][:20])
            + "\n"
        )
        tail = skel
    else:
        tail = _extract_tail_json(narrative) or {}

    md_path = config.DIR_BRIEFINGS / f"day_{date}.md"
    tmp = md_path.with_suffix(".md.tmp")
    tmp.write_text(narrative, encoding="utf-8")
    tmp.replace(md_path)

    # ── Structured (.json) ──────────────────────────────────────────────
    structured: dict
    if oll.vision_available() and slim_records:
        # Ask the model for the clean structured brief. Use a separate
        # prompt so it isn't tempted to also write prose.
        s_prompt = PROMPT_STRUCTURED + "\n\nDATA:\n" + json.dumps(
            slim_records[-100:], indent=1)[:60_000]
        raw = _text_prompt(s_prompt, config.MODEL_H1, max_tokens=1500)
        if raw:
            parsed = oll.extract_json(raw) or {}
            if parsed.get("date") or parsed.get("hotspots") or parsed.get("key_events"):
                structured = parsed
            else:
                structured = _structured_minimal(records, novel, date)
        else:
            structured = _structured_minimal(records, novel, date)
    else:
        structured = _structured_minimal(records, novel, date)

    # Enrich with provenance: counts and word budget
    structured.setdefault("date", date)
    structured["counts"] = {
        "m10_records": len(records),
        "novel_notes": len(novel),
        "h1_briefings": len(h1s),
    }
    structured["provenance"] = {
        "model": config.MODEL_H1 if oll.vision_available() else "skeleton",
        "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "md_words": _count_words(narrative or ""),
    }

    json_path = config.DIR_BRIEFINGS / f"day_{date}.json"
    tmp = json_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(structured, indent=2), encoding="utf-8")
    tmp.replace(json_path)

    # Steer gaze if any.
    gaze_str = (tail.get("suggest_gaze") or "") if isinstance(tail, dict) else ""
    if gaze_str.strip():
        from . import gaze
        gaze.set_gaze(gaze_str.strip(), set_by="D1",
                      ttl_s=4 * config.H1_INTERVAL)

    log.info("D1 wrote %s and %s", md_path.name, json_path.name)
    return md_path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=None,
                   help="UTC date YYYY-MM-DD (defaults to today)")
    args = p.parse_args()
    config.ensure_dirs()
    write_daily(args.date)


if __name__ == "__main__":
    main()
