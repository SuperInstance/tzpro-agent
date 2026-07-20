"""
twin/gc.py

Two-phase garbage collection per docs/18_DATA_TWIN_STORAGE.md.

- Stage candidates in gc/pending.json with 24h grace period
- Only delete after grace AND:
  (a) evening final read flag set
  (b) verified-copy count >= required_copies
- GC'd frames become tombstones (tier='gone'), never row deletes
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional


@dataclass
class GCCandidate:
    """A candidate for garbage collection."""
    frame_id: str
    sha256: str
    staged_at_ms: int
    reason: str
    grace_ends_ms: int


@dataclass
class GCResult:
    """Result of a GC run."""
    staged: int
    deleted: int
    skipped_no_grace: int
    skipped_no_flag: int
    skipped_no_copies: int
    total_pending: int


class GCScheduler:
    """
    Two-phase garbage collection scheduler.

    Phase 1: Stage GC candidates in gc/pending.json with 24h grace
    Phase 2: Delete blobs after grace period + conditions met
    """

    DEFAULT_GRACE_MS = 24 * 60 * 60 * 1000  # 24 hours

    def __init__(self, twin, required_copies: int = 1) -> None:
        """
        Initialize the GC scheduler.

        Args:
            twin: A Twin instance.
            required_copies: Minimum verified copies before deletion (default 1).
        """
        self._twin = twin
        self._required_copies = required_copies

    @property
    def pending_file(self) -> Path:
        """Path to gc/pending.json."""
        return self._twin.root / "gc" / "pending.json"

    def load_pending(self) -> dict[str, GCCandidate]:
        """Load pending GC candidates from gc/pending.json."""
        if not self.pending_file.exists():
            return {}

        try:
            data = json.loads(self.pending_file.read_text())
            return {
                frame_id: GCCandidate(**item)
                for frame_id, item in data.items()
            }
        except Exception:
            return {}

    def save_pending(self, pending: dict[str, GCCandidate]) -> None:
        """
        Save pending GC candidates to gc/pending.json atomically.

        Args:
            pending: Dictionary of pending candidates.
        """
        # Atomic write via temp file
        import tempfile
        tmp_path = None

        try:
            with tempfile.NamedTemporaryFile(
                dir=self.pending_file.parent,
                prefix=".tmp_pending_",
                suffix=".json",
                delete=False
            ) as tmp:
                tmp_path = Path(tmp.name)
                tmp.write(json.dumps(
                    {fid: asdict(c) for fid, c in pending.items()},
                    indent=2
                ).encode())

            os.replace(tmp_path, self.pending_file)
        except Exception:
            if tmp_path and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise

    def stage_candidates(
        self,
        tier: str = "hot",
        reason: str = "gc_candidate"
    ) -> int:
        """
        Stage GC-eligible frames for deletion.

        Finds frames without keep_reason (canonical/novel/labeled/human).

        Args:
            tier: Only stage frames in this tier (default 'hot').
            reason: Reason for GC staging.

        Returns:
            Number of frames staged.
        """
        if not self._twin.conn:
            raise RuntimeError("Twin not open.")

        cur = self._twin.conn.cursor()

        # Find GC-eligible frames (no keep_reason, not already staged)
        now_ms = int(time.time() * 1000)
        pending = self.load_pending()

        candidates = cur.execute("""
            SELECT frame_id, sha256, ts_utc
            FROM frames
            WHERE tier = ? AND keep_reason IS NULL
            AND frame_id NOT IN (SELECT frame_id FROM labels)
        """, (tier,)).fetchall()

        staged = 0
        for row in candidates:
            frame_id = row["frame_id"]
            if frame_id in pending:
                continue

            pending[frame_id] = GCCandidate(
                frame_id=frame_id,
                sha256=row["sha256"],
                staged_at_ms=now_ms,
                reason=reason,
                grace_ends_ms=now_ms + self.DEFAULT_GRACE_MS
            )
            staged += 1

        if staged > 0:
            self.save_pending(pending)

        return staged

    def finalize_grace_period(
        self,
        final_read_flag: bool = False,
        verified_copies: int = 0
    ) -> GCResult:
        """
        Finalize GC for candidates past their grace period.

        Only deletes blobs if:
        - Grace period has ended
        - final_read_flag is True (evening final read)
        - verified_copies >= required_copies

        Returns:
            GCResult with statistics.
        """
        if not self._twin.conn:
            raise RuntimeError("Twin not open.")

        pending = self.load_pending()
        now_ms = int(time.time() * 1000)

        result = GCResult(
            staged=0,
            deleted=0,
            skipped_no_grace=0,
            skipped_no_flag=0,
            skipped_no_copies=0,
            total_pending=len(pending)
        )

        # Check each candidate
        to_delete = []
        for frame_id, candidate in pending.items():
            if now_ms < candidate.grace_ends_ms:
                result.skipped_no_grace += 1
                continue

            if not final_read_flag:
                result.skipped_no_flag += 1
                continue

            if verified_copies < self._required_copies:
                result.skipped_no_copies += 1
                continue

            to_delete.append((frame_id, candidate.sha256))

        # Delete blobs and tombstone frames
        cur = self._twin.conn.cursor()

        for frame_id, sha256 in to_delete:
            try:
                # Get blob path
                blob_row = cur.execute(
                    "SELECT path FROM blobs WHERE sha256 = ?",
                    (sha256,)
                ).fetchone()

                if blob_row:
                    blob_path = self._twin.root / blob_row["path"]
                    if blob_path.exists():
                        blob_path.unlink()

                # Tombstone the frame (tier='gone', keep sha256)
                cur.execute("""
                    UPDATE frames
                    SET tier = 'gone', keep_reason = NULL
                    WHERE frame_id = ?
                """, (frame_id,))

                # Remove from pending
                del pending[frame_id]
                result.deleted += 1

            except Exception:
                pass  # Skip failed deletions

        # Commit and save pending
        self._twin.conn.commit()

        if result.deleted > 0:
            self.save_pending(pending)

        return result

    def get_pending_summary(self) -> dict[str, Any]:
        """
        Get a summary of pending GC candidates.

        Returns:
            Dictionary with pending statistics.
        """
        pending = self.load_pending()
        now_ms = int(time.time() * 1000)

        summary = {
            "total": len(pending),
            "ready_for_deletion": 0,
            "within_grace": 0,
            "reasons": {}
        }

        for candidate in pending.values():
            if now_ms >= candidate.grace_ends_ms:
                summary["ready_for_deletion"] += 1
            else:
                summary["within_grace"] += 1

            reason = candidate.reason
            summary["reasons"][reason] = summary["reasons"].get(reason, 0) + 1

        return summary


def gc_main(memory_dir: str, dry_run: bool = False) -> None:
    """
    CLI entry point for GC.

    Args:
        memory_dir: Path to memory/ directory.
        dry_run: If True, print pending but don't delete.
    """
    from .twin import Twin

    twin = Twin(Path(memory_dir))

    with twin:
        scheduler = GCScheduler(twin, required_copies=1)

        # Stage new candidates
        staged = scheduler.stage_candidates()

        # Print summary
        summary = scheduler.get_pending_summary()
        print("\n=== GC Status ===")
        print(f"Pending candidates:    {summary['total']}")
        print(f"Ready for deletion:    {summary['ready_for_deletion']}")
        print(f"Within grace period:   {summary['within_grace']}")
        print(f"Newly staged:          {staged}")

        if not dry_run:
            # Finalize past grace (with final_read_flag=False by default)
            result = scheduler.finalize_grace_period(final_read_flag=False)
            print(f"\n=== GC Results ===")
            print(f"Deleted:                {result.deleted}")
            print(f"Skipped (no grace):     {result.skipped_no_grace}")
            print(f"Skipped (no flag):      {result.skipped_no_flag}")
            print(f"Skipped (no copies):    {result.skipped_no_copies}")
        else:
            print("\nDry run: no deletions performed.")
        print("==================\n")


if __name__ == "__main__":
    import sys

    dry_run = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--dry-run"]

    if len(args) < 1:
        print("Usage: python -m twin.gc <memory_dir> [--dry-run]")
        sys.exit(1)

    gc_main(args[0], dry_run)
