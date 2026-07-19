"""cascade/decaminute_loop.py — M10, the scribe (docs/17).

Reads the canonical 10-minute frame plus the racehorses' notes (mostly
for lat/lon — the spatial track of the time sequence), and writes THE
searchable record: word-based + structured JSON, vectorizable, never GC'd.
Also steers: may update the gaze for M1.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from . import config, gaze, ollama_client as oll

log = logging.getLogger("cascade.m10")

PROMPT = """You are the ship's log scribe on an Alaskan troller, writing the
canonical 10-minute sounder record.

You see: the current TZ Pro echogram frame, plus the watchstander's
minute notes from the last interval (their lat/lon track shows WHERE the
time-sequence in the echogram happened).

Write the record a searching fisherman would want. Respond with ONLY JSON:
{
 "summary": "2-3 sentences, pilot-house language",
 "bottom_fm": <number or null>,
 "bottom_type": "<hard|soft|mixed|unknown>",
 "schools": [{"depth_fm": <n>, "size": "<small|medium|large>", "band": "<LF|HF|both>"}],
 "thermocline_fm": <number or null>,
 "haze": "<none|light|heavy>",
 "anomalies": ["..."],
 "search_terms": ["chum", "feed layer", "bait ball", ...],
 "suggest_gaze": "<one-line focus for the watchstander next interval, or empty>"
}"""


def write_record(frame: Path, sidecar: dict, notes: list[dict]) -> dict | None:
    if not oll.vision_available():
        log.info("ollama unavailable — M10 idling")
        return None

    track = [
        f"{n.get('ts_utc', '?')}: ({n.get('lat')}, {n.get('lon')}) — {n.get('caption', '')}"
        for n in notes[-12:]
    ]
    prompt = PROMPT + "\n\nWATCHSTANDER NOTES (newest last):\n" + (
        "\n".join(track) if track else "(none — interval had no new frames)"
    )

    raw = oll.vision_prompt(frame, prompt, config.MODEL_M10, config.M10_MAX_TOKENS)
    if raw is None:
        return None

    parsed = oll.extract_json(raw) or {}
    pos = sidecar.get("position") or {}
    record = {
        "spec": "echogram_record/1",
        "capture_id": sidecar.get("capture_id", frame.stem),
        "ts_utc": sidecar.get("ts_utc") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "lat": pos.get("lat_dd"),
        "lon": pos.get("lon_dd"),
        "sog_kts": pos.get("sog_kts"),
        "cog_deg": pos.get("cog_deg"),
        "summary": parsed.get("summary", raw[:400]),
        "bottom_fm": parsed.get("bottom_fm"),
        "bottom_type": parsed.get("bottom_type", "unknown"),
        "schools": parsed.get("schools", []),
        "thermocline_fm": parsed.get("thermocline_fm"),
        "haze": parsed.get("haze", "unknown"),
        "anomalies": parsed.get("anomalies", []),
        "search_terms": parsed.get("search_terms", []),
        "m1_notes_used": len(notes[-12:]),
        "model": config.MODEL_M10,
    }

    out = config.DIR_RECORDS / f"{record['capture_id']}_record.json"
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, indent=2))
    tmp.replace(out)
    log.info("record written: %s", out.name)

    # Steer the racehorses: scribe may refocus the blinders for next interval.
    suggestion = (parsed.get("suggest_gaze") or "").strip()
    if suggestion:
        gaze.set_gaze(suggestion, set_by="M10", ttl_s=config.M10_INTERVAL * 2)

    return record


def main() -> None:
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("frame", type=Path, help="canonical 10-minute frame")
    p.add_argument("--notes", type=Path, default=None, help="JSONL of M1 notes")
    a = p.parse_args()
    config.ensure_dirs()

    sidecar = {}
    try:
        sidecar = json.loads(a.frame.with_suffix(".json").read_text())
    except Exception:
        pass
    notes = []
    if a.notes and a.notes.exists():
        notes = [json.loads(l) for l in a.notes.read_text().splitlines() if l.strip()]

    print(json.dumps(write_record(a.frame, sidecar, notes), indent=2))


if __name__ == "__main__":
    main()
