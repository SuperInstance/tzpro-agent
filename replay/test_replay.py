"""replay/test_replay.py — unit tests for replay harness v0.

Tests:
1. Self-consistency: stub analyzer returns stored data → 1.0 agreement
2. Perturbed analyzer: shifts bottom_fm by 5 → low agreement
3. Determinism: two runs produce byte-identical reports
4. Empty day: clean error for missing data
5. Date validation: invalid date format raises ValueError
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from replay import replay


class TestReplayHarness(unittest.TestCase):
    """Test suite for replay harness."""

    def setUp(self):
        """Create a temporary twin with test data for each test."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.twin_root = Path(self.temp_dir.name)
        self.db_path = self.twin_root / "meta.db"
        self.blobs_dir = self.twin_root / "blobs"

        # Create database schema
        self._create_test_db()
        self._populate_test_data()

    def tearDown(self):
        """Clean up temporary directory."""
        self.temp_dir.cleanup()

    def _create_test_db(self):
        """Create the twin database schema."""
        conn = sqlite3.connect(str(self.db_path))
        cur = conn.cursor()

        # Frames table
        cur.execute("""
            CREATE TABLE frames (
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

        # Blobs table
        cur.execute("""
            CREATE TABLE blobs (
                sha256 TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                bytes INTEGER NOT NULL,
                tier TEXT NOT NULL DEFAULT 'hot',
                created INTEGER NOT NULL
            )
        """)

        # Echogram records table
        cur.execute("""
            CREATE TABLE echogram_records (
                frame_id TEXT PRIMARY KEY REFERENCES frames(frame_id),
                ts_utc INTEGER NOT NULL,
                depth_top_m REAL,
                depth_bot_m REAL,
                record_json TEXT NOT NULL,
                record_sha256 TEXT NOT NULL,
                vocab_terms TEXT,
                model TEXT,
                confidence REAL
            )
        """)

        # Notes table
        cur.execute("""
            CREATE TABLE notes (
                note_id TEXT PRIMARY KEY,
                ts_utc INTEGER NOT NULL,
                frame_id TEXT REFERENCES frames(frame_id),
                body TEXT,
                novelty REAL,
                retained INTEGER DEFAULT 0
            )
        """)

        conn.commit()
        conn.close()

    def _populate_test_data(self):
        """Populate database with 10 test frames and records."""
        conn = sqlite3.connect(str(self.db_path))
        cur = conn.cursor()

        # Create 10 frames with records
        for i in range(10):
            frame_id = f"frame_{i:010d}"
            sha256 = f"a{i:020x}{'b' * 20}{'c' * 36}"
            ts_utc = 1704067200000 + i * 60000  # Starting 2024-01-01, spaced by 1 minute

            # Insert blob
            cur.execute(
                "INSERT INTO blobs (sha256, path, bytes, tier, created) VALUES (?, ?, ?, ?, ?)",
                (sha256, f"blobs/{sha256[:2]}/{sha256[2:4]}/{sha256}.png", 12345, "hot", ts_utc)
            )

            # Insert frame
            cur.execute(
                """INSERT INTO frames (frame_id, ts_utc, lat, lon, sog, cog, sha256, bytes, tier, cadence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (frame_id, ts_utc, 57.0 + i * 0.01, -135.0 + i * 0.01, 5.0, 180.0, sha256, 12345, "hot", "10min-canonical")
            )

            # Create record with test data
            record = {
                "bottom_type": "hard" if i % 3 == 0 else ("soft" if i % 3 == 1 else "mixed"),
                "bottom_fm": 45.0 + i * 2.5,
                "search_terms": ["chum", "feed", "school"] if i % 2 == 0 else ["herring", "bait"],
                "summary": f"Test frame {i}",
            }
            record_json = json.dumps(record, separators=(",", ":"), sort_keys=True)

            cur.execute(
                """INSERT INTO echogram_records (frame_id, ts_utc, record_json, record_sha256, vocab_terms)
                   VALUES (?, ?, ?, ?, ?)""",
                (frame_id, ts_utc, record_json, "test_sha256", " ".join(record["search_terms"]))
            )

        # Create blob files
        for i in range(10):
            sha256 = f"a{i:020x}{'b' * 20}{'c' * 36}"
            blob_dir = self.blobs_dir / sha256[:2] / sha256[2:4]
            blob_dir.mkdir(parents=True, exist_ok=True)
            blob_path = blob_dir / f"{sha256}.png"
            blob_path.write_bytes(b"fake_png_data")

        conn.commit()
        conn.close()

    def test_self_consistency_stub_analyzer(self):
        """Test that stub analyzer yields 1.0 agreement (self-consistency)."""
        report = replay.replay_day(self.twin_root, "2024-01-01")

        self.assertEqual(report["date"], "2024-01-01")
        self.assertEqual(report["frames"], 10)
        self.assertEqual(report["replayed"], 10)
        self.assertEqual(report["agreement_rate"], 1.0)

        # All frames should agree
        for pf in report["per_frame"]:
            self.assertTrue(pf.get("agree", True), f"Frame {pf['frame_id']} should agree")

    def test_perturbed_analyzer_low_agreement(self):
        """Test that a perturbed analyzer produces low agreement."""
        def perturbed_analyzer(frame_path: Path, sidecar: dict) -> dict:
            # Shift bottom_fm by 5.0 (well beyond 3.0 threshold)
            result = replay._stub_analyzer(frame_path, sidecar)
            if result.get("bottom_fm") is not None:
                result["bottom_fm"] = result["bottom_fm"] + 5.0
            return result

        report = replay.replay_day(self.twin_root, "2024-01-01", perturbed_analyzer)

        # Agreement should be 0.0 since all bottom_fm values shifted by 5.0
        self.assertEqual(report["agreement_rate"], 0.0)

        # All frames should disagree with deltas
        for pf in report["per_frame"]:
            self.assertFalse(pf.get("agree", True), f"Frame {pf['frame_id']} should disagree")
            self.assertTrue(len(pf.get("deltas", [])) > 0)

    def test_determinism_identical_reports(self):
        """Test that two runs produce byte-identical JSON reports."""
        report1 = replay.replay_day(self.twin_root, "2024-01-01")
        report2 = replay.replay_day(self.twin_root, "2024-01-01")

        # Convert to JSON with sorted keys
        json1 = json.dumps(report1, sort_keys=True)
        json2 = json.dumps(report2, sort_keys=True)

        # Byte-for-byte identical
        self.assertEqual(json1, json2)

    def test_empty_day_error(self):
        """Test that querying an empty day raises RuntimeError."""
        with self.assertRaises(RuntimeError) as ctx:
            replay.load_day(self.twin_root, "2024-01-02")

        self.assertIn("No data found", str(ctx.exception))

    def test_invalid_date_format(self):
        """Test that invalid date format raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            replay.load_day(self.twin_root, "2024/01/01")

        self.assertIn("Invalid date format", str(ctx.exception))

    def test_load_day_structure(self):
        """Test that load_day returns correct structure."""
        day_data = replay.load_day(self.twin_root, "2024-01-01")

        self.assertIn("date", day_data)
        self.assertIn("frames", day_data)
        self.assertIn("records", day_data)
        self.assertIn("notes", day_data)

        # Check sorting (timestamp ascending)
        timestamps = [f["ts_utc"] for f in day_data["frames"]]
        self.assertEqual(timestamps, sorted(timestamps))

    def test_jaccard_similarity(self):
        """Test Jaccard similarity calculation."""
        # Identical sets
        self.assertEqual(replay._jaccard_similarity({"a", "b", "c"}, {"a", "b", "c"}), 1.0)

        # Disjoint sets
        self.assertEqual(replay._jaccard_similarity({"a", "b"}, {"c", "d"}), 0.0)

        # Partial overlap
        self.assertEqual(replay._jaccard_similarity({"a", "b", "c"}, {"b", "c", "d", "e"}), 0.4)

        # Empty sets
        self.assertEqual(replay._jaccard_similarity(set(), set()), 1.0)

        # One empty set
        self.assertEqual(replay._jaccard_similarity({"a"}, set()), 0.0)

    def test_compare_records_agreement(self):
        """Test record comparison logic."""
        # Use structure matching twin records (record_data nested)
        stored = {
            "record_data": {
                "bottom_type": "hard",
                "bottom_fm": 45.0,
                "search_terms": ["chum", "feed", "school"]
            }
        }

        # Identical record
        fresh_identical = {
            "bottom_type": "hard",
            "bottom_fm": 45.0,
            "search_terms": ["chum", "feed", "school"]
        }
        result = replay._compare_records(stored, fresh_identical)
        self.assertTrue(result["agree"])
        self.assertEqual(len(result["deltas"]), 0)

        # Bottom type mismatch
        fresh_type = {
            "bottom_type": "soft",
            "bottom_fm": 45.0,
            "search_terms": ["chum", "feed", "school"]
        }
        result = replay._compare_records(stored, fresh_type)
        self.assertFalse(result["agree"])

        # Bottom depth within tolerance (3.0)
        fresh_depth = {
            "bottom_type": "hard",
            "bottom_fm": 47.5,  # Delta of 2.5
            "search_terms": ["chum", "feed", "school"]
        }
        result = replay._compare_records(stored, fresh_depth)
        self.assertTrue(result["agree"])

        # Bottom depth outside tolerance
        fresh_deep = {
            "bottom_type": "hard",
            "bottom_fm": 50.0,  # Delta of 5.0
            "search_terms": ["chum", "feed", "school"]
        }
        result = replay._compare_records(stored, fresh_deep)
        self.assertFalse(result["agree"])

        # Search terms Jaccard threshold (0.3)
        fresh_terms = {
            "bottom_type": "hard",
            "bottom_fm": 45.0,
            "search_terms": ["herring", "bait"]  # Jaccard = 0.0
        }
        result = replay._compare_records(stored, fresh_terms)
        self.assertFalse(result["agree"])

        # Overlapping terms (Jaccard > 0.3)
        # ['chum', 'feed', 'school'] vs ['chum', 'feed', 'herring'] = 2/4 = 0.5
        fresh_overlap = {
            "bottom_type": "hard",
            "bottom_fm": 45.0,
            "search_terms": ["chum", "feed", "herring"]
        }
        result = replay._compare_records(stored, fresh_overlap)
        self.assertTrue(result["agree"])


if __name__ == "__main__":
    unittest.main()
