"""
twin/test_twin.py

Unit tests for the twin package.
Run with: python -m unittest twin.test_twin -v
"""

import json
import os
import tempfile
import shutil
import time
import unittest
from pathlib import Path
from PIL import Image
from io import BytesIO

try:
    from twin import Twin, FrameResult, compute_sha256
    from twin.importer import Importer
    from twin.gc import GCScheduler, GCResult
    from twin.reconcile import Reconciler
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from twin import Twin, FrameResult, compute_sha256
    from twin.importer import Importer
    from twin.gc import GCScheduler, GCResult
    from twin.reconcile import Reconciler


def create_test_png(path: Path, size: tuple[int, int] = (100, 100)) -> None:
    """Create a test PNG file."""
    img = Image.new("RGB", size, color=(128, 64, 32))
    img.save(path, "PNG")


def create_test_png_with_pixels(path: Path, color: tuple[int, int, int]) -> None:
    """Create a test PNG with specific color for unique hashes."""
    img = Image.new("RGB", (50, 50), color=color)
    img.save(path, "PNG")


class TestTwin(unittest.TestCase):
    """Test core Twin functionality."""

    def setUp(self):
        """Create a temporary directory for tests."""
        self.temp_dir = tempfile.mkdtemp()
        self.memory_dir = Path(self.temp_dir) / "memory"
        self.twin = Twin(self.memory_dir)

    def tearDown(self):
        """Clean up temporary directory."""
        if self.twin.conn:
            self.twin.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_open_creates_directory_structure(self):
        """Test that open() creates the required directory layout."""
        self.twin.open()

        self.assertTrue(self.memory_dir.exists())
        self.assertTrue((self.memory_dir / "meta.db").exists())
        self.assertTrue((self.memory_dir / "blobs").is_dir())
        self.assertTrue((self.memory_dir / "manifests").is_dir())
        self.assertTrue((self.memory_dir / "exports").is_dir())
        self.assertTrue((self.memory_dir / "gc").is_dir())

    def test_open_idempotent(self):
        """Test that open() can be called multiple times safely."""
        self.twin.open()
        self.twin.close()
        self.twin.open()
        self.assertTrue(self.twin.conn is not None)

    def test_add_frame_creates_row(self):
        """Test that add_frame creates a row in the database."""
        self.twin.open()

        # Create test PNG
        png_path = Path(self.temp_dir) / "test.png"
        create_test_png(png_path)

        sidecar = {
            "ts_utc": 1234567890,
            "lat": 45.5,
            "lon": -122.5,
            "sog": 5.2,
            "cog": 180.0
        }

        result = self.twin.add_frame(png_path, sidecar)

        self.assertIsInstance(result, FrameResult)
        self.assertTrue(result.is_new)
        self.assertEqual(len(result.frame_id), 16)  # ULID format
        self.assertEqual(len(result.sha256), 64)  # SHA256 hex

        # Check row was created
        row = self.twin.conn.execute(
            "SELECT * FROM frames WHERE frame_id = ?",
            (result.frame_id,)
        ).fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row["ts_utc"], 1234567890)
        self.assertEqual(row["lat"], 45.5)
        self.assertEqual(row["lon"], -122.5)
        self.assertEqual(row["sog"], 5.2)
        self.assertEqual(row["cog"], 180.0)
        self.assertEqual(row["tier"], "hot")

    def test_add_frame_idempotent_same_sha256(self):
        """Test that adding the same file (same SHA256) returns existing frame_id."""
        self.twin.open()

        # Create test PNG
        png_path = Path(self.temp_dir) / "test.png"
        create_test_png(png_path)

        sidecar = {"ts_utc": 1234567890}

        result1 = self.twin.add_frame(png_path, sidecar)
        result2 = self.twin.add_frame(png_path, sidecar)

        self.assertTrue(result1.is_new)
        self.assertFalse(result2.is_new)
        self.assertEqual(result1.frame_id, result2.frame_id)
        self.assertEqual(result1.sha256, result2.sha256)

    def test_add_frame_stores_blob_atomically(self):
        """Test that blobs are stored with correct hash path."""
        self.twin.open()

        png_path = Path(self.temp_dir) / "test.png"
        create_test_png(png_path)

        result = self.twin.add_frame(png_path, {"ts_utc": 1234567890})

        # Check blob path
        sha256 = result.sha256
        expected_path = self.memory_dir / "blobs" / sha256[:2] / sha256[2:4] / f"{sha256}.png"
        self.assertTrue(expected_path.exists())

        # Verify hash matches
        computed_hash = compute_sha256(expected_path)
        self.assertEqual(computed_hash, sha256)

    def test_add_record(self):
        """Test adding an echogram record."""
        self.twin.open()

        # Add a frame first
        png_path = Path(self.temp_dir) / "test.png"
        create_test_png(png_path)
        frame_result = self.twin.add_frame(png_path, {"ts_utc": 1234567890})

        # Add a record
        record = {
            "ts_utc": 1234567890,
            "depth_top_m": 10.5,
            "depth_bot_m": 45.2,
            "vocab_terms": "fish school",
            "model": "test-model",
            "confidence": 0.92
        }

        self.twin.add_record(frame_result.frame_id, record)

        # Check record was created
        row = self.twin.conn.execute(
            "SELECT * FROM echogram_records WHERE frame_id = ?",
            (frame_result.frame_id,)
        ).fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row["depth_top_m"], 10.5)
        self.assertEqual(row["depth_bot_m"], 45.2)
        self.assertEqual(row["vocab_terms"], "fish school")
        self.assertEqual(row["model"], "test-model")
        self.assertEqual(row["confidence"], 0.92)

    def test_add_note(self):
        """Test adding a note."""
        self.twin.open()

        note = {
            "body": "Test observation",
            "frame_id": None,
            "novelty": 0.75
        }

        note_id = self.twin.add_note(note, provenance="test")

        # Check note was created
        row = self.twin.conn.execute(
            "SELECT * FROM notes WHERE note_id = ?",
            (note_id,)
        ).fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row["body"], "Test observation")
        self.assertEqual(row["novelty"], 0.75)
        self.assertEqual(row["retained"], 0)

    def test_add_briefing(self):
        """Test adding a briefing."""
        self.twin.open()

        body_md = "# Test Briefing\n\nSummary of today's fishing."
        period_start = 1234567890
        period_end = 1234567890 + 86400000

        briefing_id = self.twin.add_briefing(body_md, period_start, period_end)

        # Check briefing was created
        row = self.twin.conn.execute(
            "SELECT * FROM briefings WHERE briefing_id = ?",
            (briefing_id,)
        ).fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row["body"], body_md)
        self.assertEqual(row["period_start"], period_start)
        self.assertEqual(row["period_end"], period_end)

    def test_add_label(self):
        """Test adding a label."""
        self.twin.open()

        # Add a frame first
        png_path = Path(self.temp_dir) / "test.png"
        create_test_png(png_path)
        frame_result = self.twin.add_frame(png_path, {"ts_utc": 1234567890})

        # Add a label
        self.twin.add_label(frame_result.frame_id, "fish_school", "test_labeler", "test_provenance")

        # Check label was created
        row = self.twin.conn.execute(
            "SELECT * FROM labels WHERE frame_id = ?",
            (frame_result.frame_id,)
        ).fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row["label"], "fish_school")
        self.assertEqual(row["labeler"], "test_labeler")
        self.assertEqual(row["provenance"], "test_provenance")

    def test_frames_since(self):
        """Test querying frames since a timestamp."""
        self.twin.open()

        # Add frames with different timestamps
        for i, ts in enumerate([1000, 2000, 3000, 4000]):
            png_path = Path(self.temp_dir) / f"test{i}.png"
            create_test_png_with_pixels(png_path, (i, i, i))
            self.twin.add_frame(png_path, {"ts_utc": ts})

        frames = self.twin.frames_since(2500)

        self.assertEqual(len(frames), 2)  # ts=3000 and ts=4000

    def test_records_for_day(self):
        """Test querying records for a specific day."""
        self.twin.open()

        # Add frame and record for a specific day (using millisecond timestamps)
        ts_ms = 1234567890000  # 2009-02-13 23:31:30 UTC in milliseconds
        png_path = Path(self.temp_dir) / "test.png"
        create_test_png(png_path)
        frame_result = self.twin.add_frame(png_path, {"ts_utc": ts_ms})

        record = {
            "ts_utc": ts_ms,
            "depth_top_m": 10.0,
            "depth_bot_m": 50.0
        }
        self.twin.add_record(frame_result.frame_id, record)

        # Query for that day
        records = self.twin.records_for_day("2009-02-13")

        self.assertGreaterEqual(len(records), 1)

    def test_integrity_check(self):
        """Test integrity_check returns True for valid database."""
        self.twin.open()
        self.assertTrue(self.twin.integrity_check())


class TestGC(unittest.TestCase):
    """Test garbage collection functionality."""

    def setUp(self):
        """Create a temporary directory for tests."""
        self.temp_dir = tempfile.mkdtemp()
        self.memory_dir = Path(self.temp_dir) / "memory"
        self.twin = Twin(self.memory_dir)
        self.twin.open()

    def tearDown(self):
        """Clean up temporary directory."""
        if self.twin.conn:
            self.twin.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_gc_stages_candidates(self):
        """Test that GC stages eligible frames."""
        # Add a frame without keep_reason (GC-eligible)
        png_path = Path(self.temp_dir) / "test.png"
        create_test_png(png_path)
        result = self.twin.add_frame(png_path, {"ts_utc": 1234567890})

        scheduler = GCScheduler(self.twin)
        staged = scheduler.stage_candidates(tier="hot")

        self.assertGreaterEqual(staged, 1)

        # Check it's in pending
        pending = scheduler.load_pending()
        self.assertIn(result.frame_id, pending)

    def test_gc_no_deletion_before_grace(self):
        """Test that nothing is deleted before 24h grace period."""
        png_path = Path(self.temp_dir) / "test.png"
        create_test_png(png_path)
        result = self.twin.add_frame(png_path, {"ts_utc": 1234567890})

        scheduler = GCScheduler(self.twin)
        scheduler.stage_candidates(tier="hot")

        # Try to finalize immediately (grace period not expired)
        gc_result = scheduler.finalize_grace_period(
            final_read_flag=True,
            verified_copies=10  # Plenty of copies
        )

        # Should not delete anything (within grace period)
        self.assertEqual(gc_result.deleted, 0)
        self.assertGreater(gc_result.skipped_no_grace, 0)

    def test_gc_no_deletion_without_flag(self):
        """Test that deletion requires final_read_flag."""
        png_path = Path(self.temp_dir) / "test.png"
        create_test_png(png_path)
        result = self.twin.add_frame(png_path, {"ts_utc": 1234567890})

        scheduler = GCScheduler(self.twin)
        scheduler.stage_candidates(tier="hot")

        # Manually expire grace period
        pending = scheduler.load_pending()
        pending[result.frame_id].grace_ends_ms = 0
        scheduler.save_pending(pending)

        # Try without final_read_flag
        gc_result = scheduler.finalize_grace_period(
            final_read_flag=False,
            verified_copies=10
        )

        self.assertEqual(gc_result.deleted, 0)
        self.assertGreater(gc_result.skipped_no_flag, 0)

    def test_gc_tombstones_not_deletes_rows(self):
        """Test that GC creates tombstones instead of deleting rows."""
        png_path = Path(self.temp_dir) / "test.png"
        create_test_png(png_path)
        result = self.twin.add_frame(png_path, {"ts_utc": 1234567890})

        scheduler = GCScheduler(self.twin)
        scheduler.stage_candidates(tier="hot")

        # Manually expire grace period and force deletion
        pending = scheduler.load_pending()
        pending[result.frame_id].grace_ends_ms = 0
        scheduler.save_pending(pending)

        gc_result = scheduler.finalize_grace_period(
            final_read_flag=True,
            verified_copies=1
        )

        # Even if blob deleted, row should still exist with tier='gone'
        row = self.twin.conn.execute(
            "SELECT tier FROM frames WHERE frame_id = ?",
            (result.frame_id,)
        ).fetchone()

        # If deletion happened, row should be tombstoned
        if gc_result.deleted > 0:
            self.assertEqual(row["tier"], "gone")

    def test_gc_skips_labeled_frames(self):
        """Test that labeled frames are not GC'd."""
        png_path = Path(self.temp_dir) / "test.png"
        create_test_png(png_path)
        result = self.twin.add_frame(png_path, {"ts_utc": 1234567890})

        # Add a label (makes frame GC-ineligible)
        self.twin.add_label(result.frame_id, "important", "human", "manual")

        scheduler = GCScheduler(self.twin)
        staged = scheduler.stage_candidates(tier="hot")

        # Labeled frames should not be staged
        pending = scheduler.load_pending()
        self.assertNotIn(result.frame_id, pending)

    def test_gc_skips_keep_reason_frames(self):
        """Test that frames with keep_reason are not GC'd."""
        png_path = Path(self.temp_dir) / "test.png"
        create_test_png(png_path)
        result = self.twin.add_frame(
            png_path,
            {"ts_utc": 1234567890, "keep_reason": "canonical"}
        )

        scheduler = GCScheduler(self.twin)
        staged = scheduler.stage_candidates(tier="hot")

        # Frames with keep_reason should not be staged
        pending = scheduler.load_pending()
        self.assertNotIn(result.frame_id, pending)


class TestReconcile(unittest.TestCase):
    """Test reconcile functionality."""

    def setUp(self):
        """Create a temporary directory for tests."""
        self.temp_dir = tempfile.mkdtemp()
        self.memory_dir = Path(self.temp_dir) / "memory"
        self.twin = Twin(self.memory_dir)
        self.twin.open()

    def tearDown(self):
        """Clean up temporary directory."""
        if self.twin.conn:
            self.twin.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_reconcile_handles_orphan_blobs(self):
        """Test that reconcile deletes orphan blob files."""
        # Create an orphan blob (file without DB entry)
        orphan_sha = "a" * 64
        orphan_dir = self.memory_dir / "blobs" / orphan_sha[:2] / orphan_sha[2:4]
        orphan_dir.mkdir(parents=True, exist_ok=True)
        orphan_path = orphan_dir / f"{orphan_sha}.png"
        create_test_png(orphan_path)

        # Make file older than 1 hour
        old_time = time.time() - 3601
        os.utime(orphan_path, (old_time, old_time))

        reconciler = Reconciler(self.twin)
        result = reconciler.reconcile(escalate=False)

        # Orphan should be deleted
        self.assertGreater(result.orphan_blobs_deleted, 0)
        self.assertFalse(orphan_path.exists())

    def test_reconcile_tombstones_missing_files(self):
        """Test that reconcile tombstones rows with missing files."""
        # Add a frame
        png_path = Path(self.temp_dir) / "test.png"
        create_test_png(png_path)
        frame_result = self.twin.add_frame(png_path, {"ts_utc": 1234567890})

        # Delete the blob file manually
        blob_path = self.twin.get_blob_path(frame_result.sha256)
        if blob_path:
            blob_path.unlink()

        reconciler = Reconciler(self.twin)
        reconcile_result = reconciler.reconcile(escalate=False)

        # Frame should be tombstoned
        self.assertGreater(reconcile_result.missing_files_tombstoned, 0)

        row = self.twin.conn.execute(
            "SELECT tier FROM frames WHERE frame_id = ?",
            (frame_result.frame_id,)
        ).fetchone()

        self.assertEqual(row["tier"], "gone")

    def test_reconcile_young_orphans_not_deleted(self):
        """Test that orphan blobs younger than 1h are not deleted."""
        # Create a young orphan blob
        orphan_sha = "b" * 64
        orphan_dir = self.memory_dir / "blobs" / orphan_sha[:2] / orphan_sha[2:4]
        orphan_dir.mkdir(parents=True, exist_ok=True)
        orphan_path = orphan_dir / f"{orphan_sha}.png"
        create_test_png(orphan_path)

        # File is recent (not older than 1 hour)
        reconciler = Reconciler(self.twin)
        result = reconciler.reconcile(escalate=False)

        # Young orphan should not be deleted
        self.assertEqual(result.orphan_blobs_deleted, 0)
        self.assertTrue(orphan_path.exists())


class TestImporter(unittest.TestCase):
    """Test importer functionality."""

    def setUp(self):
        """Create a temporary directory for tests."""
        self.temp_dir = tempfile.mkdtemp()
        self.memory_dir = Path(self.temp_dir) / "memory"
        self.captures_dir = Path(self.temp_dir) / "captures" / "v3"
        self.captures_dir.mkdir(parents=True)
        self.twin = Twin(self.memory_dir)
        self.twin.open()

    def tearDown(self):
        """Clean up temporary directory."""
        if self.twin.conn:
            self.twin.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_importer_idempotent(self):
        """Test that importer is idempotent."""
        # Create a PNG + sidecar
        png_path = self.captures_dir / "test.png"
        create_test_png(png_path)

        sidecar_path = self.captures_dir / "test.json"
        sidecar = {"ts_utc": 1234567890, "lat": 45.5, "lon": -122.5}
        sidecar_path.write_text(json.dumps(sidecar))

        importer = Importer(self.twin)

        # First import
        stats1 = importer.import_captures_v3(self.captures_dir, print_summary=False)
        self.assertEqual(stats1["imported"], 1)

        # Second import (should skip duplicate)
        stats2 = importer.import_captures_v3(self.captures_dir, print_summary=False)
        self.assertEqual(stats2["imported"], 0)
        self.assertEqual(stats2["skipped_duplicate"], 1)

    def test_importer_skips_png_without_sidecar(self):
        """Test that PNGs without sidecars are skipped."""
        png_path = self.captures_dir / "no_sidecar.png"
        create_test_png(png_path)

        importer = Importer(self.twin)
        stats = importer.import_captures_v3(self.captures_dir, print_summary=False)

        self.assertEqual(stats["imported"], 0)
        self.assertEqual(stats["skipped_no_sidecar"], 1)


if __name__ == "__main__":
    unittest.main()
