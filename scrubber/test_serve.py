"""
scrubber/test_serve.py

Unittest suite for the scrubber server.

Creates a temporary twin database with 5 fake frames+records+blobs,
starts the server on a test port, and verifies all endpoints.
"""

import http.server
import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.request
from http.client import HTTPConnection
from pathlib import Path


# Test server configuration
TEST_HOST = "127.0.0.1"
TEST_PORT = 8765


def create_fixture_db(workspace: Path) -> None:
    """
    Create a minimal test twin database with 5 frames and records.
    """
    memory_dir = workspace / "memory"
    blobs_dir = memory_dir / "blobs"
    db_path = memory_dir / "meta.db"

    memory_dir.mkdir(parents=True, exist_ok=True)
    blobs_dir.mkdir(parents=True, exist_ok=True)

    # Create fake PNG blob (1x1 transparent PNG)
    fake_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'

    # Create 5 fake blobs
    sha256_list = []
    for i in range(5):
        import hashlib
        data = fake_png + str(i).encode()
        sha256 = hashlib.sha256(data).hexdigest()
        sha256_list.append(sha256)

        blob_dir = blobs_dir / sha256[:2] / sha256[2:4]
        blob_dir.mkdir(parents=True, exist_ok=True)
        blob_path = blob_dir / f"{sha256}.png"
        blob_path.write_bytes(data)

    # Create database
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Create schema
    cur.execute("""
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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS echogram_records (
            frame_id TEXT PRIMARY KEY,
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

    # Insert 5 frames at 10-minute intervals starting from 2024-07-19 12:00:00 UTC
    base_ts = int(time.mktime((2024, 7, 19, 12, 0, 0, 0, 0, 0)) * 1000)

    for i, sha256 in enumerate(sha256_list):
        ts_ms = base_ts + i * 600000  # 10-minute intervals
        frame_id = f"test_frame_{i}"

        # Insert frame
        cur.execute(
            """
            INSERT INTO frames (
                frame_id, ts_utc, lat, lon, sog, cog, sha256, bytes,
                tier, cadence, novelty, keep_reason, display_geom
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                frame_id,
                ts_ms,
                55.123 + i * 0.01,
                -131.456 - i * 0.01,
                2.0 + i * 0.1,
                45.0 + i * 5,
                sha256,
                len(fake_png) + i,
                "hot",
                "10min-canonical",
                0.5 + i * 0.1,  # novelty increases
                None,
                None
            )
        )

        # Insert record
        record = {
            "schools": [{"depth_fm": 20 + i, "confidence": 0.8 + i * 0.02}],
            "bottom": {"depth_fm": 50 + i}
        }
        record_json = json.dumps(record)

        cur.execute(
            """
            INSERT INTO echogram_records (
                frame_id, ts_utc, depth_top_m, depth_bot_m,
                record_json, record_sha256, vocab_terms, model, confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                frame_id,
                ts_ms,
                20 + i,
                50 + i,
                record_json,
                "sha256_" + frame_id,
                "school, bottom",
                "test-model",
                0.8 + i * 0.02
            )
        )

    conn.commit()
    conn.close()


def start_test_server(workspace: Path) -> http.server.HTTPServer:
    """Start the test server in a background thread."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from scrubber.serve import ScrubberRequestHandler

    def handler(*args, **kwargs):
        return ScrubberRequestHandler(*args, workspace=workspace, **kwargs)

    server = http.server.HTTPServer((TEST_HOST, TEST_PORT), handler)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    # Give server time to start
    time.sleep(0.5)

    return server


class TestScrubberServer(unittest.TestCase):
    """Test suite for the scrubber HTTP server."""

    @classmethod
    def setUpClass(cls):
        """Set up test workspace and server."""
        cls.workspace = Path(tempfile.mkdtemp(prefix="scrubber_test_"))
        create_fixture_db(cls.workspace)
        cls.server = start_test_server(cls.workspace)
        cls.base_url = f"http://{TEST_HOST}:{TEST_PORT}"

    @classmethod
    def tearDownClass(cls):
        """Clean up test workspace and server."""
        cls.server.shutdown()
        import shutil
        shutil.rmtree(cls.workspace, ignore_errors=True)

    def test_api_day_returns_frames_and_records(self):
        """Test GET /api/day/<YYYY-MM-DD> returns 200 with frames and records."""
        url = f"{self.base_url}/api/day/2024-07-19"
        response = urllib.request.urlopen(url)

        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers.get_content_type(), "application/json")

        data = json.loads(response.read().decode())
        self.assertIn("frames", data)
        self.assertIn("records", data)
        self.assertEqual(len(data["frames"]), 5)
        self.assertEqual(len(data["records"]), 5)

        # Check frame structure
        frame = data["frames"][0]
        self.assertIn("frame_id", frame)
        self.assertIn("ts_utc", frame)
        self.assertIn("lat", frame)
        self.assertIn("lon", frame)
        self.assertIn("sha256", frame)
        self.assertIn("novelty", frame)

        # Check record structure
        record = data["records"][0]
        self.assertIn("frame_id", record)
        self.assertIn("record_json", record)
        self.assertIn("confidence", record)

    def test_api_day_invalid_date_returns_400(self):
        """Test GET /api/day/invalid returns 400."""
        url = f"{self.base_url}/api/day/invalid-date"
        try:
            urllib.request.urlopen(url)
            self.fail("Should have raised HTTPError")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)

    def test_api_day_missing_date_returns_404(self):
        """Test GET /api/day/2024-12-25 (no data) returns 404."""
        url = f"{self.base_url}/api/day/2024-12-25"
        try:
            urllib.request.urlopen(url)
            self.fail("Should have raised HTTPError")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)

    def test_api_blob_returns_png(self):
        """Test GET /api/blob/<sha256> returns image bytes with correct content-type."""
        # Get a frame SHA256 from the day API
        url = f"{self.base_url}/api/day/2024-07-19"
        response = urllib.request.urlopen(url)
        data = json.loads(response.read().decode())
        sha256 = data["frames"][0]["sha256"]

        # Fetch the blob
        blob_url = f"{self.base_url}/api/blob/{sha256}"
        response = urllib.request.urlopen(blob_url)

        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers.get_content_type(), "image/png")

        # Check we got PNG bytes
        blob_data = response.read()
        self.assertTrue(blob_data.startswith(b'\x89PNG'))

    def test_api_blob_invalid_sha256_returns_400(self):
        """Test GET /api/blob/invalid returns 400."""
        url = f"{self.base_url}/api/blob/too_short"
        try:
            urllib.request.urlopen(url)
            self.fail("Should have raised HTTPError")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)

    def test_api_blob_missing_returns_404(self):
        """Test GET /api/blob/00000000... returns 404."""
        url = f"{self.base_url}/api/blob/" + "0" * 64
        try:
            urllib.request.urlopen(url)
            self.fail("Should have raised HTTPError")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)

    def test_api_day_highlight_returns_max_novelty_frame(self):
        """Test GET /api/day/<date>/highlight returns max-novelty frame with caption."""
        url = f"{self.base_url}/api/day/2024-07-19/highlight"
        response = urllib.request.urlopen(url)

        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers.get_content_type(), "application/json")

        data = json.loads(response.read().decode())

        # Check structure
        self.assertIn("frame_id", data)
        self.assertIn("ts_utc", data)
        self.assertIn("sha256", data)
        self.assertIn("novelty", data)
        self.assertIn("caption", data)

        # Check it's the highest novelty frame (last one in our fixture)
        url = f"{self.base_url}/api/day/2024-07-19"
        response = urllib.request.urlopen(url)
        day_data = json.loads(response.read().decode())
        max_novelty_frame = max(day_data["frames"], key=lambda f: f.get("novelty") or 0)

        self.assertEqual(data["frame_id"], max_novelty_frame["frame_id"])

    def test_serve_index_html(self):
        """Test GET / returns index.html."""
        url = f"{self.base_url}/"
        response = urllib.request.urlopen(url)

        self.assertEqual(response.status, 200)
        self.assertIn("text/html", response.headers.get_content_type())

        content = response.read().decode()
        self.assertIn("TZPro Day Scrubber", content)

    def test_api_day_performance(self):
        """Test /api/day responds in <300ms (performance budget)."""
        url = f"{self.base_url}/api/day/2024-07-19"

        start = time.time()
        response = urllib.request.urlopen(url)
        elapsed = time.time() - start

        self.assertEqual(response.status, 200)
        self.assertLess(elapsed, 0.3, f"/api/day took {elapsed*1000:.0f}ms, budget is 300ms")


if __name__ == "__main__":
    unittest.main(verbosity=2)
