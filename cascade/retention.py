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


def _frame_id_for_png(png: Path) -> str | None:
    """Look up the twin frame_id for a capture PNG via its sidecar.

    Returns the sidecar's `capture_id` (which decaminute_loop uses as the
    primary key on echogram_records). Falls back to the file stem.
    """
    sidecar = png.with_suffix(".json")
    if not sidecar.is_file():
        return None
    try:
        import json as _json
        d = _json.loads(sidecar.read_text())
    except Exception:
        return None
    return d.get("capture_id") or png.stem


def _has_canonical_record(frame_id: str | None) -> bool:
    """True iff the twin has an echogram_records row for this frame_id.

    A frame with a canonical record is the 10-min kept image; the
    day-stitch must survive — never GC those.
    """
    if not frame_id:
        return False
    try:
        import sqlite3
        db = config.WORKSPACE / "memory" / "meta.db"
        if not db.exists():
            return False
        conn = sqlite3.connect(str(db))
        row = conn.execute(
            "SELECT 1 FROM echogram_records WHERE frame_id = ? LIMIT 1",
            (frame_id,),
        ).fetchone()
        conn.close()
        return row is not None
    except Exception:
        return False


def evening_final_read(day_dir: Path) -> dict:
    """Read the day's discarded 1-min frames one last time, then GC.

    Contract (docs/17):
      * 10-min canonical frames (one with an echogram_record row) are the
        day-stitch images — they are NEVER deleted.
      * 1-min frames without a canonical record are final-read once and
        then deleted (the novel M1 notes we kept are sufficient).
      * Nothing is deleted unless ollama responded successfully.
    """
    report = {"day": day_dir.name, "frames_read": 0, "missed": [],
              "gc_pngs": 0, "kept_canonical": 0, "gc_notes": 0}
    if not day_dir.is_dir():
        return report

    if not oll.vision_available():
        log.warning("ollama down — final read aborted, NOTHING deleted")
        return report

    for png in sorted(day_dir.glob("*.png")):
        fid = _frame_id_for_png(png)
        if _has_canonical_record(fid):
            report["kept_canonical"] += 1
            continue

        raw = oll.vision_prompt(png, FINAL_READ_PROMPT, config.MODEL_M1,
                                config.M1_MAX_TOKENS, config.MODEL_M1_FALLBACK)
        report["frames_read"] += 1
        parsed = oll.extract_json(raw or "") or {}
        if parsed.get("missed_something"):
            report["missed"].append({"frame": png.name, "note": parsed.get("note", "")})
        if config.GC_MINUTE_PNGS:
            try:
                png.unlink(missing_ok=True)
                report["gc_pngs"] += 1
            except Exception:
                log.exception("unlink failed: %s", png)

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
