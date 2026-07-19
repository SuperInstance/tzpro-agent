#!/usr/bin/env python3
"""
stipes.py — Graduated memory layer for the Hermit Memory system.

The Stipes are the "growing" memory — knowledge that survives beyond a single
watch but hasn't yet hardened into permanent Holdsfast fact.  Entries arrive
here when the Tide Pool flushes items reinforced ≥ 3 times.

Each entry lives in .stipes_memory.jsonl (append-only JSONL).  Reinforcement
counts tick up, and a computed *vitality* score decays at 0.001/day since the
last access.  When count ≥ 10 AND vitality > 0.5, the entry is queued for
Holdsfast migration (.holdfast_queue.json).  When vitality drops ≤ 0, the
entry is pruned — it outlived its usefulness.

Stdlib only: json, pathlib, time, datetime, re.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Constants ─────────────────────────────────────────────────────────────
DECAY_PER_DAY: float = 0.001       # vitality erosion per day since last access
GRADUATION_COUNT: int = 10         # reinforcements needed to be Holdsfast-eligible
GRADUATION_VITALITY: float = 0.5   # minimum vitality for Holdsfast eligibility

DEFAULT_MEMORY_FILE: str = ".stipes_memory.jsonl"
HOLDSFAST_QUEUE_FILE: str = ".holdfast_queue.json"

VALID_KINDS: frozenset[str] = frozenset({
    "capture", "nmea", "proximity", "haze", "concept",
})


# ── Helpers ───────────────────────────────────────────────────────────────

def _now() -> float:
    """Seconds since Unix epoch (float, time.time)."""
    return time.time()


def _days_since(then: float) -> float:
    """Return fractional days elapsed since *then*."""
    return max(0.0, (_now() - then) / 86400.0)


def _vitality(entry: dict[str, Any]) -> float:
    """Compute the current vitality of a single stipes entry.

    Each day without reinforcement costs DECAY_PER_DAY.  Vitality floor is 0.
    """
    if "last_accessed" not in entry:
        return 0.0
    return max(0.0, 1.0 - _days_since(entry["last_accessed"]) * DECAY_PER_DAY)


def _make_entry(kind: str, content: dict[str, Any]) -> dict[str, Any]:
    """Create a canonical stipes entry dict."""
    ts = _now()
    return {
        "graduated_at": ts,
        "kind": kind,
        "content": content,
        "count": 0,
        "last_accessed": ts,
    }


# ── Database ──────────────────────────────────────────────────────────────

class StipesDB:
    """Graduated memory — the "growing" layer between Tide Pool and Holdsfast.

    All entries are stored in an append-only JSONL file.  On open, the entire
    file is read into memory; on every mutation the file is rewritten.  This
    keeps things simple for the expected scale (thousands, not millions, of
    entries).
    """

    def __init__(self, workspace: Path | str | None = None) -> None:
        if workspace is None:
            workspace = Path(__file__).resolve().parent
        elif isinstance(workspace, str):
            workspace = Path(workspace)
        self._workspace: Path = workspace
        self._path: Path = self._workspace / DEFAULT_MEMORY_FILE
        self._holdfast_queue_path: Path = self._workspace / HOLDSFAST_QUEUE_FILE
        self._entries: list[dict[str, Any]] = []
        self._load()

    # ── I/O ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Read every line from the JSONL file into ``self._entries``."""
        self._entries.clear()
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Accept any JSON object; we'll filter by kind when querying.
                self._entries.append(obj)

    def _save(self) -> None:
        """Rewrite the entire JSONL file from ``self._entries``."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as fh:
            for entry in self._entries:
                fh.write(json.dumps(entry, default=str) + "\n")

    def _write_holdfast_queue(self, candidates: list[dict[str, Any]]) -> None:
        """Write (append) entries to the .holdfast_queue.json list.

        The file stores a JSON array of candidate objects so downstream tools
        can process the queue atomically.
        """
        existing: list[dict[str, Any]] = []
        if self._holdfast_queue_path.exists():
            try:
                existing = json.loads(
                    self._holdfast_queue_path.read_text(encoding="utf-8")
                )
                if not isinstance(existing, list):
                    existing = []
            except (json.JSONDecodeError, ValueError):
                existing = []

        existing.extend(candidates)
        self._holdfast_queue_path.write_text(
            json.dumps(existing, default=str, indent=2), encoding="utf-8"
        )

    # ── Query helpers ─────────────────────────────────────────────────

    def _stipes_entries(self) -> list[dict[str, Any]]:
        """Return only entries that look like proper stipes records."""
        return [e for e in self._entries if e.get("kind") in VALID_KINDS]

    # ── Public API ────────────────────────────────────────────────────

    def append(
        self, kind: str, content: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Append a new entry to the stipes.

        *kind* must be one of ``capture | nmea | proximity | haze | concept``.
        *content* is an arbitrary JSON-serialisable dict.

        Returns the newly created entry dict.
        """
        if kind not in VALID_KINDS:
            raise ValueError(
                f"Invalid kind {kind!r}; must be one of {sorted(VALID_KINDS)}"
            )
        entry = _make_entry(kind, content or {})
        self._entries.append(entry)
        self._save()
        return entry

    def search(self, query: str) -> list[dict[str, Any]]:
        """Return stipes entries whose stringified *content* matches *query*.

        Matching is case-insensitive substring search.  Results include a
        computed ``_vitality`` key for convenience.
        """
        q = query.lower()
        results: list[dict[str, Any]] = []
        for entry in self._stipes_entries():
            text = json.dumps(entry.get("content", {}), default=str).lower()
            if q in text:
                e = dict(entry)
                e["_vitality"] = _vitality(entry)
                results.append(e)
        return results

    def reinforce(self, kind: str) -> int:
        """Reinforce every stipes entry of the given *kind*.

        Each matching entry gets its ``count`` incremented and its
        ``last_accessed`` set to now (resetting vitality).

        Returns the number of entries reinforced.
        """
        if kind not in VALID_KINDS:
            raise ValueError(
                f"Invalid kind {kind!r}; must be one of {sorted(VALID_KINDS)}"
            )
        now = _now()
        reinforced = 0
        for entry in self._entries:
            if entry.get("kind") != kind:
                continue
            entry["count"] = entry.get("count", 0) + 1
            entry["last_accessed"] = now
            reinforced += 1
        if reinforced:
            self._save()
            # Check for Holdsfast graduation.
            self._check_graduation()
        return reinforced

    def list(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return the most recent stipes entries (by *graduated_at*).

        Each result includes a computed ``_vitality`` key.
        """
        entries = self._stipes_entries()
        entries.sort(key=lambda e: e.get("graduated_at", 0), reverse=True)
        out: list[dict[str, Any]] = []
        for entry in entries[:limit]:
            e = dict(entry)
            e["_vitality"] = _vitality(entry)
            out.append(e)
        return out

    def stats(self) -> dict[str, int]:
        """Return a dict of ``{kind: count}`` for all stipes entries."""
        buckets: dict[str, int] = {}
        for entry in self._stipes_entries():
            kind = entry["kind"]
            buckets[kind] = buckets.get(kind, 0) + 1
        return dict(sorted(buckets.items()))

    def prune(self, threshold: float | None = None) -> int:
        """Remove stipes entries whose vitality is ≤ *threshold* (default 0).

        Returns the number of entries pruned.
        """
        if threshold is None:
            threshold = 0.0
        before = len(self._entries)
        self._entries = [
            e
            for e in self._entries
            if e.get("kind") not in VALID_KINDS or _vitality(e) > threshold
        ]
        pruned = before - len(self._entries)
        if pruned:
            self._save()
        return pruned

    def _check_graduation(self) -> int:
        """Find entries eligible for Holdsfast and queue them.

        An entry graduates when ``count >= GRADUATION_COUNT`` AND its computed
        vitality exceeds ``GRADUATION_VITALITY``.

        Queued entries are *not* removed from stipes — the downstream
        Holdsfast importer is responsible for consumption.

        Returns the number of candidates queued.
        """
        candidates: list[dict[str, Any]] = []
        for entry in self._stipes_entries():
            v = _vitality(entry)
            if entry.get("count", 0) >= GRADUATION_COUNT and v > GRADUATION_VITALITY:
                # Avoid re-queuing entries we've already marked.
                if entry.get("_queued_for_holdsfast"):
                    continue
                candidates.append({
                    "entry": dict(entry),
                    "vitality": round(v, 4),
                    "queued_at": _now(),
                })
                entry["_queued_for_holdsfast"] = True

        if candidates:
            self._write_holdfast_queue(candidates)
            self._save()  # persist the _queued_for_holdsfast flags
        return len(candidates)

    # ── Introspection ─────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        """Return a diagnostic snapshot of the database."""
        entries = self._stipes_entries()
        total = len(entries)
        if total == 0:
            return {
                "state": "empty",
                "total_entries": 0,
                "memory_file": str(self._path),
                "holdsfast_queue": str(self._holdfast_queue_path),
            }

        vitals = [_vitality(e) for e in entries]
        counts = [e.get("count", 0) for e in entries]

        return {
            "state": "active",
            "total_entries": total,
            "by_kind": self.stats(),
            "avg_vitality": round(sum(vitals) / total, 4),
            "min_vitality": round(min(vitals), 4),
            "max_vitality": round(max(vitals), 4),
            "avg_count": round(sum(counts) / total, 2),
            "max_count": max(counts),
            "graduation_candidates": sum(
                1
                for e in entries
                if e.get("count", 0) >= GRADUATION_COUNT and _vitality(e) > GRADUATION_VITALITY
            ),
            "prune_candidates": sum(1 for e in entries if _vitality(e) <= 0),
            "memory_file": str(self._path),
            "holdsfast_queue": str(self._holdfast_queue_path),
        }


# ── CLI ───────────────────────────────────────────────────────────────────

def _cli_list(db: StipesDB, argv: list[str]) -> None:
    limit = 10
    if len(argv) > 1:
        try:
            limit = int(argv[1])
        except ValueError:
            pass
    entries = db.list(limit=limit)
    if not entries:
        print("(no stipes entries)")
        return
    for i, e in enumerate(entries, 1):
        ts = _format_ts(e.get("graduated_at"))
        print(
            f"{i:>3}. [{e['kind']}] count={e.get('count',0)} "
            f"v={e.get('_vitality',0):.4f}  {ts}"
        )
        content = e.get("content", {})
        if content:
            for k, v in content.items():
                sv = str(v)
                if len(sv) > 80:
                    sv = sv[:77] + "..."
                print(f"       {k}: {sv}")


def _cli_search(db: StipesDB, argv: list[str]) -> None:
    if len(argv) < 2:
        print("usage: stipes.py search <term>")
        return
    query = " ".join(argv[1:])
    results = db.search(query)
    if not results:
        print(f"(no matches for {query!r})")
        return
    print(f"{len(results)} match(es) for {query!r}:\n")
    for i, e in enumerate(results, 1):
        ts = _format_ts(e.get("graduated_at"))
        print(
            f"  {i}. [{e['kind']}] count={e.get('count',0)} "
            f"v={e.get('_vitality',0):.4f}  {ts}"
        )
        content = e.get("content", {})
        for k, v in content.items():
            sv = str(v)
            if len(sv) > 80:
                sv = sv[:77] + "..."
            print(f"       {k}: {sv}")


def _cli_stats(db: StipesDB) -> None:
    s = db.status()
    print(f"state:              {s['state']}")
    print(f"total entries:      {s['total_entries']}")
    if s["total_entries"]:
        print(f"by kind:")
        for kind, count in s["by_kind"].items():
            print(f"  {kind:>12}: {count}")
        print(f"avg vitality:       {s['avg_vitality']:.4f}")
        print(f"vitality range:     [{s['min_vitality']:.4f}, {s['max_vitality']:.4f}]")
        print(f"avg count:          {s['avg_count']:.2f}")
        print(f"max count:          {s['max_count']}")
        print(f"graduation ready:   {s['graduation_candidates']}")
        print(f"ready for prune:    {s['prune_candidates']}")
    print(f"memory file:        {s['memory_file']}")
    print(f"holdsfast queue:    {s['holdsfast_queue']}")


def _cli_prune(db: StipesDB) -> None:
    n = db.prune()
    print(f"pruned {n} entry/ies")
    if n:
        print("remaining:")
        _cli_list(db, [])


def _format_ts(ts: float | None) -> str:
    if ts is None:
        return "(no timestamp)"
    try:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.isoformat()
    except (OSError, ValueError):
        return str(ts)


def _cli_test(db: StipesDB) -> None:
    """Self-contained smoke test — write, read, reinforce, prune."""
    print("=== stipes self-test ===\n")

    # Append test entries.
    print("[1] append test entries")
    e1 = db.append("capture", {"species": "chum", "depth_fm": 35})
    e2 = db.append("concept", {"tag": "tide_correlation", "note": "flood=active"})
    e3 = db.append("haze", {"active": True, "confidence": 0.72})
    print(f"  created: capture id={id(e1)}, concept id={id(e2)}, haze id={id(e3)}")

    # List.
    print("\n[2] list (limit 5)")
    for e in db.list(5):
        print(f"  [{e['kind']}] count={e.get('count',0)} v={e.get('_vitality',0):.4f}")

    # Stats.
    print("\n[3] stats")
    for k, v in db.stats().items():
        print(f"  {k}: {v}")

    # Search.
    print("\n[4] search('chum')")
    results = db.search("chum")
    for e in results:
        print(f"  [{e['kind']}] {json.dumps(e.get('content',{}))}")

    # Reinforce.
    print("\n[5] reinforce('capture') 9x")
    for _ in range(9):
        db.reinforce("capture")
    e_after = db.search("chum")
    for e in e_after:
        print(f"  [{e['kind']}] count={e.get('count',0)} v={e.get('_vitality',0):.4f}")

    # Graduation check.
    print("\n[6] graduation check (count >= 10, vitality > 0.5)")
    s = db.status()
    print(f"  graduation_candidates: {s['graduation_candidates']}")

    # Prune (nothing should be stale).
    print("\n[7] prune")
    n = db.prune()
    print(f"  pruned: {n}")

    # Manually age an entry to force prune.
    print("\n[8] age an entry beyond vitality=0 and re-prune")
    for entry in db._entries:
        if entry.get("kind") == "haze":
            entry["last_accessed"] = _now() - (2000 * 86400)  # 2000 days ago
            break
    db._save()
    n = db.prune()
    print(f"  pruned: {n}  (haze should be gone)")
    print(f"  remaining kinds: {list(db.stats().keys())}")

    # Status.
    print("\n[9] status")
    for k, v in db.status().items():
        print(f"  {k}: {v}")

    print("\n=== all tests passed ===")


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]

    # Resolve workspace: take the directory of this script, honouring a
    # STIPES_WORKSPACE env override for testing.
    workspace = os.environ.get("STIPES_WORKSPACE", None)
    db = StipesDB(workspace=workspace)

    if not argv:
        print("usage: stipes.py <list|search <q>|stats|prune|test>", file=sys.stderr)
        # Default to list when run with no args.
        _cli_list(db, [])
        return

    cmd = argv[0].lower()

    if cmd == "list":
        _cli_list(db, argv)
    elif cmd == "search":
        _cli_search(db, argv)
    elif cmd == "stats":
        _cli_stats(db)
    elif cmd == "prune":
        _cli_prune(db)
    elif cmd == "test":
        _cli_test(db)
    else:
        print(f"unknown command: {cmd!r}", file=sys.stderr)
        print("available: list, search <q>, stats, prune, test", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
