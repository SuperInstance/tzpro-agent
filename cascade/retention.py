"""cascade/retention.py — ring buffer, novelty retention, evening final read + GC.

The GC contract (docs/17): M1 notes are transient; novel ones are kept;
discarded minute frames get ONE FINAL READ in the evening pass before
anything is deleted. Nothing is deleted unread.
"""
from __future__ import annotations

import json
import logging
import time
from collections import deque
from pathlib import Path

from . import config, ollama_client as oll

log = logging.getLogger("cascade.retention")

FINAL_READ_PROMPT = """Final evening scan of a TZ Pro echogram frame that was
marked routine during the day. One last chance: is there anything here a
narrow watch would have missed — faint structure, subtle bottom change,
odd interference? Answer ONLY with JSON:
{"missed_something": <true|false>, "note": "<one sentence or empty>"}"""


class RingBuffer:
    def __init__(self, size: int) -> None:
        self._buf: deque[dict] = deque(maxlen=size)

    def push(self, item: dict) -> None:
        self._buf.append(item)

    def items(self) -> list[dict]:
        return list(self._buf)


def evening_final_read(day_dir: Path) -> dict:
    """Read the day's discarded frames one last time, then GC minute notes.

    Returns the final-read report (appended to the day briefing by H1).
    """
    report = {"day": day_dir.name, "frames_read": 0, "missed": [], "gc_notes": 0}
    if not day_dir.is_dir():
        return report

    for png in sorted(day_dir.glob("*.png")):
        if not oll.vision_available():
            log.warning("ollama down — final read aborted, NOTHING deleted")
            return report
        raw = oll.vision_prompt(png, FINAL_READ_PROMPT, config.MODEL_M1,
                                config.M1_MAX_TOKENS, config.MODEL_M1_FALLBACK)
        report["frames_read"] += 1
        parsed = oll.extract_json(raw or "") or {}
        if parsed.get("missed_something"):
            report["missed"].append({"frame": png.name, "note": parsed.get("note", "")})
        if config.GC_MINUTE_PNGS:
            png.unlink(missing_ok=True)

    # GC the day's non-novel minute notes (novel ones live in DIR_NOVEL).
    notes_dir = config.OUT / "minute_notes" / day_dir.name
    if notes_dir.is_dir():
        for f in notes_dir.glob("*.json"):
            f.unlink()
            report["gc_notes"] += 1

    report["ts_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return report


def main() -> None:
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("day_dir", type=Path, help="capture day folder to final-read")
    a = p.parse_args()
    config.ensure_dirs()
    print(json.dumps(evening_final_read(a.day_dir), indent=2))


if __name__ == "__main__":
    main()
