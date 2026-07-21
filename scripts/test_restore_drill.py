#!/usr/bin/env python3
"""test_restore_drill.py - unittest suite for restore_drill.py.

Tests both the happy path (full restore) and corruption path (detect bad backup).
Stdlib only. Run until green.

Usage:
    python -m pytest scripts/test_restore_drill.py -v
    python scripts/test_restore_drill.py
    python -m unittest scripts.test_restore_drill
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
import unittest
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.restore_drill import (
    sha256_file,
    create_fake_png,
    create_test_twin,
    run_fake_backup,
    destroy_local_blobs,
    restore_from_backup,
    main as restore_drill_main,
    EXIT_PASSED,
    EXIT_FAILED,
    EXIT_CORRUPTION,
)


class TestRestoreDrillHelpers(unittest.TestCase):
    """Test helper functions used by the restore drill."""

    def setUp(self):
        """Create temp directory for each test."""
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        """Clean up temp directory."""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_sha256_file(self):
        """Test SHA256 hash computation."""
        # Create a test file
        test_file = self.temp_dir / "test.bin"
        test_data = b"Hello, World!"
        test_file.write_bytes(test_data)

        # Known hash for "Hello, World!"
        expected = "dffd6021bb2bd5b0af676290809ec3a53191dd81c7f70a4b28688a362182986f"
        actual = sha256_file(test_file)
        self.assertEqual(actual, expected)

    def test_sha256_file_chunked(self):
        """Test SHA256 with chunked reading (large file)."""
        # Create a larger file (>1 MiB to test chunking)
        test_file = self.temp_dir / "large.bin"
        test_data = b"x" * (2 << 20)  # 2 MiB
        test_file.write_bytes(test_data)

        # Compute hash
        actual = sha256_file(test_file)

        # Verify it's a valid SHA256 (64 hex chars)
        self.assertEqual(len(actual), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in actual))

    def test_create_fake_png(self):
        """Test fake PNG creation."""
        png_path = self.temp_dir / "test.png"
        size = 2048
        create_fake_png(png_path, size)

        # Verify file exists and has correct size
        self.assertTrue(png_path.exists())
        self.assertEqual(png_path.stat().st_size, size)

        # Verify PNG signature
        with png_path.open("rb") as f:
            signature = f.read(8)
            self.assertEqual(signature, b'\x89PNG\r\n\x1a\n')


class TestCreateTestTwin(unittest.TestCase):
    """Test twin workspace creation."""

    def setUp(self):
        """Create temp directory."""
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        """Clean up temp directory."""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_create_test_twin(self):
        """Test creating a test twin workspace."""
        workspace = self.temp_dir / "workspace"
        memory_dir = create_test_twin(workspace)

        # Verify directory structure
        self.assertTrue(memory_dir.exists())
        self.assertTrue((memory_dir / "blobs").exists())
        self.assertTrue((memory_dir / "manifests").exists())
        self.assertTrue((memory_dir / "meta.db").exists())

        # Verify database has frames
        conn = sqlite3.connect(memory_dir / "meta.db")
        conn.row_factory = sqlite3.Row
        frames = conn.execute("SELECT COUNT(*) as count FROM frames").fetchone()
        self.assertEqual(frames["count"], 10)

        # Verify blobs exist
        blob_count = len(list((memory_dir / "blobs").rglob("*.png")))
        self.assertEqual(blob_count, 10)

        conn.close()

    def test_twin_blob_hash_consistency(self):
        """Test that blob SHA256 hashes match between files and database."""
        workspace = self.temp_dir / "workspace"
        memory_dir = create_test_twin(workspace)

        conn = sqlite3.connect(memory_dir / "meta.db")
        conn.row_factory = sqlite3.Row

        # Get all frames with their sha256
        frames = conn.execute("SELECT frame_id, sha256 FROM frames").fetchall()

        for frame in frames:
            # Find the blob file
            sha256 = frame["sha256"]
            blob_path = memory_dir / "blobs" / sha256[:2] / sha256[2:4] / f"{sha256}.png"

            # Verify file exists and hash matches
            self.assertTrue(blob_path.exists(), f"Blob missing for {frame['frame_id']}")
            actual_hash = sha256_file(blob_path)
            self.assertEqual(actual_hash, sha256, f"Hash mismatch for {frame['frame_id']}")

        conn.close()


class TestFakeBackup(unittest.TestCase):
    """Test fake backup creation."""

    def setUp(self):
        """Create temp directory and twin."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.workspace = self.temp_dir / "workspace"
        self.backup_dir = self.temp_dir / "backup"
        self.memory_dir = create_test_twin(self.workspace)

    def tearDown(self):
        """Clean up temp directory."""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_run_fake_backup(self):
        """Test running a fake backup."""
        manifest_path = run_fake_backup(self.memory_dir, self.backup_dir)

        # Verify manifest exists
        self.assertTrue(manifest_path.exists())
        self.assertEqual(manifest_path.name, "2026-07-19.manifest.jsonl")

        # Verify manifest structure
        lines = manifest_path.read_text().splitlines()
        self.assertGreater(len(lines), 1)  # Header + entries

        # First line should be hash chain header
        header = json.loads(lines[0])
        self.assertIn("prev_manifest_sha256", header)

        # Subsequent lines should be file entries
        for line in lines[1:]:
            entry = json.loads(line)
            self.assertIn("sha256", entry)
            self.assertIn("relpath", entry)
            self.assertIn("bytes", entry)

        # Verify backup blobs were copied
        backup_blobs = self.backup_dir / "memory" / "blobs"
        blob_count = len(list(backup_blobs.rglob("*.png")))
        self.assertEqual(blob_count, 10)

    def test_backup_manifest_integrity(self):
        """Test that backup manifest has correct file hashes."""
        manifest_path = run_fake_backup(self.memory_dir, self.backup_dir)

        # Read manifest entries
        entries = []
        for line in manifest_path.read_text().splitlines():
            obj = json.loads(line.strip())
            if "sha256" in obj and "relpath" in obj:
                entries.append(obj)

        # Verify each entry
        for entry in entries:
            backup_path = self.backup_dir / "memory" / entry["relpath"]
            self.assertTrue(backup_path.exists(), f"Backup missing: {entry['relpath']}")

            # Verify hash matches
            actual_hash = sha256_file(backup_path)
            self.assertEqual(actual_hash, entry["sha256"], f"Hash mismatch for {entry['relpath']}")

            # Verify size matches
            actual_size = backup_path.stat().st_size
            self.assertEqual(actual_size, entry["bytes"], f"Size mismatch for {entry['relpath']}")


class TestDestroyLocalBlobs(unittest.TestCase):
    """Test local blob destruction."""

    def setUp(self):
        """Create temp directory and twin."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.workspace = self.temp_dir / "workspace"
        self.memory_dir = create_test_twin(self.workspace)

    def tearDown(self):
        """Clean up temp directory."""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_destroy_local_blobs(self):
        """Test destroying local blobs."""
        blobs_dir = self.memory_dir / "blobs"

        # Verify blobs exist
        self.assertTrue(blobs_dir.exists())
        initial_count = len(list(blobs_dir.rglob("*.png")))
        self.assertGreater(initial_count, 0)

        # Destroy
        deleted = destroy_local_blobs(self.memory_dir)
        self.assertEqual(deleted, initial_count)

        # Verify blobs are gone
        remaining = len(list(blobs_dir.rglob("*.png")))
        self.assertEqual(remaining, 0)


class TestRestoreFromBackup(unittest.TestCase):
    """Test restore from backup functionality."""

    def setUp(self):
        """Create temp directory, twin, and backup."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.workspace = self.temp_dir / "workspace"
        self.backup_dir = self.temp_dir / "backup"
        self.memory_dir = create_test_twin(self.workspace)
        self.manifest_path = run_fake_backup(self.memory_dir, self.backup_dir)
        destroy_local_blobs(self.memory_dir)

    def tearDown(self):
        """Clean up temp directory."""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_restore_from_backup(self):
        """Test restoring from backup."""
        results = restore_from_backup(
            self.memory_dir,
            self.backup_dir,
            self.manifest_path
        )

        # All files should be restored and verified
        self.assertEqual(results["total"], 10)
        self.assertEqual(results["restored"], 10)
        self.assertEqual(results["verified"], 10)
        self.assertEqual(results["failed"], 0)
        self.assertEqual(len(results["corrupted"]), 0)

    def test_restore_creates_correct_files(self):
        """Test that restored files have correct content."""
        restore_from_backup(
            self.memory_dir,
            self.backup_dir,
            self.manifest_path
        )

        # Read manifest for expected hashes
        entries = []
        for line in self.manifest_path.read_text().splitlines():
            obj = json.loads(line.strip())
            if "sha256" in obj and "relpath" in obj:
                entries.append(obj)

        # Verify each restored file
        for entry in entries:
            restored_path = self.memory_dir / entry["relpath"]
            self.assertTrue(restored_path.exists(), f"File not restored: {entry['relpath']}")

            # Verify hash
            actual_hash = sha256_file(restored_path)
            self.assertEqual(actual_hash, entry["sha256"], f"Hash mismatch: {entry['relpath']}")

    def test_restore_with_corruption(self):
        """Test restore detects corrupted backup."""
        # Corrupt one backed-up file
        backup_blobs = self.backup_dir / "memory" / "blobs"
        first_blob = list(backup_blobs.rglob("*.png"))[0]
        original_data = first_blob.read_bytes()
        corrupted_data = bytearray(original_data)
        corrupted_data[0] = (corrupted_data[0] + 1) % 256
        first_blob.write_bytes(bytes(corrupted_data))

        # Restore should detect corruption
        results = restore_from_backup(
            self.memory_dir,
            self.backup_dir,
            self.manifest_path
        )

        # Should have 9 verified, 1 corrupted
        self.assertEqual(results["total"], 10)
        self.assertEqual(results["verified"], 9)
        self.assertEqual(len(results["corrupted"]), 1)

        # Corruption details should be correct
        corruption = results["corrupted"][0]
        self.assertIn("relpath", corruption)
        self.assertIn("expected_sha256", corruption)
        self.assertIn("actual_sha256", corruption)
        self.assertNotEqual(corruption["expected_sha256"], corruption["actual_sha256"])


class TestHappyPathDrill(unittest.TestCase):
    """Test the complete happy path drill."""

    def test_happy_path_drill(self):
        """Test that happy path drill completes successfully."""
        temp_dir = Path(tempfile.mkdtemp())

        try:
            # Run happy path drill
            result = restore_drill_main([
                "--mode", "happy",
                "--temp-dir", str(temp_dir)
            ])

            # Should return EXIT_PASSED
            self.assertEqual(result, EXIT_PASSED)

        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

    def test_happy_path_creates_correct_structure(self):
        """Test that happy path creates correct directory structure."""
        temp_dir = Path(tempfile.mkdtemp())

        try:
            drill_dir = temp_dir / f"restore_drill_{int(time.time())}"
            restore_drill_main([
                "--mode", "happy",
                "--temp-dir", str(temp_dir),
                "--keep"
            ])

            # Verify workspace was created
            workspace = drill_dir / "workspace"
            self.assertTrue(workspace.exists())
            self.assertTrue((workspace / "memory").exists())

            # Verify backup was created
            backup = drill_dir / "backup"
            self.assertTrue(backup.exists())

        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)


class TestCorruptionPathDrill(unittest.TestCase):
    """Test the corruption detection drill."""

    def test_corruption_path_drill(self):
        """Test that corruption path drill detects and reports corruption."""
        temp_dir = Path(tempfile.mkdtemp())

        try:
            # Run corruption path drill
            result = restore_drill_main([
                "--mode", "corruption",
                "--temp-dir", str(temp_dir)
            ])

            # Should return EXIT_CORRUPTION (2)
            self.assertEqual(result, EXIT_CORRUPTION)

        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

    def test_corruption_path_reports_details(self):
        """Test that corruption path reports corruption details."""
        temp_dir = Path(tempfile.mkdtemp())

        try:
            # Run corruption path drill with --keep to inspect results
            result = restore_drill_main([
                "--mode", "corruption",
                "--temp-dir", str(temp_dir),
                "--keep"
            ])

            # Find the drill directory
            drill_dirs = list(temp_dir.glob("restore_drill_*"))
            if drill_dirs:
                drill_dir = drill_dirs[0]
                workspace = drill_dir / "workspace"
                memory_dir = workspace / "memory"

                # Verify some files were restored
                restored_blobs = list((memory_dir / "blobs").rglob("*.png"))
                self.assertGreater(len(restored_blobs), 0)

        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)


class TestDrillExitCodes(unittest.TestCase):
    """Test drill exit codes for different scenarios."""

    def test_happy_path_exit_code(self):
        """Test happy path returns 0."""
        temp_dir = Path(tempfile.mkdtemp())
        try:
            result = restore_drill_main([
                "--mode", "happy",
                "--temp-dir", str(temp_dir)
            ])
            self.assertEqual(result, EXIT_PASSED)
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

    def test_corruption_path_exit_code(self):
        """Test corruption path returns 2."""
        temp_dir = Path(tempfile.mkdtemp())
        try:
            result = restore_drill_main([
                "--mode", "corruption",
                "--temp-dir", str(temp_dir)
            ])
            self.assertEqual(result, EXIT_CORRUPTION)
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)


def run_tests():
    """Run all tests and return exit code."""
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
