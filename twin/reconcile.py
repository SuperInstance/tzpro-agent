"""
twin/reconcile.py

Startup sweep per docs/18_DATA_TWIN_STORAGE.md.

- Orphan blobs (file, no row, >1h old) -> delete
- Rows with missing files -> tier='gone' + print escalation line
"""

from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ReconcileResult:
    """Result of a reconcile sweep."""
    orphan_blobs_deleted: int
    missing_files_tombstoned: int
    missing_files_escalated: list[dict]


class Reconciler:
    """
    Reconcile blob/DB divergence per docs/18.

    Startup sweep:
    1. Orphan blobs (file exists, no row, >1h old) -> delete
    2. Rows with missing files -> tier='gone' + escalation event
    """

    ONE_HOUR_MS = 60 * 60 * 1000

    def __init__(self, twin) -> None:
        """
        Initialize the reconciler.

        Args:
            twin: A Twin instance.
        """
        self._twin = twin

    def reconcile(self, escalate: bool = True) -> ReconcileResult:
        """
        Run startup reconcile sweep.

        Args:
            escalate: If True, print escalation lines for missing files.

        Returns:
            ReconcileResult with statistics.
        """
        if not self._twin.conn:
            raise RuntimeError("Twin not open.")

        result = ReconcileResult(
            orphan_blobs_deleted=0,
            missing_files_tombstoned=0,
            missing_files_escalated=[]
        )

        cur = self._twin.conn.cursor()

        # Step 1: Find orphan blobs (files without rows)
        result.orphan_blobs_deleted = self._delete_orphan_blobs(cur)

        # Step 2: Find rows with missing files
        missing = self._find_missing_files(cur)

        # Tombstone and escalate
        for frame_id, sha256 in missing:
            cur.execute("""
                UPDATE frames
                SET tier = 'gone', keep_reason = NULL
                WHERE frame_id = ?
            """, (frame_id,))

            result.missing_files_tombstoned += 1
            result.missing_files_escalated.append({
                "frame_id": frame_id,
                "sha256": sha256
            })

            if escalate:
                self._escalate_missing_file(frame_id, sha256)

        self._twin.conn.commit()

        return result

    def _delete_orphan_blobs(self, cur: sqlite3.Cursor) -> int:
        """
        Delete blob files that have no corresponding row and are >1h old.

        Args:
            cur: Database cursor.

        Returns:
            Number of orphan blobs deleted.
        """
        blobs_dir = self._twin.root / "blobs"
        if not blobs_dir.exists():
            return 0

        # Get all known SHA256s from the database
        known_hashes = set()
        for row in cur.execute("SELECT sha256 FROM blobs"):
            known_hashes.add(row["sha256"])

        # Get all known SHA256s from frames
        for row in cur.execute("SELECT DISTINCT sha256 FROM frames"):
            known_hashes.add(row["sha256"])

        deleted = 0
        now_ms = int(time.time() * 1000)

        # Walk the blobs directory
        for prefix_dir in blobs_dir.iterdir():
            if not prefix_dir.is_dir() or len(prefix_dir.name) != 2:
                continue

            for subdir in prefix_dir.iterdir():
                if not subdir.is_dir() or len(subdir.name) != 2:
                    continue

                for blob_file in subdir.glob("*.png"):
                    # Extract SHA256 from filename
                    sha256 = blob_file.stem

                    if sha256 in known_hashes:
                        continue

                    # Check file age (>1h old)
                    file_age_ms = now_ms - int(blob_file.stat().st_mtime * 1000)
                    if file_age_ms < self.ONE_HOUR_MS:
                        continue

                    # Delete orphan blob
                    try:
                        blob_file.unlink()
                        deleted += 1
                    except Exception:
                        pass  # Skip files we can't delete

        return deleted

    def _find_missing_files(self, cur: sqlite3.Cursor) -> list[tuple[str, str]]:
        """
        Find frames whose blob files are missing.

        Args:
            cur: Database cursor.

        Returns:
            List of (frame_id, sha256) tuples for frames with missing blobs.
        """
        missing = []

        for row in cur.execute("SELECT frame_id, sha256, tier FROM frames WHERE tier != 'gone'"):
            frame_id = row["frame_id"]
            sha256 = row["sha256"]

            blob_path = self._twin.get_blob_path(sha256)
            if blob_path is None or not blob_path.exists():
                missing.append((frame_id, sha256))

        return missing

    def _escalate_missing_file(self, frame_id: str, sha256: str) -> None:
        """
        Escalate a missing file event (prime directive 5).

        Prints an escalation line to alert operators.

        Args:
            frame_id: The frame ID with missing blob.
            sha256: The SHA256 of the missing blob.
        """
        print(f"ESCALATION: Frame {frame_id} has missing blob file {sha256}. Data loss detected.")


def reconcile_main(memory_dir: str) -> None:
    """
    CLI entry point for reconcile.

    Args:
        memory_dir: Path to memory/ directory.
    """
    from .twin import Twin

    twin = Twin(Path(memory_dir))

    with twin:
        reconciler = Reconciler(twin)
        result = reconciler.reconcile(escalate=True)

        print("\n=== Reconcile Results ===")
        print(f"Orphan blobs deleted:   {result.orphan_blobs_deleted}")
        print(f"Missing files found:    {result.missing_files_tombstoned}")
        print("=========================\n")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m twin.reconcile <memory_dir>")
        sys.exit(1)

    reconcile_main(sys.argv[1])
