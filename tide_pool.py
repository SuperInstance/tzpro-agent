#!/usr/bin/env python3
"""tide_pool.py — Short-term working memory for the ship's AI.

The Tide Pool is the surface layer of Hermit Memory: ephemera that matters
right now — this watch, this tide cycle, this ten-minute capture cadence.
Every FLUSH_INTERVAL seconds the pool flushes. Observations reinforced
3+ times graduate to the Stipes (.stipes_memory.jsonl). Everything else
is let go, like water returning to the bay.
"""

from __future__ import annotations

import json
import sys
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# ── Constants ─────────────────────────────────────────────────────────
FLUSH_INTERVAL = 600  # 10 minutes, aligned with capture cadence
NMEA_BUFFER_LEN = 5
STIPES_FILENAME = ".stipes_memory.jsonl"
TIDE_POOL_FILENAME = ".tide_pool.json"
REINFORCEMENT_THRESHOLD = 3


# ── Memory atoms ──────────────────────────────────────────────────────
@dataclass
class CaptureAnalysis:
    """A single sounder-capture analysis — species, depth, bottom, etc."""

    timestamp: float
    summary: dict[str, Any] = field(default_factory=dict)
    reinforcements: int = 0


@dataclass
class NMEAReading:
    """One NMEA sentence with its receive timestamp."""

    timestamp: float
    sentence: str
    reinforcements: int = 0


@dataclass
class BoatProximityState:
    """Snapshot of nearby vessel traffic."""

    timestamp: float
    nearest_vessel_m: float | None = None
    count_within_1km: int = 0
    reinforcements: int = 0


@dataclass
class FeedHazeState:
    """Snapshot of feed-haze / bait-cloud detection."""

    timestamp: float
    active: bool = False
    confidence: float = 0.0
    reinforcements: int = 0


# ── Tide Pool ─────────────────────────────────────────────────────────
@dataclass
class TidePool:
    """Rotating short-term memory that graduates reinforced items to Stipes."""

    workspace: Path = field(default_factory=lambda: Path(__file__).parent.resolve())
    flush_interval: int = FLUSH_INTERVAL
    reinforcement_threshold: int = REINFORCEMENT_THRESHOLD

    current_capture: CaptureAnalysis | None = None
    nmea_readings: deque[NMEAReading] = field(
        default_factory=lambda: deque(maxlen=NMEA_BUFFER_LEN)
    )
    boat_proximity: BoatProximityState | None = None
    feed_haze: FeedHazeState | None = None
    last_flush: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self._stipes_path = self.workspace / STIPES_FILENAME
        self._pool_path = self.workspace / TIDE_POOL_FILENAME
        # Try to resume a persisted pool on boot; failure is fine — we start fresh.
        if self._pool_path.exists():
            try:
                self.load()
            except Exception:
                pass

    # ── Ingest ────────────────────────────────────────────────────────
    def add_capture_analysis(self, summary: dict[str, Any]) -> CaptureAnalysis:
        """Store the current capture analysis, replacing any previous one."""
        self.current_capture = CaptureAnalysis(timestamp=time.time(), summary=summary)
        return self.current_capture

    def add_nmea_reading(self, sentence: str) -> NMEAReading:
        """Append an NMEA sentence, keeping only the last five."""
        reading = NMEAReading(timestamp=time.time(), sentence=sentence)
        self.nmea_readings.append(reading)
        return reading

    def update_boat_proximity(
        self, nearest_vessel_m: float | None = None, count_within_1km: int = 0
    ) -> BoatProximityState:
        """Store the current boat-proximity snapshot."""
        self.boat_proximity = BoatProximityState(
            timestamp=time.time(),
            nearest_vessel_m=nearest_vessel_m,
            count_within_1km=count_within_1km,
        )
        return self.boat_proximity

    def update_feed_haze(self, active: bool, confidence: float = 0.0) -> FeedHazeState:
        """Store the current feed-haze detection state."""
        self.feed_haze = FeedHazeState(
            timestamp=time.time(), active=active, confidence=confidence
        )
        return self.feed_haze

    # ── Reinforcement ─────────────────────────────────────────────────
    def reinforce_capture(self) -> None:
        """Increment reinforcement on the current capture analysis."""
        if self.current_capture:
            self.current_capture.reinforcements += 1

    def reinforce_nmea(self, index: int = -1) -> None:
        """Increment reinforcement on an NMEA reading (default: most recent)."""
        if self.nmea_readings:
            self.nmea_readings[index].reinforcements += 1

    def reinforce_boat_proximity(self) -> None:
        """Increment reinforcement on the current boat-proximity state."""
        if self.boat_proximity:
            self.boat_proximity.reinforcements += 1

    def reinforce_feed_haze(self) -> None:
        """Increment reinforcement on the current feed-haze state."""
        if self.feed_haze:
            self.feed_haze.reinforcements += 1

    # ── Flush & graduation ────────────────────────────────────────────
    def _should_graduate(self, item: Any) -> bool:
        return getattr(item, "reinforcements", 0) >= self.reinforcement_threshold

    def _items(self) -> list[tuple[str, Any]]:
        """Return all currently held memory items with their kind labels."""
        items: list[tuple[str, Any]] = []
        if self.current_capture:
            items.append(("capture_analysis", self.current_capture))
        for reading in self.nmea_readings:
            items.append(("nmea_reading", reading))
        if self.boat_proximity:
            items.append(("boat_proximity", self.boat_proximity))
        if self.feed_haze:
            items.append(("feed_haze", self.feed_haze))
        return items

    def flush(self, force: bool = False) -> dict[str, Any]:
        """Flush the pool. Reinforced items graduate; the rest are discarded.

        Returns a report describing what graduated and what was dropped.
        """
        now = time.time()
        graduated: list[dict[str, Any]] = []
        dropped: list[str] = []

        for kind, item in self._items():
            if self._should_graduate(item):
                record = {
                    "graduated_at": now,
                    "source": "tide_pool",
                    "kind": kind,
                    "payload": asdict(item),
                }
                graduated.append(record)
            else:
                dropped.append(kind)

        if graduated:
            self._stipes_path.parent.mkdir(parents=True, exist_ok=True)
            with self._stipes_path.open("a", encoding="utf-8") as fh:
                for record in graduated:
                    fh.write(json.dumps(record, default=str) + "\n")

        # Clear the pool.
        self.current_capture = None
        self.nmea_readings.clear()
        self.boat_proximity = None
        self.feed_haze = None
        self.last_flush = now
        self.save()

        return {
            "flushed_at": now,
            "graduated_count": len(graduated),
            "graduated_kinds": [r["kind"] for r in graduated],
            "dropped_count": len(dropped),
            "dropped_kinds": dropped,
        }

    def maybe_flush(self) -> dict[str, Any] | None:
        """Flush only if the interval has elapsed."""
        if time.time() - self.last_flush >= self.flush_interval:
            return self.flush()
        return None

    # ── Persistence ───────────────────────────────────────────────────
    def to_dict(self) -> dict[str, Any]:
        return {
            "last_flush": self.last_flush,
            "current_capture": asdict(self.current_capture) if self.current_capture else None,
            "nmea_readings": [asdict(r) for r in self.nmea_readings],
            "boat_proximity": asdict(self.boat_proximity) if self.boat_proximity else None,
            "feed_haze": asdict(self.feed_haze) if self.feed_haze else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], workspace: Path | None = None) -> "TidePool":
        pool = cls(workspace=workspace or Path(__file__).parent.resolve())
        pool.last_flush = data.get("last_flush", time.time())
        if data.get("current_capture"):
            pool.current_capture = CaptureAnalysis(**data["current_capture"])
        pool.nmea_readings.clear()
        for r in data.get("nmea_readings", []):
            pool.nmea_readings.append(NMEAReading(**r))
        if data.get("boat_proximity"):
            pool.boat_proximity = BoatProximityState(**data["boat_proximity"])
        if data.get("feed_haze"):
            pool.feed_haze = FeedHazeState(**data["feed_haze"])
        return pool

    def save(self) -> None:
        """Persist the pool to disk so a restart can resume this watch."""
        with self._pool_path.open("w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, default=str, indent=2)

    def load(self) -> None:
        """Load the pool from disk."""
        if not self._pool_path.exists():
            return
        with self._pool_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        loaded = self.from_dict(data, workspace=self.workspace)
        self.current_capture = loaded.current_capture
        self.nmea_readings = loaded.nmea_readings
        self.boat_proximity = loaded.boat_proximity
        self.feed_haze = loaded.feed_haze
        self.last_flush = loaded.last_flush

    # ── Introspection ─────────────────────────────────────────────────
    def status(self) -> dict[str, Any]:
        """Return a snapshot of the pool's current contents and health."""
        now = time.time()
        return {
            "state": "active",
            "flush_interval_s": self.flush_interval,
            "seconds_since_flush": round(now - self.last_flush, 2),
            "seconds_until_flush": round(
                max(0.0, self.flush_interval - (now - self.last_flush)), 2
            ),
            "reinforcement_threshold": self.reinforcement_threshold,
            "current_capture": asdict(self.current_capture) if self.current_capture else None,
            "nmea_readings": [asdict(r) for r in self.nmea_readings],
            "boat_proximity": asdict(self.boat_proximity) if self.boat_proximity else None,
            "feed_haze": asdict(self.feed_haze) if self.feed_haze else None,
            "stipes_path": str(self._stipes_path),
        }


# ── CLI ───────────────────────────────────────────────────────────────
def _print_status(pool: TidePool) -> None:
    print(json.dumps(pool.status(), indent=2, default=str))


def _run_test() -> int:
    """Exercise the pool: ingest, reinforce, flush, verify graduation."""
    import tempfile

    tmpdir = Path(tempfile.mkdtemp(prefix="tide_pool_test_"))
    pool = TidePool(workspace=tmpdir, flush_interval=600)

    # Ingest.
    pool.add_capture_analysis({"species": "chum", "depth_fm": 35, "bottom": "hard"})
    pool.add_nmea_reading("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47")
    pool.add_nmea_reading("$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A")
    pool.update_boat_proximity(nearest_vessel_m=450.0, count_within_1km=2)
    pool.update_feed_haze(active=True, confidence=0.78)

    # Reinforce the capture and feed haze past the threshold.
    for _ in range(3):
        pool.reinforce_capture()
        pool.reinforce_feed_haze()
    # Reinforce one NMEA reading only twice (should be dropped).
    pool.reinforce_nmea()
    pool.reinforce_nmea()

    # Force a flush.
    report = pool.flush(force=True)

    # Verify Stipes output.
    stipes = []
    if pool._stipes_path.exists():
        with pool._stipes_path.open("r", encoding="utf-8") as fh:
            stipes = [json.loads(line) for line in fh if line.strip()]

    expected_graduated = {"capture_analysis", "feed_haze"}
    actual_graduated = {r["kind"] for r in stipes}
    passed = actual_graduated == expected_graduated and report["dropped_count"] == 3

    print("Tide Pool self-test")
    print("-" * 40)
    print(f"  Graduated kinds: {sorted(actual_graduated)}")
    print(f"  Dropped count:   {report['dropped_count']}")
    print(f"  Stipes file:     {pool._stipes_path}")
    print(f"  Result:          {'PASS' if passed else 'FAIL'}")

    # Clean up.
    for p in [pool._stipes_path, pool._pool_path, tmpdir]:
        if p.exists():
            if p.is_dir():
                p.rmdir()
            else:
                p.unlink()

    return 0 if passed else 1


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] in ("status", "st"):
        pool = TidePool()
        _print_status(pool)
        return 0
    if argv[0] in ("flush", "fl"):
        pool = TidePool()
        report = pool.flush(force=True)
        print(json.dumps(report, indent=2, default=str))
        return 0
    if argv[0] in ("test", "--test", "-t"):
        return _run_test()
    print(f"Usage: python {Path(__file__).name} [status|flush|test]")
    return 1


if __name__ == "__main__":
    sys.exit(main())
