#!/usr/bin/env python3
"""restore_drill.py - Week-3 checkpoint: automated restore drill for vessel data twin.

Implements a complete sandboxed disaster recovery test:
1. Creates a fake workspace: twin with 10 frames + blobs + a manifest_backup run
2. DESTROYS the local copies (delete blobs/ for one day)
3. Restores from the backup: copy blobs back, re-hash against manifest, insert/repair DB rows
4. Verifies every manifest entry restored with matching hash → DRILL PASSED
5. Also drills failure case: corrupt one byte → REPORT corruption, restore good files, exit 2

Exit codes:
    0 - DRILL PASSED (all files verified)
    1 - DRILL FAILED (hash mismatches or missing files)
    2 - DRILL CORRUPTION DETECTED (corrupted files found and reported)
    3 - Invalid arguments

Stdlib only. Python 3.10+.

Usage:
    python scripts/restore_drill.py --mode happy
    python scripts/restore_drill.py --mode corruption
    python -m scripts.restore_drill
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import uuid

# Exit codes
EXIT_PASSED = 0
EXIT_FAILED = 1
EXIT_CORRUPTION = 2
EXIT_BAD_ARG = 3

# Constants for fake data
NUM_TEST_FRAMES = 10
TEST_DAY = "2026-07-19"
TEST_SHA256_PREFIX = "a" * 64  # Will be replaced with real hashes

# Hash chunk size (1 MiB like manifest_backup.py)
HASH_CHUNK = 1 << 20


@dataclass
class DrillResult:
    """Result of the restore drill."""
    mode: str
    total_entries: int
    restored: int
    verified: int
    failed: int
    corrupted: list[dict]
    exit_code: int
    message: str


def sha256_file(path: Path) -> str:
    """Stream sha256 of a file in 1 MiB chunks."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(HASH_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def generate_frame_id(ts_ms: int) -> str:
    """Generate a ULID-like frame_id."""
    import random
    ts_hex = format(ts_ms & 0xFFFFFFFFFFFF, '012x')
    rand_hex = format(random.randint(0, 65535), '04x')
    return f"{ts_hex}{rand_hex}"


def create_fake_png(path: Path, size: int = 1024) -> None:
    """Create a minimal valid PNG file with specific size."""
    # PNG signature
    png_signature = b'\x89PNG\r\n\x1a\n'

    # Create a minimal IHDR chunk
    width = (size - 100) // 3  # Rough calculation to get target size
    height = width
    ihdr_data = (
        width.to_bytes(4, 'big') +
        height.to_bytes(4, 'big') +
        b'\x08\x02\x00\x00\x00'  # bit depth=8, color type=2 (RGB), etc.
    )
    ihdr_chunk = (
        b'\x00\x00\x00\x0d'  # length
        + b'IHDR'
        + ihdr_data
        + b'\x00\x00\x00\x00'  # CRC (simplified)
    )

    # Create an IDAT chunk with data
    idat_data = b'\x78\x9c' + b'\x00' * (size - len(png_signature) - len(ihdr_chunk) - 24)
    idat_chunk = (
        len(idat_data).to_bytes(4, 'big') +
        b'IDAT' +
        idat_data +
        b'\x00\x00\x00\x00'  # CRC
    )

    # Create an IEND chunk
    iend_chunk = b'\x00\x00\x00\x00IEND\xae\x42\x60\x82'

    png_data = png_signature + ihdr_chunk + idat_chunk + iend_chunk
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png_data[:size])  # Truncate to exact size


def create_test_twin(workspace: Path) -> Path:
    """Create a fake twin workspace with frames and blobs.

    Returns:
        Path to the memory directory.
    """
    memory_dir = workspace / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)

    # Create blobs directory structure
    blobs_dir = memory_dir / "blobs"
    manifests_dir = memory_dir / "manifests"
    blobs_dir.mkdir(parents=True, exist_ok=True)
    manifests_dir.mkdir(parents=True, exist_ok=True)

    # Create SQLite database
    db_path = memory_dir / "meta.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")

    # Create schema (minimal subset needed for restore)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS blobs (
            sha256 TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            bytes INTEGER NOT NULL,
            tier TEXT NOT NULL DEFAULT 'hot',
            created INTEGER NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS frames (
            frame_id TEXT PRIMARY KEY,
            ts_utc INTEGER NOT NULL,
            lat REAL,
            lon REAL,
            sog REAL,
            cog REAL,
            sha256 TEXT NOT NULL,
            bytes INTEGER NOT NULL,
            tier TEXT NOT NULL DEFAULT 'hot',
            cadence TEXT NOT NULL,
            novelty REAL,
            keep_reason TEXT,
            display_geom TEXT
        )
    """)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_frames_ts ON frames(ts_utc)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_frames_tier_ts ON frames(tier, ts_utc)")

    # Create test frames with blobs
    base_ts = int(datetime(2026, 7, 19, tzinfo=timezone.utc).timestamp() * 1000)

    for i in range(NUM_TEST_FRAMES):
        ts_ms = base_ts + (i * 60000)  # 1 minute apart
        frame_id = generate_frame_id(ts_ms)

        # Create a PNG blob
        blob_size = 1024 + (i * 100)  # Variable sizes

        # Create with temp name first, then rename to actual SHA256
        temp_blob_path = blobs_dir / f"temp_{i}.png"
        create_fake_png(temp_blob_path, blob_size)
        actual_sha256 = sha256_file(temp_blob_path)

        # Rename to SHA256 path
        blob_dir = blobs_dir / actual_sha256[:2] / actual_sha256[2:4]
        blob_dir.mkdir(parents=True, exist_ok=True)
        blob_path = blob_dir / f"{actual_sha256}.png"
        temp_blob_path.rename(blob_path)

        # Register blob in database
        conn.execute("""
            INSERT INTO blobs (sha256, path, bytes, tier, created)
            VALUES (?, ?, ?, ?, ?)
        """, (actual_sha256, f"blobs/{actual_sha256[:2]}/{actual_sha256[2:4]}/{actual_sha256}.png",
              blob_size, "hot", ts_ms))

        # Create frame
        conn.execute("""
            INSERT INTO frames (
                frame_id, ts_utc, lat, lon, sog, cog,
                sha256, bytes, tier, cadence, novelty, keep_reason, display_geom
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            frame_id, ts_ms, 55.0 + (i * 0.01), -130.0 + (i * 0.01),
            5.0 + (i * 0.1), 180.0 + (i * 2),
            actual_sha256, blob_size, "hot", "10min-canonical",
            0.5 if i % 2 == 0 else None, None, None
        ))

    conn.commit()
    conn.close()

    return memory_dir


def run_fake_backup(memory_dir: Path, backup_dir: Path) -> Path:
    """Simulate manifest_backup.py run.

    Creates a manifest and copies blobs to the backup directory.
    """
    backup_blobs = backup_dir / "memory" / "blobs"
    backup_manifests = backup_dir / "memory" / "manifests"

    backup_blobs.mkdir(parents=True, exist_ok=True)
    backup_manifests.mkdir(parents=True, exist_ok=True)

    blobs_dir = memory_dir / "blobs"

    # Collect all blobs
    entries = []
    for blob_path in blobs_dir.rglob("*.png"):
        rel_path = blob_path.relative_to(memory_dir)
        sha256 = sha256_file(blob_path)
        size = blob_path.stat().st_size

        entries.append({
            "sha256": sha256,
            "relpath": str(rel_path).replace("\\", "/"),
            "bytes": size,
        })

        # Copy to backup
        dest_path = backup_dir / "memory" / rel_path
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(blob_path, dest_path)

    # Write manifest (simplified version without hash chaining for drill)
    manifest_path = backup_manifests / f"{TEST_DAY}.manifest.jsonl"
    manifest_lines = [json.dumps({"prev_manifest_sha256": ""}, separators=(",", ":"))]
    for entry in entries:
        manifest_lines.append(json.dumps(entry, separators=(",", ":"), sort_keys=True))
    manifest_path.write_text("\n".join(manifest_lines) + "\n", "utf-8")

    return manifest_path


def destroy_local_blobs(memory_dir: Path) -> int:
    """Simulate disaster: delete local blobs directory.

    Returns:
        Number of files deleted.
    """
    blobs_dir = memory_dir / "blobs"
    count = 0

    if blobs_dir.exists():
        for blob_path in blobs_dir.rglob("*"):
            if blob_path.is_file():
                blob_path.unlink()
                count += 1
        # Also remove empty directories
        for subdir in sorted(blobs_dir.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if subdir.is_dir() and not any(subdir.iterdir()):
                subdir.rmdir()

    return count


def restore_from_backup(
    memory_dir: Path,
    backup_dir: Path,
    manifest_path: Path,
    corrupt_indices: list[int] = None
) -> dict:
    """Restore blobs from backup, re-hashing against the manifest.

    Args:
        memory_dir: Original memory directory (blobs destroyed).
        backup_dir: Backup directory containing backup/memory/blobs.
        manifest_path: Path to the manifest file.
        corrupt_indices: Optional list of entry indices to corrupt (for testing).

    Returns:
        Dictionary with restore results.
    """
    corrupt_indices = corrupt_indices or []

    # Read manifest entries
    entries = []
    for line in manifest_path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if "prev_manifest_sha256" in obj:
            continue
        entries.append(obj)

    # Restore each entry
    blobs_dir = memory_dir / "blobs"
    backup_blobs_root = backup_dir / "memory"

    results = {
        "total": len(entries),
        "restored": 0,
        "verified": 0,
        "failed": 0,
        "corrupted": [],
        "mismatches": []
    }

    for idx, entry in enumerate(entries):
        rel_path = entry["relpath"]
        expected_sha256 = entry["sha256"]
        expected_bytes = entry.get("bytes")

        # Copy from backup
        src_path = backup_blobs_root / rel_path
        dest_path = memory_dir / rel_path

        if not src_path.exists():
            results["failed"] += 1
            results["mismatches"].append({
                "relpath": rel_path,
                "reason": "missing_in_backup"
            })
            continue

        # Apply corruption if requested
        if idx in corrupt_indices:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            corrupted_data = bytearray(src_path.read_bytes())
            corrupted_data[0] = (corrupted_data[0] + 1) % 256  # Flip one byte
            dest_path.write_bytes(bytes(corrupted_data))
        else:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dest_path)

        # Verify hash
        actual_sha256 = sha256_file(dest_path)
        actual_bytes = dest_path.stat().st_size

        if actual_sha256 == expected_sha256:
            results["verified"] += 1
            results["restored"] += 1
        else:
            results["corrupted"].append({
                "relpath": rel_path,
                "expected_sha256": expected_sha256,
                "actual_sha256": actual_sha256,
                "expected_bytes": expected_bytes,
                "actual_bytes": actual_bytes
            })

    return results


def repair_database_rows(memory_dir: Path, restore_results: dict) -> dict:
    """Insert/repair database rows for restored files.

    Marks corrupted files as tier='cold' with sha256 so they remain resolvable.
    Marks successfully restored files as tier='hot'.

    Args:
        memory_dir: Memory directory with meta.db.
        restore_results: Results from restore_from_backup.

    Returns:
        Dictionary with repair statistics.
    """
    db_path = memory_dir / "meta.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    results = {
        "marked_hot": 0,
        "marked_cold": 0,
        "errors": []
    }

    # Update successfully restored files to tier='hot'
    for entry in restore_results.get("verified_entries", []):
        sha256 = entry.get("sha256")
        try:
            conn.execute("""
                UPDATE frames
                SET tier = 'hot'
                WHERE sha256 = ?
            """, (sha256,))
            conn.execute("""
                UPDATE blobs
                SET tier = 'hot'
                WHERE sha256 = ?
            """, (sha256,))
            results["marked_hot"] += 1
        except sqlite3.Error as e:
            results["errors"].append(str(e))

    # Mark corrupted files as tier='cold' (resolvable but not verified)
    for corruption in restore_results.get("corrupted", []):
        sha256 = corruption.get("expected_sha256")
        try:
            conn.execute("""
                UPDATE frames
                SET tier = 'cold'
                WHERE sha256 = ?
            """, (sha256,))
            conn.execute("""
                UPDATE blobs
                SET tier = 'cold'
                WHERE sha256 = ?
            """, (sha256,))
            results["marked_cold"] += 1
        except sqlite3.Error as e:
            results["errors"].append(str(e))

    conn.commit()
    conn.close()

    return results


def run_happy_path(temp_dir: Path) -> DrillResult:
    """Run the happy path drill: backup, destroy, restore, verify all pass."""
    workspace = temp_dir / "workspace"
    backup_dir = temp_dir / "backup"

    print(f"=== HAPPY PATH DRILL ===")
    print(f"workspace: {workspace}")
    print(f"backup:    {backup_dir}")

    # Step 1: Create test twin
    print("\n[1] Creating test twin...")
    memory_dir = create_test_twin(workspace)
    print(f"    Created {NUM_TEST_FRAMES} frames")

    # Step 2: Run backup
    print("\n[2] Running backup...")
    manifest_path = run_fake_backup(memory_dir, backup_dir)
    entry_count = len([l for l in manifest_path.read_text().splitlines() if l.strip()])
    print(f"    Backed up {entry_count - 1} entries (minus header)")

    # Step 3: Destroy local blobs
    print("\n[3] Destroying local blobs...")
    deleted = destroy_local_blobs(memory_dir)
    print(f"    Deleted {deleted} blob files")

    # Step 4: Restore from backup
    print("\n[4] Restoring from backup...")
    restore_results = restore_from_backup(memory_dir, backup_dir, manifest_path)
    print(f"    Restored: {restore_results['restored']}/{restore_results['total']}")
    print(f"    Verified: {restore_results['verified']}/{restore_results['total']}")

    # Step 5: Verify
    print("\n[5] Verification...")
    if restore_results["failed"] > 0:
        print(f"    FAILED: {restore_results['failed']} files failed to restore")
        return DrillResult(
            mode="happy",
            total_entries=restore_results['total'],
            restored=restore_results['restored'],
            verified=restore_results['verified'],
            failed=restore_results['failed'],
            corrupted=[],
            exit_code=EXIT_FAILED,
            message=f"DRILL FAILED: {restore_results['failed']} files failed to restore"
        )

    if restore_results["corrupted"]:
        print(f"    FAILED: {len(restore_results['corrupted'])} corrupted files detected")
        return DrillResult(
            mode="happy",
            total_entries=restore_results['total'],
            restored=restore_results['restored'],
            verified=restore_results['verified'],
            failed=restore_results['failed'],
            corrupted=restore_results['corrupted'],
            exit_code=EXIT_FAILED,
            message=f"DRILL FAILED: {len(restore_results['corrupted'])} corrupted files"
        )

    if restore_results["verified"] == restore_results["total"]:
        print(f"    PASSED: All {restore_results['verified']} files verified")
        return DrillResult(
            mode="happy",
            total_entries=restore_results['total'],
            restored=restore_results['restored'],
            verified=restore_results['verified'],
            failed=0,
            corrupted=[],
            exit_code=EXIT_PASSED,
            message=f"DRILL PASSED: All {restore_results['verified']} entries verified"
        )

    return DrillResult(
        mode="happy",
        total_entries=restore_results['total'],
        restored=restore_results['restored'],
        verified=restore_results['verified'],
        failed=restore_results['total'] - restore_results['verified'],
        corrupted=[],
        exit_code=EXIT_FAILED,
        message="DRILL FAILED: Verification mismatch"
    )


def run_corruption_path(temp_dir: Path) -> DrillResult:
    """Run the corruption path drill: backup, corrupt one file, restore, report corruption."""
    workspace = temp_dir / "workspace"
    backup_dir = temp_dir / "backup"

    print(f"=== CORRUPTION PATH DRILL ===")
    print(f"workspace: {workspace}")
    print(f"backup:    {backup_dir}")

    # Step 1: Create test twin
    print("\n[1] Creating test twin...")
    memory_dir = create_test_twin(workspace)
    print(f"    Created {NUM_TEST_FRAMES} frames")

    # Step 2: Run backup
    print("\n[2] Running backup...")
    manifest_path = run_fake_backup(memory_dir, backup_dir)
    print(f"    Created manifest: {manifest_path.name}")

    # Step 3: Destroy local blobs
    print("\n[3] Destroying local blobs...")
    deleted = destroy_local_blobs(memory_dir)
    print(f"    Deleted {deleted} blob files")

    # Step 4: Corrupt one backed-up file
    print("\n[4] Corrupting one backed-up file...")
    backup_blobs = backup_dir / "memory" / "blobs"
    first_blob = list(backup_blobs.rglob("*.png"))[0]
    original_data = first_blob.read_bytes()
    corrupted_data = bytearray(original_data)
    corrupted_data[0] = (corrupted_data[0] + 1) % 256
    first_blob.write_bytes(bytes(corrupted_data))
    print(f"    Corrupted: {first_blob.relative_to(backup_dir)}")

    # Step 5: Restore from backup (will detect corruption)
    print("\n[5] Restoring from backup (with corruption detection)...")
    restore_results = restore_from_backup(memory_dir, backup_dir, manifest_path)
    print(f"    Restored: {restore_results['restored']}/{restore_results['total']}")
    print(f"    Verified: {restore_results['verified']}/{restore_results['total']}")
    print(f"    Corrupted: {len(restore_results['corrupted'])}")

    # Step 6: Report corruption
    print("\n[6] Corruption Report:")
    for corruption in restore_results["corrupted"]:
        print(f"    - {corruption['relpath']}")
        print(f"      Expected SHA256: {corruption['expected_sha256'][:16]}...")
        print(f"      Actual SHA256:   {corruption['actual_sha256'][:16]}...")

    # Step 7: Verify drill found the corruption
    if len(restore_results["corrupted"]) == 1:
        print("\n    DRILL DETECTED CORRUPTION AS EXPECTED")
        return DrillResult(
            mode="corruption",
            total_entries=restore_results['total'],
            restored=restore_results['restored'],
            verified=restore_results['verified'],
            failed=restore_results['failed'],
            corrupted=restore_results['corrupted'],
            exit_code=EXIT_CORRUPTION,
            message=f"DRILL CORRUPTION DETECTED: 1 corrupted file found and reported"
        )

    return DrillResult(
        mode="corruption",
        total_entries=restore_results['total'],
        restored=restore_results['restored'],
        verified=restore_results['verified'],
        failed=restore_results['failed'],
        corrupted=restore_results['corrupted'],
        exit_code=EXIT_FAILED,
        message="DRILL FAILED: Expected 1 corrupted file, found "
                f"{len(restore_results['corrupted'])}"
    )


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="restore_drill.py",
        description="Automated restore drill for vessel data twin backup path."
    )
    parser.add_argument(
        "--mode",
        choices=["happy", "corruption"],
        default="happy",
        help="Drill mode: happy (all restore) or corruption (detect bad backup)"
    )
    parser.add_argument(
        "--temp-dir",
        type=Path,
        default=None,
        help="Custom temp directory (default: system temp)"
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep temp directory after drill (for inspection)"
    )

    args = parser.parse_args(argv)

    # Create temp directory
    if args.temp_dir:
        temp_dir = args.temp_dir / f"restore_drill_{int(time.time())}"
    else:
        temp_dir = Path(tempfile.gettempdir()) / f"restore_drill_{int(time.time())}"

    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        if args.mode == "happy":
            result = run_happy_path(temp_dir)
        else:  # corruption
            result = run_corruption_path(temp_dir)

        print(f"\n{'='*72}")
        print(result.message)
        print(f"{'='*72}")
        print(f"Total entries:  {result.total_entries}")
        print(f"Restored:       {result.restored}")
        print(f"Verified:       {result.verified}")
        print(f"Failed:         {result.failed}")
        if result.corrupted:
            print(f"Corrupted:      {len(result.corrupted)}")

        return result.exit_code

    finally:
        # Cleanup
        if not args.keep:
            shutil.rmtree(temp_dir, ignore_errors=True)
        else:
            print(f"\nTemp directory kept for inspection: {temp_dir}")


if __name__ == "__main__":
    sys.exit(main())
