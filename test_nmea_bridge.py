#!/usr/bin/env python3
"""test_nmea_bridge.py — Unit tests for the parser/state machine.

We don't need hardware to verify correctness — we test the pure-Python
parser by feeding synthetic sentences and checking the resulting
VesselState.

Run with:
    python -m pytest test_nmea_bridge.py -v
or:
    python test_nmea_bridge.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from nmea_bridge import VesselState, parse_sentence, _verify_checksum  # noqa: E402


def _checksum(body: str) -> str:
    """Compute NMEA0183 XOR checksum."""
    xor = 0
    for ch in body:
        xor ^= ord(ch)
    return f"*{xor:02X}"


def _wrap(talker: str, kind: str, fields: list[str]) -> str:
    body = f"{talker}{kind}," + ",".join(fields)
    # Many fields must end with empty trailing fields to look right;
    # we just append the checksum.
    return "$" + body + _checksum(body)


class TestChecksum(unittest.TestCase):
    def test_correct_checksum(self):
        # Real GGA sentence (no checksum in input)
        s = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
        self.assertTrue(_verify_checksum(s))

    def test_bad_checksum_rejected(self):
        s = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*FF"
        self.assertFalse(_verify_checksum(s))

    def test_missing_checksum_accepted(self):
        # Some sources omit the checksum
        s = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,"
        self.assertTrue(_verify_checksum(s))


class TestGGA(unittest.TestCase):
    def test_full_gga(self):
        s = _wrap("GP", "GGA", [
            "123519", "4807.038", "N", "01131.000", "E",
            "1", "08", "0.9", "545.4", "M", "46.9", "M", "", "",
        ])
        st = VesselState()
        self.assertEqual(parse_sentence(s, st), "GGA")
        # 48°07.038' N = 48.11730° N
        self.assertAlmostEqual(st.lat, 48.11730, places=4)
        # 011°31.000' E = 11.51667° E
        self.assertAlmostEqual(st.lon, 11.51667, places=4)
        self.assertEqual(st.fix_quality, 1)
        self.assertEqual(st.satellites, 8)
        self.assertAlmostEqual(st.hdop, 0.9, places=2)
        self.assertAlmostEqual(st.altitude_m, 545.4, places=1)

    def test_gga_southern_hemisphere(self):
        s = _wrap("GP", "GGA", [
            "120000", "3322.123", "S", "07028.456", "W",
            "1", "06", "1.5", "10.0", "M", "0.0", "M", "", "",
        ])
        st = VesselState()
        parse_sentence(s, st)
        self.assertLess(st.lat, 0)     # negative = South
        self.assertLess(st.lon, 0)     # negative = West
        self.assertAlmostEqual(st.lat, -(33 + 22.123/60), places=4)
        self.assertAlmostEqual(st.lon, -(70 + 28.456/60), places=4)

    def test_alaska_coordinates(self):
        # Sitka, AK: 57.0431° N, 135.3270° W
        s = _wrap("GP", "GGA", [
            "090000", "5702.586", "N", "13519.620", "W",
            "1", "10", "0.8", "5.0", "M", "0.0", "M", "", "",
        ])
        st = VesselState()
        parse_sentence(s, st)
        self.assertAlmostEqual(st.lat, 57.04310, places=4)
        self.assertAlmostEqual(st.lon, -135.32700, places=4)


class TestRMC(unittest.TestCase):
    def test_full_rmc(self):
        s = _wrap("GP", "RMC", [
            "123519", "A", "4807.038", "N", "01131.000", "E",
            "022.4", "084.4", "230394", "003.1", "W", "A",
        ])
        st = VesselState()
        self.assertEqual(parse_sentence(s, st), "RMC")
        self.assertAlmostEqual(st.lat, 48.11730, places=4)
        self.assertAlmostEqual(st.lon, 11.51667, places=4)
        self.assertAlmostEqual(st.sog_kts, 22.4, places=1)
        self.assertAlmostEqual(st.cog_deg, 84.4, places=1)
        self.assertAlmostEqual(st.mag_variation, -3.1, places=1)
        # The RMC timestamp_utc helper _stamp_utc_from_rmc is called but
        # then we overwrite timestamp_utc with "now" at the end of
        # parse_sentence; we just verify the field is populated.
        self.assertIsNotNone(st.timestamp_utc)

    def test_easterly_variation(self):
        s = _wrap("GP", "RMC", [
            "120000", "A", "4807.038", "N", "01131.000", "E",
            "005.0", "180.0", "010126", "012.5", "E", "A",
        ])
        st = VesselState()
        parse_sentence(s, st)
        self.assertGreater(st.mag_variation, 0)
        self.assertAlmostEqual(st.mag_variation, 12.5, places=1)


class TestHeading(unittest.TestCase):
    def test_hdt_true(self):
        s = _wrap("HC", "HDT", ["123.4", "T"])
        st = VesselState()
        self.assertEqual(parse_sentence(s, st), "HDT")
        self.assertAlmostEqual(st.heading_true_deg, 123.4, places=1)

    def test_hdt_wraparound(self):
        s = _wrap("HC", "HDT", ["372.5", "T"])
        st = VesselState()
        parse_sentence(s, st)
        self.assertAlmostEqual(st.heading_true_deg, 12.5, places=1)

    def test_hdg_with_deviation(self):
        # heading mag = 90, dev = 2 W → true = 88
        s = _wrap("HC", "HDG", ["90.0", "", "2.0", "W", "", ""])
        st = VesselState()
        self.assertEqual(parse_sentence(s, st), "HDG")
        self.assertAlmostEqual(st.heading_mag_deg, 90.0, places=1)
        self.assertAlmostEqual(st.heading_true_deg, 88.0, places=1)

    def test_vhw(self):
        s = _wrap("VW", "VHW", ["", "", "95.0", "M", "6.5", "N", "180.0", "T"])
        st = VesselState()
        parse_sentence(s, st)
        # VHW with empty T but present M → only mag
        self.assertAlmostEqual(st.heading_mag_deg, 95.0, places=1)


class TestDepth(unittest.TestCase):
    def test_dbt_full(self):
        # 30 ft, 9.1 m, 5 fm
        s = _wrap("SD", "DBT", ["30.0", "f", "9.1", "M", "5.0", "F", "", ""])
        st = VesselState()
        self.assertEqual(parse_sentence(s, st), "DBT")
        self.assertAlmostEqual(st.depth_ft, 30.0, places=1)
        self.assertAlmostEqual(st.depth_m, 9.1, places=1)
        self.assertAlmostEqual(st.depth_fm, 5.0, places=1)

    def test_dpt_computes_all_units(self):
        s = _wrap("SD", "DPT", ["15.0", "0.0", "100.0", ""])
        st = VesselState()
        parse_sentence(s, st)
        self.assertAlmostEqual(st.depth_m, 15.0, places=1)
        self.assertAlmostEqual(st.depth_fm, 15.0 * 0.546807, places=3)
        self.assertAlmostEqual(st.depth_ft, 15.0 / 0.3048, places=1)


class TestMotionClassification(unittest.TestCase):
    def test_docked(self):
        st = VesselState()
        st.sog_kts = 0.0
        self.assertEqual(st.classify_motion(), "docked")
        st.sog_kts = 0.3
        self.assertEqual(st.classify_motion(), "docked")

    def test_trolling(self):
        st = VesselState()
        st.sog_kts = 1.5
        self.assertEqual(st.classify_motion(), "trolling")
        st.sog_kts = 2.2
        self.assertEqual(st.classify_motion(), "trolling")

    def test_cruising(self):
        st = VesselState()
        st.sog_kts = 9.0
        self.assertEqual(st.classify_motion(), "cruising")

    def test_unknown(self):
        st = VesselState()
        self.assertEqual(st.classify_motion(), "unknown")


class TestIsFresh(unittest.TestCase):
    def test_fresh_after_update(self):
        from datetime import datetime, timezone
        st = VesselState()
        st.timestamp_utc = datetime.now(timezone.utc).isoformat()
        self.assertTrue(st.is_fresh(max_age_s=2.0))

    def test_stale(self):
        from datetime import datetime, timezone, timedelta
        st = VesselState()
        st.timestamp_utc = (datetime.now(timezone.utc) - timedelta(seconds=20)).isoformat()
        self.assertFalse(st.is_fresh(max_age_s=10.0))

    def test_never_updated(self):
        st = VesselState()
        self.assertFalse(st.is_fresh())


class TestEndToEnd(unittest.TestCase):
    """Simulate a full minute of NMEA traffic from a vessel underway."""

    def test_realistic_sequence(self):
        st = VesselState()

        sentences = [
            _wrap("GP", "GGA", ["090000", "5702.586", "N", "13519.620", "W",
                                "1", "10", "0.8", "5.0", "M", "0.0", "M", "", ""]),
            _wrap("GP", "RMC", ["090000", "A", "5702.586", "N", "13519.620", "W",
                                "006.2", "180.0", "170126", "015.0", "E", "A"]),
            _wrap("HC", "HDT", ["178.5", "T"]),
            _wrap("SD", "DBT", ["240.0", "f", "73.2", "M", "40.0", "F", "", ""]),
            _wrap("GP", "GGA", ["090010", "5702.700", "N", "13519.620", "W",
                                "1", "11", "0.7", "5.0", "M", "0.0", "M", "", ""]),
            _wrap("GP", "RMC", ["090010", "A", "5702.700", "N", "13519.620", "W",
                                "006.3", "181.0", "170126", "015.0", "E", "A"]),
            _wrap("HC", "HDT", ["179.0", "T"]),
        ]

        for s in sentences:
            parse_sentence(s, st)

        # After the sequence:
        self.assertAlmostEqual(st.lat, 57 + 2.7/60, places=4)
        self.assertAlmostEqual(st.lon, -(135 + 19.62/60), places=4)
        self.assertEqual(st.satellites, 11)
        self.assertAlmostEqual(st.sog_kts, 6.3, places=1)
        self.assertAlmostEqual(st.cog_deg, 181.0, places=1)
        self.assertAlmostEqual(st.heading_true_deg, 179.0, places=1)
        self.assertAlmostEqual(st.depth_fm, 40.0, places=1)
        self.assertEqual(st.state_class, "slow_cruise")  # 6.3 kts
        self.assertGreaterEqual(st.sentence_count, 7)


if __name__ == "__main__":
    unittest.main(verbosity=2)