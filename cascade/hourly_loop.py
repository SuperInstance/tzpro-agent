"""cascade/hourly_loop.py — H1, the analyst (docs/17).

Reads the day's scribe records (and retained novel notes) and writes the
briefing: summary, impact, recommendations with confidences. Text-only —
it reasons over records, not pixels. On-demand any time.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request

from . import config, gaze, ollama_client as oll, twin_sink
from .tools import daily_context

log = logging.getLogger("cascade.h1")

PROMPT = """You are the ship's analyst writing the hourly briefing for the
captain of an Alaskan troller. Below are today's canonical 10-minute
sounder records (JSON) and any retained novel watchstander notes.

Write the briefing. Plain pilot-house language, no filler. Structure:
1. DAY SO FAR — what the grounds looked like, spatially (use lat/lon track)
2. SIGNAL — schools, thermocline behavior, bottom changes worth caring about
3. RECOMMENDATIONS — each with a confidence (0-1) and one-line basis
4. WATCH — what to focus on next hour (becomes a gaze directive)

End with a JSON block: {"recommendations": [{"action": "...", "confidence": 0.0, "basis": "..."}], "suggest_gaze": "..."}

RULES: Respond with ONLY the briefing in that structure. Brief from the
'records' array — it is the canonical source. 'context_notes' (if any)
are background chatter, not the story. No preamble, no offers of help,
no meta-commentary about the data."""


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
        log.warning("H1 inference failed: %s", e)
        return None


def _mean_position(records: list[dict]) -> tuple[float, float] | None:
    """Calculate mean lat/lon from records with position data.

    Accepts both shapes: M10 records carry top-level lat/lon; raw
    capture sidecars nest them under position.lat_dd/lon_dd."""
    lats, lons = [], []
    for r in records:
        pos = r.get("position") or r
        if isinstance(pos, dict):
            lat = pos.get("lat", pos.get("lat_dd"))
            lon = pos.get("lon", pos.get("lon_dd"))
            if lat is not None and lon is not None:
                try:
                    lats.append(float(lat))
                    lons.append(float(lon))
                except (ValueError, TypeError):
                    continue
    if not lats or not lons:
        return None
    return sum(lats) / len(lats), sum(lons) / len(lons)


def _format_tide_weather_section(ctx: dict) -> str:
    """Format context data into a 3-6 line markdown section."""
    station = ctx.get("tide_station", {}).get("name", "Unknown")
    lines = [f"## Tide & Weather ({station})"]

    # Tide events (today's highs/lows)
    tides = ctx.get("tide_events", [])
    if tides:
        lines.append("**Tides:**")
        for ev in tides[:4]:  # Show first 4 events
            typ = ev.get("type", "?").title()
            t = ev.get("t", "")
            h = ev.get("height_ft", 0)
            lines.append(f"  - {typ} {t} ({h:.1f} ft)")

    # Wind forecast
    winds = ctx.get("wind_forecast", [])
    if winds:
        lines.append("**Wind:**")
        for w in winds[:3]:  # Show first 3 periods
            t = w.get("time", "")
            spd = w.get("speed_knots", 0)
            direc = w.get("direction", "?")
            lines.append(f"  - {t}: {spd} kt {direc}")

    return "\n".join(lines)


def _retention_stats() -> str | None:
    """Today's M1 retention as 'kept/seen = pct, in/out of band'.

    Approximation, labeled: 'seen' = frames in the twin today (M1 attempts
    every new frame once); 'kept' = novel notes retained today by the
    OR-of-three rule. Band: 5–25% (docs/21 Week-4 checkpoint).
    """
    try:
        import sqlite3
        db = config.WORKSPACE / "memory" / "meta.db"
        if not db.exists():
            return None
        day_start = int(time.time() - (time.time() % 86400)) * 1000  # UTC midnight
        conn = sqlite3.connect(str(db))
        seen = conn.execute(
            "SELECT COUNT(*) FROM frames WHERE ts_utc >= ?", (day_start,)
        ).fetchone()[0]
        kept = conn.execute(
            "SELECT COUNT(*) FROM notes WHERE ts_utc >= ? AND retained = 1", (day_start,)
        ).fetchone()[0]
        conn.close()
        if seen == 0:
            return None
        pct = 100.0 * kept / seen
        band = "in band" if 5.0 <= pct <= 25.0 else "OUT of band (5–25%)"
        return f"{kept}/{seen} = {pct:.0f}%, {band}"
    except Exception:
        return None


def write_briefing() -> str | None:
    if not oll.vision_available():
        log.info("ollama unavailable — H1 idling")
        return None

    records = []
    for f in sorted(config.DIR_RECORDS.glob("*_record.json")):
        try:
            records.append(json.loads(f.read_text()))
        except Exception:
            pass
    if not records:
        log.info("no records yet — nothing to brief")
        return None

    novel = []
    for f in sorted(config.DIR_NOVEL.glob("*.json"))[-20:]:
        try:
            novel.append(json.loads(f.read_text()))
        except Exception:
            pass

    # Brief from the canonical M10 records. Novel M1 notes are context
    # only when records are thin — with a full record set, notes just
    # pull the model off-structure (found 2026-07-20: the model
    # summarized the notes and ignored the records entirely).
    include_notes = novel[-5:] if len(records) < 10 else []
    payload = json.dumps({"records": records[-60:], "context_notes": include_notes}, indent=1)
    text = _text_prompt(PROMPT + "\n\nDATA:\n" + payload, config.MODEL_H1, config.H1_MAX_TOKENS)
    if text is None:
        return None

    # Fetch tide & weather context for the mean position
    mean_pos = _mean_position(records[-60:])
    if mean_pos:
        lat, lon = mean_pos
        ctx = daily_context.get_context(lat, lon)
        if not ctx.get("offline"):
            # Append tide & weather section to the briefing
            section = _format_tide_weather_section(ctx)
            text = text + "\n\n" + section
        else:
            log.debug("context offline, skipping tide & weather section")

    # Retention stats line (calibration protocol, docs/research/
    # NOVELTY_CALIBRATION.md §5): drift in M1 retention must be visible
    # day to day. Programmatic, not model-written — always accurate.
    stats = _retention_stats()
    if stats:
        text = text + f"\n\n_M1 retention: {stats}_"

    stamp = time.strftime("%Y%m%d_%H%M", time.gmtime())
    out = config.DIR_BRIEFINGS / f"briefing_{stamp}.md"
    tmp = out.with_suffix(".tmp")
    tmp.write_text(text)
    tmp.replace(out)
    log.info("briefing written: %s", out.name)
    twin_sink.add_briefing(text, config.MODEL_H1)

    # Analyst may steer all lower loops.
    tail = oll.extract_json(text) or {}
    suggestion = (tail.get("suggest_gaze") or "").strip()
    if suggestion:
        gaze.set_gaze(suggestion, set_by="H1", ttl_s=config.H1_INTERVAL)

    return str(out)


def main() -> None:
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--now", action="store_true", help="write a briefing immediately")
    a = p.parse_args()
    config.ensure_dirs()
    if a.now:
        path = write_briefing()
        print(path or "no briefing (no records or model unavailable)")


if __name__ == "__main__":
    main()
