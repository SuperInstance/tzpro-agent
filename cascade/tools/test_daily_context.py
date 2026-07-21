"""cascade/tools/test_daily_context.py — unittest for daily_context.

Uses monkeypatched urlopen to avoid real network calls. Covers:
- Station selection (Ketchikan for 55.78,-131.70)
- Tide parsing (high/low events with times/heights)
- Offline path (URLError returns offline dict)
- Atomic write (temp+replace pattern)
"""
from __future__ import annotations

import io
import json
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock

from cascade.tools.daily_context import (
    _nearest_station,
    get_context,
    write_context,
)

# ── Mock responses ────────────────────────────────────────────────────────────
_MOCK_TIDE_RESPONSE = {
    "predictions": [
        {"t": "2026-07-20 04:32", "v": "14.5", "type": "H"},
        {"t": "2026-07-20 10:45", "v": "2.1", "type": "L"},
        {"t": "2026-07-20 17:18", "v": "15.2", "type": "H"},
        {"t": "2026-07-20 23:05", "v": "1.8", "type": "L"},
    ]
}

_MOCK_POINT_RESPONSE = {
    "properties": {
        "forecast": "https://api.weather.gov/gridpoints/AKZ200/42,73/forecast"
    }
}

_MOCK_FORECAST_RESPONSE = {
    "periods": [
        {
            "startTime": "2026-07-20T12:00:00-08:00",
            "windSpeed": "10 mph",
            "windDirection": "NW",
        },
        {
            "startTime": "2026-07-20T15:00:00-08:00",
            "windSpeed": "15 mph",
            "windDirection": "W",
        },
    ]
}


def _mock_urlopen_factory():
    """Return a mock function that returns proper mock response objects."""
    def _mock_urlopen(request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else str(request)

        if "tidesandcurrents.noaa.gov" in url:
            data = json.dumps(_MOCK_TIDE_RESPONSE).encode()
        elif "api.weather.gov/points" in url:
            data = json.dumps(_MOCK_POINT_RESPONSE).encode()
        elif "gridpoints" in url or "forecast" in url:
            data = json.dumps(_MOCK_FORECAST_RESPONSE).encode()
        else:
            raise urllib.error.URLError("mock: unknown URL")

        # Create a proper mock response object
        mock_resp = MagicMock()
        mock_resp.read = MagicMock(return_value=data)
        mock_resp.__enter__ = lambda self: self
        mock_resp.__exit__ = lambda self, *args: None
        return mock_resp

    return _mock_urlopen


class TestDailyContext(unittest.TestCase):
    def test_nearest_station_ketchikan(self):
        """Ketchikan (9450460) is nearest to 55.78,-131.70."""
        sid, data = _nearest_station(55.78, -131.70)
        self.assertEqual(sid, "9450460")
        self.assertEqual(data["name"], "Ketchikan")

    def test_nearest_station_juneau(self):
        """Juneau (9452210) is nearest to 58.3,-134.4."""
        sid, data = _nearest_station(58.3, -134.4)
        self.assertEqual(sid, "9452210")
        self.assertEqual(data["name"], "Juneau")

    @patch("urllib.request.urlopen", _mock_urlopen_factory())
    def test_get_context_tide_events(self):
        """Tide events parsed with type, time, height."""
        ctx = get_context(55.78, -131.70)
        self.assertFalse(ctx.get("offline"))
        self.assertIn("tide_events", ctx)
        events = ctx["tide_events"]
        self.assertEqual(len(events), 4)
        # First event should be high tide at 14.5 ft
        self.assertEqual(events[0]["type"], "high")
        self.assertEqual(events[0]["t"], "2026-07-20 04:32")
        self.assertEqual(events[0]["height_ft"], 14.5)
        # Second should be low tide at 2.1 ft
        self.assertEqual(events[1]["type"], "low")
        self.assertEqual(events[1]["height_ft"], 2.1)

    @patch("urllib.request.urlopen", _mock_urlopen_factory())
    def test_get_context_wind_forecast(self):
        """Wind forecast parsed with time, speed, direction."""
        ctx = get_context(55.78, -131.70)
        self.assertIn("wind_forecast", ctx)
        winds = ctx["wind_forecast"]
        self.assertGreater(len(winds), 0)
        # First wind: 10 mph ≈ 8.7 knots, NW
        self.assertEqual(winds[0]["speed_knots"], 8.7)
        self.assertEqual(winds[0]["direction"], "NW")

    @patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline"))
    def test_get_context_offline(self, mock_urlopen):
        """Network failure returns offline dict."""
        ctx = get_context(55.78, -131.70)
        self.assertTrue(ctx.get("offline"))
        self.assertIn("reason", ctx)
        self.assertEqual(ctx["reason"], "tide_api_failed")

    @patch("urllib.request.urlopen", _mock_urlopen_factory())
    def test_write_context_atomic(self):
        """Atomic write: temp file created, then renamed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            path = write_context(out_dir, 55.78, -131.70)

            # File exists
            self.assertTrue(path.exists())
            # In context/ subdirectory
            self.assertEqual(path.parent.name, "context")
            # Valid JSON
            data = json.loads(path.read_text())
            self.assertIn("tide_events", data)
            self.assertIn("wind_forecast", data)

    @patch("urllib.request.urlopen", _mock_urlopen_factory())
    def test_get_context_deterministic_keys(self):
        """Output has deterministic key order (sorted for consistency)."""
        ctx = get_context(55.78, -131.70)
        keys = list(ctx.keys())
        # Expected order: offline, tide_station, tide_events, wind_forecast, fetched_at
        self.assertEqual(keys, ["offline", "tide_station", "tide_events", "wind_forecast", "fetched_at"])

    @patch("urllib.request.urlopen", _mock_urlopen_factory())
    def test_get_context_station_included(self):
        """Result includes nearest station info."""
        ctx = get_context(55.78, -131.70)
        station = ctx["tide_station"]
        self.assertEqual(station["id"], "9450460")
        self.assertEqual(station["name"], "Ketchikan")
        self.assertIn("lat", station)
        self.assertIn("lon", station)

    @patch("urllib.request.urlopen", _mock_urlopen_factory())
    def test_get_context_fetched_at(self):
        """Result includes fetch timestamp."""
        ctx = get_context(55.78, -131.70)
        self.assertIn("fetched_at", ctx)
        # Parseable datetime
        time.strptime(ctx["fetched_at"], "%Y-%m-%d %H:%M:%SZ")


if __name__ == "__main__":
    unittest.main()
