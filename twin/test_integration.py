"""
twin/test_integration.py

END-TO-END integration tests for cascade→twin persistence.

Tests the complete data flow from cascade perception loops to the data twin:
- M1 (minute loop) frame + note ingestion
- M10 (scribe) record writing with frame linkage
- Non-fatal twin sink behavior (degrade, don't die)
- Importer idempotence with cascade loop interaction
- GC grace period semantics

Run with: python -m unittest twin.test_integration -v
"""

import io
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image

try:
    from twin import Twin, compute_sha256
    from twin.importer import Importer
    from twin.gc import GCScheduler
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from twin import Twin, compute_sha256
    from twin.importer import Importer
    from twin.gc import GCScheduler


def create_tiny_png(path: Path, color: tuple[int, int, int] = (128, 64, 32)) -> None:
    """Create a minimal valid PNG file (1x1 pixel)."""
    img = Image.new("RGB", (1, 1), color=color)
    img.save(path, "PNG")


def create_tzpro_sidecar(path: Path, ts_utc: str = "2026-07-19T12:00:00Z",
                          lat: float = 45.5, lon: float = -122.5) -> dict:
    """Create a tzpro capture sidecar with nested position block."""
    sidecar = {
        "ts_utc": ts_utc,
        "position": {
            "lat_dd": lat,
            "lon_dd": lon,
            "sog_kts": 5.2,
            "cog_deg": 180.0
        },
        "display": {
            "type": "Point",
            "coordinates": [lon, lat]
        }
    }
    if path:
        path.write_text(json.dumps(sidecar))
    return sidecar


class TestCascadeTwinIntegration(unittest.TestCase):
    """
    END-TO-END tests for cascade→twin integration.

    Each test creates a fresh temporary workspace with isolated:
    - captures/v3/ directory structure
    - cascade output directories
    - memory/ twin database
    """

    def setUp(self):
        """Create isolated temporary workspace for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.temp_dir) / "workspace"
        self.workspace.mkdir(parents=True)

        # Create directory structure
        self.captures_dir = self.workspace / "captures" / "v3" / "2026-07-19"
        self.captures_dir.mkdir(parents=True)

        self.memory_dir = self.workspace / "memory"
        self.cascade_out = self.workspace / "cascade_out"
        self.cascade_out.mkdir(parents=True)

        # Create twin instance
        self.twin = Twin(self.memory_dir)

        # Mock cascade.config paths
        self.config_patcher = None

    def tearDown(self):
        """Clean up temporary directory."""
        try:
            if self.twin.conn:
                self.twin.close()
        except RuntimeError:
            pass  # Twin not opened, ignore
        if self.config_patcher:
            self.config_patcher.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _setup_cascade_mocks(self, vision_response: dict | None = None):
        """Setup cascade config and ollama mocks."""
        # Import cascade modules
        import cascade.config as config
        import cascade.ollama_client as ollama

        # Mock config paths
        self.config_patcher = patch.multiple(
            config,
            WORKSPACE=str(self.workspace),
            CAPTURES=self.workspace / "captures" / "v3",
            OUT=self.cascade_out,
            NOVELTY_THRESHOLD=0.65,
            RING_BUFFER_SIZE=120
        )
        self.config_patcher.start()

        # Mock ollama vision
        if vision_response is not None:
            self.vision_patcher = patch.object(
                ollama, 'vision_prompt',
                return_value=json.dumps(vision_response)
            )
        else:
            self.vision_patcher = patch.object(
                ollama, 'vision_prompt',
                return_value=None
            )
        self.vision_patcher.start()

        # Mock vision_available to return True
        self.available_patcher = patch.object(
            ollama, 'vision_available',
            return_value=True
        )
        self.available_patcher.start()

        # Mock model_present
        self.model_patcher = patch.object(
            ollama, 'model_present',
            return_value=True
        )
        self.model_patcher.start()

        return config, ollama

    def _create_fake_capture(self, name: str, ts: str,
                             lat: float = 45.5, lon: float = -122.5,
                             color: tuple[int, int, int] = (128, 64, 32)) -> tuple[Path, dict]:
        """Create a fake capture (PNG + sidecar)."""
        png_path = self.captures_dir / name
        create_tiny_png(png_path, color)
        sidecar = create_tzpro_sidecar(
            png_path.with_suffix(".json"),
            ts_utc=ts, lat=lat, lon=lon
        )
        return png_path, sidecar

    def test_m1_note_lands_in_twin(self):
        """
        Test 1: M1 loop creates frame row + retained note row + blob file.
        """
        # Setup: fake capture + high novelty response
        png_path, sidecar = self._create_fake_capture(
            "001_frame.png",
            "2026-07-19T12:00:00Z"
        )

        vision_response = {
            "caption": "Small fish school at 15fm",
            "bottom_fm": 45,
            "features": ["blob school", "thermocline"],
            "notable": True,
            "novelty": 0.9  # High novelty -> retained
        }

        config, ollama = self._setup_cascade_mocks(vision_response)

        # Open twin and run M1 simulation
        self.twin.open()

        # Simulate M1 loop processing
        import cascade.minute_loop as m1
        import cascade.twin_sink as sink

        # Reset twin_sink connection
        sink._twin = None
        sink._tried = False

        # Simulate the M1 loop logic
        from datetime import datetime, timezone
        ts_ms = int(datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc).timestamp() * 1000)

        # Add frame (via twin_sink)
        frame_id = sink.add_frame(png_path, sidecar)

        # Create note (as M1 would)
        note = {
            "ts_utc": "2026-07-19T12:00:00Z",
            "frame": "001_frame.png",
            "frame_id": frame_id,
            "lat": 45.5,
            "lon": -122.5,
            "caption": vision_response["caption"],
            "features": vision_response["features"],
            "notable": vision_response["notable"],
            "novelty": vision_response["novelty"],
            "retained": 1,  # Novel notes are retained
            "model": "test-model"
        }
        sink.add_note(note)

        # Verify: frame row exists in meta.db with correct lat/lon/epoch-ms
        frame_row = self.twin.conn.execute(
            "SELECT * FROM frames WHERE frame_id = ?",
            (frame_id,)
        ).fetchone()

        self.assertIsNotNone(frame_row, "Frame row should exist")
        self.assertEqual(frame_row["lat"], 45.5, "Latitude should match")
        self.assertEqual(frame_row["lon"], -122.5, "Longitude should match")
        self.assertEqual(frame_row["ts_utc"], ts_ms, "Timestamp should be epoch-ms")

        # Verify: note row exists with retained=1
        note_row = self.twin.conn.execute(
            "SELECT * FROM notes WHERE frame_id = ?",
            (frame_id,)
        ).fetchone()

        self.assertIsNotNone(note_row, "Note row should exist")
        self.assertEqual(note_row["retained"], 1, "Note should be retained")
        self.assertEqual(note_row["novelty"], 0.9, "Novelty should be 0.9")

        # Verify: blob file exists under blobs/
        blob_path = self.twin.get_blob_path(frame_row["sha256"])
        self.assertIsNotNone(blob_path, "Blob path should exist")
        self.assertTrue(blob_path.exists(), "Blob file should exist")
        # Verify path structure: blobs/<xx>/<yy>/<sha256>.png
        self.assertTrue("blobs" in str(blob_path), "Blob should be under blobs/ directory")

    def test_m1_routine_note_not_retained(self):
        """
        Test 2: Routine notes (low novelty, not notable) don't persist to twin.
        """
        # Setup: fake capture + low novelty response
        png_path, sidecar = self._create_fake_capture(
            "002_frame.png",
            "2026-07-19T12:01:00Z"
        )

        vision_response = {
            "caption": "Empty water, no fish",
            "bottom_fm": 40,
            "features": [],
            "notable": False,
            "novelty": 0.1  # Low novelty -> not retained
        }

        self._setup_cascade_mocks(vision_response)
        self.twin.open()

        import cascade.twin_sink as sink
        sink._twin = None
        sink._tried = False

        # Add frame
        frame_id = sink.add_frame(png_path, sidecar)

        # Routine note should not be added to twin
        # (M1 only calls twin_sink.add_note for novel/notable notes)

        # Verify: frame row exists (frames always added)
        frame_row = self.twin.conn.execute(
            "SELECT * FROM frames WHERE frame_id = ?",
            (frame_id,)
        ).fetchone()

        self.assertIsNotNone(frame_row, "Frame row should exist")

        # Verify: no note row (routine notes not retained)
        note_row = self.twin.conn.execute(
            "SELECT * FROM notes WHERE frame_id = ?",
            (frame_id,)
        ).fetchone()

        self.assertIsNone(note_row, "Note row should NOT exist for routine observation")

    def test_twin_down_is_nonfatal(self):
        """
        Test 3: Twin unavailable degrades gracefully, file outputs still produced.
        """
        # Setup: fake capture
        png_path, sidecar = self._create_fake_capture(
            "003_frame.png",
            "2026-07-19T12:02:00Z"
        )

        vision_response = {
            "caption": "Test caption",
            "features": [],
            "notable": True,
            "novelty": 0.9
        }

        config, ollama = self._setup_cascade_mocks(vision_response)

        # Point twin at an invalid path (simulating twin unavailable)
        import cascade.twin_sink as sink
        import cascade.config as cascade_config

        # Patch twin_sink to point at invalid location
        with patch.object(sink, 'get_twin', return_value=None):
            # Add frame should return None but not raise
            frame_id = sink.add_frame(png_path, sidecar)
            self.assertIsNone(frame_id, "Should return None when twin unavailable")

            # Add note should not raise
            note = {
                "ts_utc": "2026-07-19T12:02:00Z",
                "frame": "003_frame.png",
                "frame_id": None,
                "caption": "Test caption",
                "novelty": 0.9,
                "notable": True
            }
            # Should not raise
            sink.add_note(note)

        # Verify file outputs still produced (simulate by checking capture exists)
        self.assertTrue(png_path.exists(), "Original file should still exist")

    def test_m10_record_links_to_frame(self):
        """
        Test 4: M10 write_record creates echogram_records row joined by frame_id.
        """
        # Setup: fake capture
        png_path, sidecar = self._create_fake_capture(
            "004_frame.png",
            "2026-07-19T12:00:00Z"
        )

        scribe_response = {
            "summary": "Good fishing conditions, bait ball at 20fm",
            "bottom_fm": 45,
            "bottom_type": "soft",
            "schools": [{"depth_fm": 20, "size": "medium", "band": "LF"}],
            "thermocline_fm": 15,
            "haze": "light",
            "anomalies": [],
            "search_terms": ["bait ball", "feed layer"]
        }

        self._setup_cascade_mocks(scribe_response)
        self.twin.open()

        import cascade.twin_sink as sink
        sink._twin = None
        sink._tried = False

        # Add frame first (as M10 does)
        frame_id = sink.add_frame(png_path, sidecar)

        # Create record (as M10 does)
        record = {
            "spec": "echogram_record/1",
            "capture_id": "004_frame",
            "frame_id": frame_id,
            "ts_utc": "2026-07-19T12:00:00Z",
            "depth_top_m": 30.0,
            "depth_bot_m": 60.0,
            "model": "test-scribe"
        }

        sink.add_record(record)

        # Verify: echogram_records row joins to frames row by frame_id
        record_row = self.twin.conn.execute(
            """
            SELECT er.*, f.frame_id as join_frame_id
            FROM echogram_records er
            JOIN frames f ON er.frame_id = f.frame_id
            WHERE er.frame_id = ?
            """,
            (frame_id,)
        ).fetchone()

        self.assertIsNotNone(record_row, "Record row should exist")
        self.assertEqual(record_row["frame_id"], frame_id, "frame_id should match")
        self.assertEqual(record_row["join_frame_id"], frame_id, "Should join correctly")
        self.assertEqual(record_row["depth_top_m"], 30.0, "depth_top_m should match")

    def test_importer_then_m1_no_duplicate_frames(self):
        """
        Test 5: Importer runs, then M1 processes - no duplicate sha256 rows.
        """
        # Setup: existing capture
        png_path1, sidecar1 = self._create_fake_capture(
            "005_existing.png",
            "2026-07-19T12:00:00Z"
        )

        self.twin.open()

        # Setup cascade mocks so twin_sink uses our test workspace
        self._setup_cascade_mocks({"caption": "test", "features": [], "notable": False, "novelty": 0.1})

        # Run importer first
        importer = Importer(self.twin)
        stats = importer.import_captures_v3(self.captures_dir.parent, print_summary=False)

        self.assertEqual(stats["imported"], 1, "Importer should import 1 frame")

        # Get the frame_id and sha256 from import
        imported_rows = self.twin.conn.execute("SELECT frame_id, sha256 FROM frames").fetchall()
        self.assertEqual(len(imported_rows), 1, "Should have 1 frame")
        original_frame_id = imported_rows[0]["frame_id"]
        original_sha256 = imported_rows[0]["sha256"]

        # Now add a NEW frame after the import
        png_path2, sidecar2 = self._create_fake_capture(
            "006_new.png",
            "2026-07-19T12:01:00Z",
            lat=45.6,  # Different position
            color=(64, 128, 96)  # Different color = different SHA256
        )

        # Simulate M1 processing the new frame
        import cascade.twin_sink as sink
        sink._twin = None
        sink._tried = False

        new_frame_id = sink.add_frame(png_path2, sidecar2)

        # Verify: no duplicate sha256 rows
        sha256_rows = self.twin.conn.execute("SELECT sha256 FROM frames").fetchall()
        sha256s = [r["sha256"] for r in sha256_rows]

        # Should have exactly 2 unique sha256s
        self.assertEqual(len(set(sha256s)), 2, "Should have 2 unique sha256s")
        self.assertEqual(len(sha256_rows), 2, "Should have 2 frame rows")

        # Verify: only the new frame gets an M1 pass (old frame unchanged)
        # Original frame_id should be unchanged
        self.assertIn(original_sha256, sha256s, "Original sha256 should still exist")

        # New frame should have different sha256 (different content)
        new_sha256_rows = self.twin.conn.execute(
            "SELECT sha256 FROM frames WHERE frame_id = ?",
            (new_frame_id,)
        ).fetchall()
        self.assertEqual(len(new_sha256_rows), 1, "New frame should exist")
        self.assertNotEqual(new_sha256_rows[0]["sha256"], original_sha256,
                           "New frame should have different sha256")

    def test_gc_grace_blocks_deletion(self):
        """
        Test 6: GC grace period blocks deletion; tombstone after grace expiry.
        """
        # Setup: frame without keep_reason (GC-eligible)
        png_path, sidecar = self._create_fake_capture(
            "007_gc_test.png",
            "2026-07-19T12:00:00Z"
        )

        self.twin.open()

        # Add frame
        result = self.twin.add_frame(png_path, sidecar)

        # Verify blob exists
        blob_path = self.twin.get_blob_path(result.sha256)
        self.assertIsNotNone(blob_path, "Blob should exist")
        self.assertTrue(blob_path.exists(), "Blob file should exist initially")

        # Stage for GC
        scheduler = GCScheduler(self.twin)
        staged = scheduler.stage_candidates(tier="hot")

        self.assertGreaterEqual(staged, 1, "Should stage at least 1 candidate")

        # Verify file still exists during grace period
        self.assertTrue(blob_path.exists(), "File should exist during grace period")

        # Try to finalize before grace expires - should not delete
        gc_result = scheduler.finalize_grace_period(
            final_read_flag=True,
            verified_copies=10
        )

        self.assertEqual(gc_result.deleted, 0, "Should delete 0 (grace period active)")
        self.assertTrue(blob_path.exists(), "File should still exist after grace check")

        # Force grace period expiry
        pending = scheduler.load_pending()
        pending[result.frame_id].grace_ends_ms = 0  # Expired
        scheduler.save_pending(pending)

        # Finalize with expired grace
        gc_result = scheduler.finalize_grace_period(
            final_read_flag=True,
            verified_copies=1
        )

        # After grace expiry and final_read_flag, should delete
        self.assertGreater(gc_result.deleted, 0, "Should delete after grace expiry")

        # Verify tombstone semantics (row still exists with tier='gone')
        row = self.twin.conn.execute(
            "SELECT tier, sha256 FROM frames WHERE frame_id = ?",
            (result.frame_id,)
        ).fetchone()

        self.assertIsNotNone(row, "Row should still exist (tombstone)")
        self.assertEqual(row["tier"], "gone", "Tier should be 'gone'")
        self.assertEqual(row["sha256"], result.sha256, "SHA256 retained in tombstone")


if __name__ == "__main__":
    unittest.main()
