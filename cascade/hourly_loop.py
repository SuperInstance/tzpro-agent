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

from . import config, gaze, ollama_client as oll

log = logging.getLogger("cascade.h1")

PROMPT = """You are the ship's analyst writing the hourly briefing for the
captain of an Alaskan troller. Below are today's canonical 10-minute
sounder records (JSON) and any retained novel watchstander notes.

Write the briefing. Plain pilot-house language, no filler. Structure:
1. DAY SO FAR — what the grounds looked like, spatially (use lat/lon track)
2. SIGNAL — schools, thermocline behavior, bottom changes worth caring about
3. RECOMMENDATIONS — each with a confidence (0-1) and one-line basis
4. WATCH — what to focus on next hour (becomes a gaze directive)

End with a JSON block: {"recommendations": [{"action": "...", "confidence": 0.0, "basis": "..."}], "suggest_gaze": "..."}"""


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

    payload = json.dumps({"records": records[-60:], "novel_notes": novel}, indent=1)
    text = _text_prompt(PROMPT + "\n\nDATA:\n" + payload, config.MODEL_H1, config.H1_MAX_TOKENS)
    if text is None:
        return None

    stamp = time.strftime("%Y%m%d_%H%M", time.gmtime())
    out = config.DIR_BRIEFINGS / f"briefing_{stamp}.md"
    tmp = out.with_suffix(".tmp")
    tmp.write_text(text)
    tmp.replace(out)
    log.info("briefing written: %s", out.name)

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
