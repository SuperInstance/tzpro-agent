"""cascade/minute_loop.py — M1, the racehorse (docs/17).

One frame, one job: what is here, is it novel? Blinders on: tiny context,
short answer. Notes are transient unless novel — zero-shot observations
of how something LOOKED are training ore for the vocabulary pipeline.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

from . import config, gaze, ollama_client as oll, twin_sink
from .retention import RingBuffer

log = logging.getLogger("cascade.m1")

PROMPT = """You are a fish-finder watchstander on an Alaskan troller.
Look at this TZ Pro echogram screenshot (dual-band: LF left, HF right,
depth in fathoms increasing downward).

One job: report what is here and whether it is novel. Blinders on —
this frame only, no history, no speculation beyond the image.

Respond with ONLY a JSON object:
{
 "caption": "one sentence, plain pilot-house language",
 "bottom_fm": <number or null>,
 "features": ["blob school", "thermocline", "haze", "bottom hardness change", ...],
 "notable": <true|false>,
 "novelty": <0.0-1.0 how unusual vs a routine empty-water frame>
}"""


class MinuteLoop:
    def __init__(self) -> None:
        self.ring = RingBuffer(config.RING_BUFFER_SIZE)
        self.seen: set[str] = set()  # frame hashes already analyzed

    def _unprocessed_frames(self) -> list[Path]:
        if not config.CAPTURES.exists():
            return []
        frames: list[Path] = []
        for day in sorted(config.CAPTURES.iterdir()):
            if day.is_dir():
                frames.extend(sorted(day.glob("*.png")))
        return [f for f in frames if self._hash(f) not in self.seen]

    @staticmethod
    def _hash(p: Path) -> str:
        return hashlib.sha1(p.name.encode()).hexdigest()

    def _load_sidecar(self, png: Path) -> dict:
        sidecar = png.with_suffix(".json")
        try:
            return json.loads(sidecar.read_text())
        except Exception:
            return {}

    def run_once(self) -> list[dict]:
        """Analyze any new frames. Returns notes produced this pass."""
        if not oll.vision_available():
            log.info("ollama unavailable — M1 idling")
            return []

        notes = []
        for frame in self._unprocessed_frames():
            self.seen.add(self._hash(frame))
            g = gaze.current()
            prompt = PROMPT
            if g:
                prompt += f"\n\nFOCUS DIRECTIVE (from {g['set_by']}): {g['focus']}"

            raw = oll.vision_prompt(frame, prompt, config.MODEL_M1,
                                    config.M1_MAX_TOKENS, config.MODEL_M1_FALLBACK)
            if raw is None:
                continue

            sidecar = self._load_sidecar(frame)
            parsed = oll.extract_json(raw) or {}
            # Register the frame in the data twin (idempotent by hash);
            # notes carry the twin frame_id for provenance joins.
            frame_id = twin_sink.add_frame(frame, sidecar)
            # Record the model that ACTUALLY ran (fallback if primary
            # absent) — provenance must be honest (docs/06).
            model_used = (
                config.MODEL_M1
                if oll.model_present(config.MODEL_M1)
                else config.MODEL_M1_FALLBACK
            )
            note = {
                "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "frame": frame.name,
                "frame_id": frame_id,
                "lat": (sidecar.get("position") or {}).get("lat_dd"),
                "lon": (sidecar.get("position") or {}).get("lon_dd"),
                "sog_kts": (sidecar.get("position") or {}).get("sog_kts"),
                "caption": parsed.get("caption", raw[:200]),
                "features": parsed.get("features", []),
                "notable": bool(parsed.get("notable", False)),
                "novelty": float(parsed.get("novelty", 0.0) or 0.0),
                "gaze": g["focus"] if g else None,
                "model": model_used,
            }
            self.ring.push(note)
            notes.append(note)

            # Retention rule: novel notes are kept (training ore); the rest
            # live only in the ring for the scribe, then GC. (docs/17)
            if note["novelty"] >= config.NOVELTY_THRESHOLD or note["notable"]:
                self._persist_novel(note)
                note["body"] = note["caption"]  # twin notes schema: body text
                note["retained"] = 1
                twin_sink.add_note(note)
        return notes

    def _persist_novel(self, note: dict) -> None:
        out = config.DIR_NOVEL / f"{note['ts_utc'].replace(':', '')}_{note['frame']}.json"
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps(note, indent=2))
        tmp.replace(out)
        log.info("novel note kept: %s (novelty %.2f)", note["frame"], note["novelty"])

    def recent_notes(self, limit: int | None = None) -> list[dict]:
        return self.ring.items()[-limit:] if limit else self.ring.items()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    config.ensure_dirs()
    loop = MinuteLoop()
    for n in loop.run_once():
        print(json.dumps(n, indent=2))


if __name__ == "__main__":
    main()
