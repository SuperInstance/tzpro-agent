"""cascade/daemon.py — the zeroclaw: independent scheduler + heartbeat.

One job: keep the three loops fed. Own scheduler, own heartbeat file,
kill-safe, model-degraded mode. NO dependency on OpenClaw or any external
agent runtime (docs/17, independence contract).

Cadences: M1 every 60s, M10 every 600s (or on new canonical frame),
H1 every 3600s. Single-threaded by design: a slow inference skips a beat
rather than overlapping itself.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from . import config, hourly_loop, minute_loop, decaminute_loop as m10

log = logging.getLogger("cascade.daemon")


class CascadeDaemon:
    def __init__(self) -> None:
        config.ensure_dirs()
        self.m1 = minute_loop.MinuteLoop()
        self.next_m1 = 0.0
        self.next_m10 = 0.0
        self.next_h1 = time.time() + config.H1_INTERVAL  # first briefing after 1h
        self.recorded: set[str] = set()                  # capture_ids with records

    # ── heartbeat ────────────────────────────────────────────────────
    def heartbeat(self) -> None:
        hb = {
            "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "pid": __import__("os").getpid(),
            "m1_frames_seen": len(self.m1.seen),
            "records_written": len(self.recorded),
        }
        tmp = config.HEARTBEAT_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(hb, indent=2))
        tmp.replace(config.HEARTBEAT_FILE)

    # ── M10: canonical frames awaiting a record ──────────────────────
    def _pending_canonical_frames(self) -> list[Path]:
        if not config.CAPTURES.exists():
            return []
        pending = []
        for day in sorted(config.CAPTURES.iterdir()):
            if day.is_dir():
                for png in sorted(day.glob("*.png")):
                    if png.stem not in self.recorded:
                        pending.append(png)
        return pending

    def _run_m10(self) -> None:
        for frame in self._pending_canonical_frames():
            self.recorded.add(frame.stem)  # idempotency: once per frame, ever
            sidecar = {}
            try:
                sidecar = json.loads(frame.with_suffix(".json").read_text())
            except Exception:
                pass
            m10.write_record(frame, sidecar, self.m1.recent_notes(limit=12))

    # ── main loop ────────────────────────────────────────────────────
    def run(self) -> None:
        log.info("cascade daemon up — M1/%ds M10/%ds H1/%ds",
                 config.M1_INTERVAL, config.M10_INTERVAL, config.H1_INTERVAL)
        last_hb = 0.0
        while True:
            now = time.time()

            if now >= self.next_m1:
                self.next_m1 = now + config.M1_INTERVAL
                try:
                    notes = self.m1.run_once()
                    if notes:
                        log.info("M1: %d note(s)", len(notes))
                except Exception:
                    log.exception("M1 cycle failed — continuing")

            if now >= self.next_m10:
                self.next_m10 = now + config.M10_INTERVAL
                try:
                    self._run_m10()
                except Exception:
                    log.exception("M10 cycle failed — continuing")

            if now >= self.next_h1:
                self.next_h1 = now + config.H1_INTERVAL
                try:
                    hourly_loop.write_briefing()
                except Exception:
                    log.exception("H1 cycle failed — continuing")

            if now - last_hb >= config.HEARTBEAT_INTERVAL:
                last_hb = now
                self.heartbeat()

            time.sleep(5)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(config.DIR_LOGS / "daemon.log", encoding="utf-8"),
        ] if config.DIR_LOGS.exists() or config.ensure_dirs() is None else [],
    )
    CascadeDaemon().run()


if __name__ == "__main__":
    main()
