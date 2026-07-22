"""companion/test_bridge.py — unit tests for the cascade → ship-log-search bridge.

Run from the companion/ directory:
    cd companion
    python -m unittest test_bridge.py -v

Or from the repo root:
    python -m unittest companion.test_bridge -v
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Allow running from companion/ or repo root
import sys
HERE = Path(__file__).parent.resolve()
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import bridge  # noqa: E402


class TestCategoryDerivation(unittest.TestCase):

    def test_catch_keywords(self):
        text = "First set of the season, 250 lbs sockeye on a 400 fm soak."
        self.assertEqual(bridge.derive_category(text), "catch")

    def test_weather_keywords(self):
        text = "Strong north wind, 25 kt gusts, building seas all afternoon."
        self.assertEqual(bridge.derive_category(text), "weather")

    def test_navigation_keywords(self):
        text = "Set course 270 deg, drifted 1.2 nm on the tide."
        self.assertEqual(bridge.derive_category(text), "navigation")

    def test_maintenance_keywords(self):
        text = "Replaced hydraulic hose on port drum, topped off engine oil."
        self.assertEqual(bridge.derive_category(text), "maintenance")

    def test_fallback_to_observation(self):
        self.assertEqual(bridge.derive_category("Just a calm day on the water."), "observation")

    def test_empty_text(self):
        self.assertEqual(bridge.derive_category(""), "observation")

    def test_catch_count_keyword(self):
        # Numeric "32 fish" should still trigger catch
        self.assertEqual(bridge.derive_category("32 fish in the box today"), "catch")


class TestBuildId(unittest.TestCase):

    def test_h1_id_format(self):
        self.assertEqual(
            bridge.build_id("_briefing_20260722T010000.json", "h1"),
            "tzpro-h1-_briefing_20260722T010000",
        )

    def test_d1_id_format(self):
        self.assertEqual(
            bridge.build_id("day_2026-07-21.json", "d1"),
            "tzpro-d1-day_2026-07-21",
        )

    def test_stable_across_calls(self):
        # Same input → same id (idempotency check)
        a = bridge.build_id("_briefing_X.json", "h1")
        b = bridge.build_id("_briefing_X.json", "h1")
        self.assertEqual(a, b)


class TestTruncate(unittest.TestCase):

    def test_short_text_unchanged(self):
        self.assertEqual(bridge.truncate("hello", 4000), "hello")

    def test_long_text_truncated(self):
        text = "x" * 5000
        result = bridge.truncate(text, 100)
        self.assertEqual(len(result), 100)
        self.assertTrue(result.endswith("."))

    def test_empty_text(self):
        self.assertEqual(bridge.truncate(""), "")


class TestH1ToLogEntry(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = Path(self.tmpdir) / "_briefing_20260722T010000.json"
        with open(self.path, "w") as f:
            json.dump({
                "summary": "Good morning chumming at Cape Edgecumbe. 250 lbs sockeye.",
                "tide": {"high_utc": "2026-07-22T13:00Z"},
                "weather": {"wind_kt": 12},
                "retention_stats": {"m1_kept": 5, "m10_records": 2},
                "ts_utc": "2026-07-22T01:00:00Z",
            }, f)

    def test_returns_required_fields(self):
        entry = bridge.h1_to_log_entry(self.path)
        self.assertIsNotNone(entry)
        self.assertIn("id", entry)
        self.assertIn("text", entry)
        self.assertIn("category", entry)
        self.assertIn("timestamp", entry)
        self.assertIn("metadata", entry)

    def test_id_is_stable(self):
        entry = bridge.h1_to_log_entry(self.path)
        self.assertEqual(entry["id"], "tzpro-h1-_briefing_20260722T010000")

    def test_category_derived_from_text(self):
        entry = bridge.h1_to_log_entry(self.path)
        self.assertEqual(entry["category"], "catch")  # "sockeye", "lbs"

    def test_skips_empty_summary(self):
        empty_path = Path(self.tmpdir) / "_briefing_empty.json"
        with open(empty_path, "w") as f:
            json.dump({"summary": "", "ts_utc": "2026-07-22T01:00:00Z"}, f)
        self.assertIsNone(bridge.h1_to_log_entry(empty_path))


class TestD1ToLogEntry(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = Path(self.tmpdir) / "day_2026-07-21.json"
        with open(self.path, "w") as f:
            json.dump({
                "date": "2026-07-21",
                "summary": "Solid day. 850 lbs across 6 sets.",
                "key_events": [
                    {"narrative": "First set at slack tide, 200 lbs sockeye.", "timestamp": "2026-07-21T05:00:00Z"},
                    {"narrative": "Engine oil topped off, no issues.", "timestamp": "2026-07-21T11:30:00Z"},
                ],
                "anomalies": [
                    {"description": "Briefly saw whales near the set.", "timestamp": "2026-07-21T07:00:00Z"},
                ],
                "hotspots": [],
            }, f)

    def test_returns_list(self):
        result = bridge.d1_to_log_entry(self.path)
        self.assertIsInstance(result, list)
        # 1 summary + 2 events + 1 anomaly = 4 entries
        self.assertEqual(len(result), 4)

    def test_summary_entry_exists(self):
        entries = bridge.d1_to_log_entry(self.path)
        summary_entry = next(e for e in entries if "d1-summary" in e["id"])
        self.assertIn("850 lbs", summary_entry["text"])
        self.assertEqual(summary_entry["category"], "catch")

    def test_event_entries_have_per_event_categories(self):
        entries = bridge.d1_to_log_entry(self.path)
        catch_event = next(e for e in entries if "d1-event" in e["id"] and "sockeye" in e["text"].lower())
        # Use case-insensitive match — text from LLM may capitalize arbitrarily
        maint_event = next(e for e in entries if "d1-event" in e["id"] and "engine" in e["text"].lower())
        self.assertEqual(catch_event["category"], "catch")
        self.assertEqual(maint_event["category"], "maintenance")

    def test_anomaly_uses_observation_category(self):
        entries = bridge.d1_to_log_entry(self.path)
        anomaly = next(e for e in entries if "d1-anomaly" in e["id"])
        self.assertEqual(anomaly["category"], "observation")
        self.assertEqual(anomaly["metadata"]["severity"], "unknown")

    def test_empty_day_returns_empty_list(self):
        empty_path = Path(self.tmpdir) / "day_2026-07-22.json"
        with open(empty_path, "w") as f:
            json.dump({"date": "2026-07-22", "summary": "", "key_events": [], "anomalies": []}, f)
        self.assertEqual(bridge.d1_to_log_entry(empty_path), [])


class TestPostEntry(unittest.TestCase):

    def setUp(self):
        self.entry = {
            "id": "tzpro-h1-test",
            "text": "Test briefing text",
            "category": "observation",
            "timestamp": "2026-07-22T01:00:00Z",
            "lat": 56.8,
            "lon": -135.5,
            "location_name": "Test Ground",
            "metadata": {"kind": "h1_briefing"},
        }

    @patch("bridge.requests.post")
    def test_successful_post(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200, text='{"ingested":1}')
        ok = bridge.post_entry(self.entry, "http://localhost:8787", "secret", 5)
        self.assertTrue(ok)
        self.assertEqual(mock_post.call_count, 1)
        # Verify URL
        called_url = mock_post.call_args[0][0]
        self.assertEqual(called_url, "http://localhost:8787/api/ingest")
        # Verify auth header
        headers = mock_post.call_args[1]["headers"]
        self.assertEqual(headers["X-Log-Key"], "secret")

    @patch("bridge.requests.post")
    def test_4xx_returns_false_no_retry(self, mock_post):
        mock_post.return_value = MagicMock(status_code=400, text='{"error":"bad"}')
        ok = bridge.post_entry(self.entry, "http://localhost:8787", "", 5)
        self.assertFalse(ok)
        self.assertEqual(mock_post.call_count, 1)

    @patch("bridge.requests.post")
    def test_5xx_returns_false_for_retry(self, mock_post):
        mock_post.return_value = MagicMock(status_code=503, text='{"error":"down"}')
        ok = bridge.post_entry(self.entry, "http://localhost:8787", "", 5)
        self.assertFalse(ok)

    @patch("bridge.requests.post")
    def test_network_error_returns_false(self, mock_post):
        import requests
        mock_post.side_effect = requests.ConnectionError("connection refused")
        ok = bridge.post_entry(self.entry, "http://localhost:8787", "", 5)
        self.assertFalse(ok)


class TestIdempotency(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # Create one valid H1 file
        self.briefings_dir = Path(self.tmpdir)
        path = self.briefings_dir / "_briefing_20260722T010000.json"
        with open(path, "w") as f:
            json.dump({
                "summary": "Test briefing, 100 lbs sockeye.",
                "ts_utc": "2026-07-22T01:00:00Z",
            }, f)

    @patch("bridge.post_entry")
    def test_already_sent_skips(self, mock_post):
        mock_post.return_value = True
        # Pre-populate sent_ids
        sent_ids = {"tzpro-h1-_briefing_20260722T010000"}
        cfg = {
            "companion_url": "http://localhost:8787",
            "companion_key": "",
            "cascade_briefings": str(self.briefings_dir),
            "poll_interval_s": 30,
            "timeout_s": 5,
        }
        bridge.run_once(cfg, sent_ids)
        mock_post.assert_not_called()

    @patch("bridge.post_entry")
    def test_new_file_gets_sent(self, mock_post):
        mock_post.return_value = True
        sent_ids = set()
        cfg = {
            "companion_url": "http://localhost:8787",
            "companion_key": "",
            "cascade_briefings": str(self.briefings_dir),
            "poll_interval_s": 30,
            "timeout_s": 5,
        }
        new_sent = bridge.run_once(cfg, sent_ids)
        self.assertEqual(mock_post.call_count, 1)
        self.assertIn("tzpro-h1-_briefing_20260722T010000", new_sent)

    @patch("bridge.post_entry")
    def test_failed_post_not_marked_sent(self, mock_post):
        mock_post.return_value = False  # 5xx — should retry next cycle
        sent_ids = set()
        cfg = {
            "companion_url": "http://localhost:8787",
            "companion_key": "",
            "cascade_briefings": str(self.briefings_dir),
            "poll_interval_s": 30,
            "timeout_s": 5,
        }
        new_sent = bridge.run_once(cfg, sent_ids)
        self.assertEqual(len(new_sent), 0)  # not marked as sent
        # Second cycle should retry
        mock_post.return_value = True
        new_sent2 = bridge.run_once(cfg, new_sent)
        self.assertEqual(mock_post.call_count, 2)
        self.assertIn("tzpro-h1-_briefing_20260722T010000", new_sent2)


class TestPathToLogEntry(unittest.TestCase):

    def test_h1_json_recognized(self):
        path = Path("/tmp/_briefing_20260722T010000.json")
        self.assertIsNotNone(bridge.H1_RE.match(path.name))

    def test_d1_json_recognized(self):
        path = Path("/tmp/day_2026-07-21.json")
        self.assertIsNotNone(bridge.D1_RE.match(path.name))

    def test_md_files_ignored(self):
        path = Path("/tmp/_briefing_20260722T010000.md")
        self.assertIsNone(bridge.path_to_log_entry(path))

    def test_unrelated_files_ignored(self):
        self.assertIsNone(bridge.path_to_log_entry(Path("/tmp/random.json")))


if __name__ == "__main__":
    unittest.main(verbosity=2)