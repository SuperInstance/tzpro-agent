#!/usr/bin/env python3
"""holdfast.py — Permanent memory layer for the hermit memory system.

The holdfast is the anchor of a kelp forest. It doesn't move, doesn't decay,
doesn't forget. In the memory system, this is the representation of knowledge
that has been reinforced enough (count >= 10, vitality > 0.5 in stipes) to
be considered permanent.

Graduation pipeline:
  Tide Pool (reinforcement >= 3) → Stipes (count >= 10, vitality > 0.5)
  → .holdfast_queue.json → Holdsfast (permanent)

Contains: boat specs, species signatures, gear performance curves,
Captain's preferences, chart data, and any knowledge that should
survive indefinitely.

Usage:
  python holdfast.py status     — show permanent knowledge summary
  python holdfast.py migrate    — drain graduation queue into holdfast
  python holdfast.py query <k>  — list entries by kind
  python holdfast.py test       — self-test
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).parent.resolve()
HOLDFAST_FILE = HERE / ".holdfast.json"
QUEUE_FILE = HERE / ".holdfast_queue.json"

CANONICAL_KINDS = {
    "boat_spec": "Permanent vessel specifications",
    "species_sig": "Species signatures (depth, intensity, shape)",
    "gear_perf": "Gear performance curves",
    "captain_pref": "Captain's preferences and decisions",
    "chart": "Chart and bathymetry data",
    "pattern": "Learned patterns that passed the threshold",
    "theory": "Working theories that proved out",
    "concept": "Abstract concepts and relationships",
}


@dataclass
class HoldfastEntry:
    """A permanent knowledge entry in the holdfast.

    Unlike Tide Pool (short-term) and Stipes (long-term but decayable),
    holdfast entries are permanent. They never decay. They can only be
    explicitly removed.
    """
    kind: str
    content: dict[str, Any]
    source: str = "holdfast"
    created_at: float = field(default_factory=time.time)
    last_read_at: float = field(default_factory=time.time)
    read_count: int = 0
    graduated_from: Optional[str] = None

    @property
    def age_days(self) -> float:
        return (time.time() - self.created_at) / 86400

    @property
    def kind_label(self) -> str:
        return CANONICAL_KINDS.get(self.kind, self.kind)


@dataclass
class Holdfast:
    """Anchored permanent memory. Never decays.

    Contains the accumulated wisdom that has survived the graduation
    pipeline: highly reinforced, high-vitality knowledge from Stipes
    that was deemed permanent.

    Structure: {kind: [HoldfastEntry, ...]} — indexed by kind for
    fast recall. Serialized as JSON to .holdfast.json.
    """

    entries: dict[str, list[HoldfastEntry]] = field(default_factory=dict)
    path: Path = HOLDFAST_FILE

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def __len__(self) -> int:
        return sum(len(v) for v in self.entries.values())

    # ── Persistence ──────────────────────────────────────────

    def _load(self) -> None:
        """Load holdfast from disk."""
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text("utf-8"))
            for kind, entries in raw.items():
                self.entries[kind] = [HoldfastEntry(**e) for e in entries]
        except (json.JSONDecodeError, OSError):
            pass

    def save(self) -> None:
        """Serialize holdfast to disk."""
        raw: dict[str, list[dict]] = {}
        for kind, entries in self.entries.items():
            raw[kind] = [asdict(e) for e in entries]
        self.path.write_text(json.dumps(raw, indent=2, default=str), "utf-8")

    # ── Core operations ──────────────────────────────────────

    def plant(self, entry: HoldfastEntry) -> None:
        """Add a permanent entry."""
        self.entries.setdefault(entry.kind, []).append(entry)
        self.save()

    def recall(self, kind: Optional[str] = None, limit: int = 20) -> list[HoldfastEntry]:
        """Retrieve entries, optionally filtered by kind."""
        results: list[HoldfastEntry] = []
        kinds = [kind] if kind else CANONICAL_KINDS.keys()
        for k in kinds:
            if k not in self.entries:
                continue
            for entry in self.entries[k]:
                entry.read_count += 1
                entry.last_read_at = time.time()
                results.append(entry)
        results.sort(key=lambda e: e.read_count, reverse=True)
        for e in results[:limit]:
            e.read_count += 0  # already incremented above
        self.save()
        return results[:limit]

    def query(self, kind: str) -> list[HoldfastEntry]:
        """Get all entries of a specific kind."""
        return self.entries.get(kind, [])

    def remove(self, kind: str, predicate: callable) -> int:
        """Remove entries matching predicate. Returns count removed."""
        before = len(self.entries.get(kind, []))
        self.entries[kind] = [e for e in self.entries.get(kind, []) if not predicate(e)]
        removed = before - len(self.entries[kind])
        if removed:
            self.save()
        return removed

    def stats(self) -> dict[str, Any]:
        """Diagnostic summary."""
        return {
            "total_entries": len(self),
            "by_kind": {k: len(v) for k, v in self.entries.items()},
            "kinds": list(self.entries.keys()),
            "oldest_entry_days": max(
                (e.age_days for entries in self.entries.values() for e in entries),
                default=0.0,
            ),
            "most_read": max(
                (e.read_count for entries in self.entries.values() for e in entries),
                default=0,
            ),
        }

    # ── Graduation queue management ──────────────────────────

    @staticmethod
    def read_queue(path: Path = QUEUE_FILE) -> list[dict]:
        """Read the graduation queue (.holdfast_queue.json) from stipes."""
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    @staticmethod
    def clear_queue(path: Path = QUEUE_FILE) -> None:
        """Empty the graduation queue after migration."""
        path.write_text("[]", "utf-8")

    def migrate(self) -> int:
        """Drain the graduation queue into the holdfast.

        Each queued item becomes a permanent HoldfastEntry. The kind
        is inferred from the content or defaults to 'pattern'.
        Returns number of entries migrated.
        """
        queue = self.read_queue()
        if not queue:
            return 0

        count = 0
        for item in queue:
            kind = item.get("kind", "pattern")
            content = item.get("content", item)
            source = item.get("_source", "stipes")
            self.plant(HoldfastEntry(
                kind=kind,
                content=content,
                source="graduated",
                graduated_from=source,
            ))
            count += 1

        self.clear_queue()
        self.save()
        return count


# ══════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════

def cli() -> None:
    holdfast = Holdfast()

    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print("Usage: python holdfast.py <command>")
        print()
        print("Commands:")
        print("  status           Show holdfast summary")
        print("  migrate          Drain graduation queue into holdfast")
        print("  query <kind>     List entries by kind")
        print("  stats            Detailed diagnostic stats")
        print("  test             Run self-test")
        return

    cmd = sys.argv[1]

    if cmd == "status":
        s = holdfast.stats()
        print("HOLDFAST — Permanent Memory Layer")
        print("=" * 40)
        print(f"  Total entries: {s['total_entries']}")
        print(f"  Kinds: {', '.join(s['kinds']) if s['kinds'] else '(empty)'}")
        print(f"  Queue pending: {len(holdfast.read_queue())}")
        for kind, count in s["by_kind"].items():
            print(f"    {kind}: {count}")
        queue_entries = holdfast.read_queue()
        if queue_entries:
            print(f"\n  Waiting in graduation queue: {len(queue_entries)}")

    elif cmd == "migrate":
        count = holdfast.migrate()
        print(f"Migrated {count} entries from graduation queue to holdfast.")
        s = holdfast.stats()
        print(f"Holdfast now has {s['total_entries']} permanent entries.")

    elif cmd == "query" and len(sys.argv) >= 3:
        kind = sys.argv[2]
        entries = holdfast.query(kind)
        if not entries:
            print(f"No entries of kind '{kind}'.")
            return
        print(f"HOLDFAST entries: {kind} ({len(entries)})")
        print("=" * 40)
        for i, e in enumerate(entries[:10]):
            print(f"  [{i+1}] {e.kind} (reads={e.read_count}, age={e.age_days:.1f}d)")
            content_preview = json.dumps(e.content)[:80]
            print(f"       {content_preview}")

    elif cmd == "stats":
        s = holdfast.stats()
        print(json.dumps(s, indent=2))
        print(f"Queue pending: {len(holdfast.read_queue())}")

    elif cmd == "test":
        print("HOLDFAST self-test")
        print("-" * 40)
        h = Holdfast()
        assert len(h) == 0, "fresh holdfast should be empty"
        print("[OK] Fresh holdfast is empty")

        h.plant(HoldfastEntry(kind="boat_spec", content={"vessel": "EILEEN", "length_ft": 58}))
        h.plant(HoldfastEntry(kind="species_sig", content={"species": "chum", "depth_fm": 35}))
        h.plant(HoldfastEntry(kind="captain_pref", content={"lure": "green flasher"}))
        assert len(h) == 3, "should have 3 entries"
        print("[OK] 3 entries planted")

        recalled = h.recall(limit=5)
        assert len(recalled) == 3, "recall() should return all"
        print("[OK] recall() returns all 3 entries")

        boat = h.query("boat_spec")
        assert len(boat) == 1
        assert boat[0].content["vessel"] == "EILEEN"
        print("[OK] query('boat_spec') returns correct entry")

        s = h.stats()
        assert s["total_entries"] == 3
        assert "boat_spec" in s["by_kind"]
        print(f"[OK] stats: total={s['total_entries']}, kinds={len(s['kinds'])}")

        # Test migration from queue
        test_queue = h.path.parent / ".test_holdfast_queue.json"
        queued = [
            {"kind": "pattern", "content": {"pattern": "feed_patch_boundary", "lon": -131.864}, "_source": "stipes"},
            {"kind": "theory", "content": {"theory": "boat_competition_reduces_blobs"}, "_source": "stipes"},
        ]
        test_queue.write_text(json.dumps(queued), "utf-8")
        
        h2 = Holdfast()
        q = h2.read_queue(path=test_queue)
        assert len(q) == 2
        print(f"[OK] Queue has {len(q)} entries ready for migration")

        for item in q:
            h2.plant(HoldfastEntry(
                kind=item.get("kind", "pattern"),
                content=item.get("content", item),
                source="graduated",
                graduated_from=item.get("_source", "stipes"),
            ))
        h2.clear_queue(path=test_queue)
        assert len(h2.read_queue(path=test_queue)) == 0
        print(f"[OK] Graduation complete, holdfast now has {len(h2)} entries")

        # Clean up test
        test_queue.unlink(missing_ok=True)

        # Persistence test
        h3 = Holdfast()
        h3.plant(HoldfastEntry(kind="boat_spec", content={"vessel": "EILEEN", "test": True}))
        h3.save()
        path = h3.path
        assert path.exists()
        h4 = Holdfast()
        loaded = h4.query("boat_spec")
        assert any(e.content.get("test") for e in loaded), "persistence roundtrip failed"
        print("[OK] Persistence: save/load roundtrip verified")
        path.unlink(missing_ok=True)

        print("-" * 40)
        print("ALL TESTS PASSED")

    else:
        print(f"Unknown command: {cmd}")
        cli()


if __name__ == "__main__":
    cli()
