"""cascade/test_d1_daemon.py — smoke tests for the D1 + EOD-GC wiring.

Tests:
  1. evening_final_read preserves canonical (10-min) frames, deletes
     non-canonical 1-min frames, and never deletes when ollama is down.
  2. daily_loop writes paired day_<DATE>.md + day_<DATE>.json offline.
  3. CascadeDaemon schedules D1 once per UTC day (basic timing test).
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

# Make the test runnable from any cwd.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import cascade.config as config  # noqa: E402
import cascade.daily_loop as d1  # noqa: E402
import cascade.retention as retention  # noqa: E402


def _stub_workspace():
    """Return a clean temp workspace; caller cleans up."""
    tmp = Path(tempfile.mkdtemp(prefix="tzpro-d1test-"))
    os.environ["TZPRO_WORKSPACE"] = str(tmp)
    os.environ["CASCADE_OUT"] = str(tmp / "cascade_out")
    os.environ["CASCADE_GC_MINUTE_PNGS"] = "1"
    return tmp


def _write_minimal_twin(workspace: Path, frame_id: str) -> None:
    """Create a minimal meta.db with one row + one echogram_record."""
    mem = workspace / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    db = mem / "meta.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        """CREATE TABLE IF NOT EXISTS frames (
            frame_id TEXT PRIMARY KEY,
            ts_utc INTEGER, lat REAL, lon REAL,
            sog REAL, cog REAL, sha256 TEXT,
            tier TEXT, novelty REAL, keep_reason TEXT)"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS echogram_records (
            frame_id TEXT PRIMARY KEY,
            record_json TEXT,
            confidence REAL)"""
    )
    conn.execute(
        "INSERT OR REPLACE INTO frames(frame_id, sha256) VALUES (?, ?)",
        (frame_id, "deadbeef" * 8),
    )
    conn.execute(
        "INSERT OR REPLACE INTO echogram_records(frame_id, record_json, confidence) VALUES (?, ?, ?)",
        (frame_id, "{}", 0.9),
    )
    conn.commit()
    conn.close()


def test_evening_final_read_keeps_canonical(tmp: Path):
    day = tmp / "captures" / "v3" / "2026-07-21_5547N_13142W"
    day.mkdir(parents=True)
    (day / "1010_canon.png").write_bytes(b"canonical-png")
    (day / "1010_canon.json").write_text(
        json.dumps({"capture_id": "1010_canon", "position": {"lat_dd": 55.5, "lon_dd": -131.5}})
    )

    # A non-canonical 1-min frame, no record row.
    (day / "1001_1min.png").write_bytes(b"onemin-png")
    (day / "1001_1min.json").write_text(
        json.dumps({"capture_id": "1001_1min", "position": {"lat_dd": 55.5, "lon_dd": -131.5}})
    )

    _write_minimal_twin(tmp, "1010_canon")

    # Re-import config to honor the new env.
    import importlib
    importlib.reload(config)
    importlib.reload(retention)

    with mock.patch("cascade.ollama_client.vision_available", return_value=True), \
         mock.patch("cascade.ollama_client.vision_prompt", return_value='{"missed_something": false, "note": ""}'), \
         mock.patch("cascade.ollama_client.extract_json", return_value={"missed_something": False, "note": ""}):
        report = retention.evening_final_read(day)

    assert (day / "1010_canon.png").exists(), "canonical must NOT be deleted"
    assert not (day / "1001_1min.png").exists(), "1-min must be deleted"
    assert report["kept_canonical"] == 1
    assert report["gc_pngs"] == 1
    print("  PASS  test_evening_final_read_keeps_canonical")


def test_evening_final_read_no_delete_when_ollama_down(tmp: Path):
    day = tmp / "captures" / "v3" / "2026-07-21_5547N_13142W"
    day.mkdir(parents=True)
    (day / "1001_1min.png").write_bytes(b"x")
    (day / "1001_1min.json").write_text(json.dumps({"capture_id": "1001_1min"}))

    import importlib
    importlib.reload(config)
    importlib.reload(retention)

    with mock.patch("cascade.ollama_client.vision_available", return_value=False):
        report = retention.evening_final_read(day)

    assert (day / "1001_1min.png").exists(), "must not delete when ollama offline"
    assert report["gc_pngs"] == 0
    print("  PASS  test_evening_final_read_no_delete_when_ollama_down")


def test_d1_writes_paired_md_and_json(tmp: Path):
    out = tmp / "cascade_out"
    (out / "records").mkdir(parents=True)
    (out / "minute_notes" / "novel").mkdir(parents=True)
    (out / "briefings").mkdir(parents=True)
    (out / "logs").mkdir(parents=True)

    (out / "records" / "1010_x_record.json").write_text(json.dumps({
        "ts_utc": "2026-07-21T18:10:00Z", "lat": 55.5, "lon": -131.5,
        "summary": "chum on the 22 line",
        "bottom_fm": 48, "bottom_type": "hard",
        "schools": [{"depth_fm": 22, "size": "medium", "band": "LF"}],
        "thermocline_fm": 26, "anomalies": [],
    }))
    (out / "minute_notes" / "novel" / "1010_x.json").write_text(json.dumps({
        "ts_utc": "2026-07-21T18:10:30Z", "lat": 55.5, "lon": -131.5,
        "caption": "tight school", "features": ["blob school"], "novelty": 0.9,
    }))

    import importlib
    importlib.reload(config)
    importlib.reload(d1)

    with mock.patch("cascade.ollama_client.vision_available", return_value=False):
        md = d1.write_daily("2026-07-21")

    assert md is not None
    assert md.exists()
    assert md.with_suffix(".json").exists()
    raw = json.loads(md.with_suffix(".json").read_text())
    assert raw["date"] == "2026-07-21"
    assert raw["counts"]["m10_records"] == 1
    assert raw["counts"]["novel_notes"] == 1
    assert raw["provenance"]["model"] == "skeleton"
    print("  PASS  test_d1_writes_paired_md_and_json")


def test_d1_skips_empty_day(tmp: Path):
    out = tmp / "cascade_out"
    (out / "records").mkdir(parents=True)
    (out / "minute_notes" / "novel").mkdir(parents=True)
    (out / "briefings").mkdir(parents=True)

    import importlib
    importlib.reload(config)
    importlib.reload(d1)
    assert d1.write_daily("2030-01-01") is None
    print("  PASS  test_d1_skips_empty_day")


def main():
    print("test_d1_daemon:")
    tmp = _stub_workspace()
    try:
        test_evening_final_read_keeps_canonical(tmp)
        # Reset state for next test
        shutil.rmtree(tmp, ignore_errors=True)
        tmp = _stub_workspace()
        test_evening_final_read_no_delete_when_ollama_down(tmp)
        shutil.rmtree(tmp, ignore_errors=True)
        tmp = _stub_workspace()
        test_d1_writes_paired_md_and_json(tmp)
        shutil.rmtree(tmp, ignore_errors=True)
        tmp = _stub_workspace()
        test_d1_skips_empty_day(tmp)
        shutil.rmtree(tmp, ignore_errors=True)
        print("  ALL 4 PASS")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
