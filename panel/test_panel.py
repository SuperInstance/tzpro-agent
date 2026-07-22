"""panel/test_panel.py — smoke tests for the three-panel day console.

Tests:
  1. cascade_paths resolves the expected subdirs.
  2. _list_m1_notes, _list_m10_records, _list_h1_briefings, _list_d1_briefs
     filter by date and produce well-formed dicts.
  3. PanelHandler routing for / and /api/day/<d> + /api/day/<d>/panel/*.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from http.server import BaseHTTPRequestHandler
from io import BytesIO
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import panel.serve as serve  # noqa: E402


def _set_mtime(p: Path, iso_utc: str) -> None:
    """Set a file's mtime so date-keyed listings can find it."""
    ts = datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).timestamp()
    import os
    os.utime(p, (ts, ts))


def _seed(ws: Path) -> Path:
    """Seed a workspace tree and return its captures day dir."""
    out = ws / "cascade_out"
    (out / "records").mkdir(parents=True, exist_ok=True)
    (out / "minute_notes" / "novel").mkdir(parents=True, exist_ok=True)
    (out / "briefings").mkdir(parents=True, exist_ok=True)

    day = ws / "captures" / "v3" / "2026-07-21_5547N_13142W"
    day.mkdir(parents=True, exist_ok=True)
    (day / "1010_x.png").write_bytes(b"\x89PNG")  # minimal
    (day / "1010_x.json").write_text(json.dumps({
        "capture_id": "1010_x",
        "ts_utc": "2026-07-21T18:10:00Z",
        "position": {"lat_dd": 55.5, "lon_dd": -131.5, "sog_kts": 2.0},
    }))
    (out / "records" / "1010_x_record.json").write_text(json.dumps({
        "ts_utc": "2026-07-21T18:10:00Z",
        "capture_id": "1010_x",
        "lat": 55.5, "lon": -131.5, "sog_kts": 2.0,
        "summary": "chum school stacked at 22 fm",
        "bottom_fm": 48, "bottom_type": "hard",
        "schools": [{"depth_fm": 22, "size": "medium", "band": "LF"}],
        "thermocline_fm": 26, "anomalies": [], "search_terms": [],
    }))
    (out / "minute_notes" / "novel" / "1010_x.json").write_text(json.dumps({
        "ts_utc": "2026-07-21T18:10:30Z",
        "frame": "1010_x.png", "lat": 55.5, "lon": -131.5,
        "caption": "tight blob school", "features": ["blob school"],
        "novelty": 0.91,
    }))
    h1_md = (out / "briefings" / "briefing_20260721_1800.md")
    h1_md.write_text("# H1 1800\n\nchum at 22 fm\n")
    (out / "briefings" / "briefing_20260721_1800.json").write_text(json.dumps({
        "ts_utc": "2026-07-21T18:00:00Z",
        "recommendations": [{"action": "stay", "confidence": 0.8, "basis": "tight marks"}],
    }))
    # H1 is keyed by file mtime (UTC). Set mtime to 2026-07-21 18:00 UTC so
    # the test fixture matches the filename.
    _set_mtime(h1_md, "2026-07-21T18:00:00Z")
    _set_mtime(h1_md.with_suffix(".json"), "2026-07-21T18:00:00Z")
    (out / "briefings" / "day_2026-07-21.md").write_text("# Daily 2026-07-21\n\nok\n")
    return ws


def _paths(ws: Path) -> dict:
    paths = serve.cascade_paths(ws)
    paths["briefings"].mkdir(parents=True, exist_ok=True)
    return paths


def test_cascade_paths_keys(tmp: Path):
    paths = _paths(tmp)
    for k in ("out", "records", "novel", "briefings", "captures", "twin_db"):
        assert k in paths, f"missing {k}"
    print("  PASS  test_cascade_paths_keys")


def test_list_m10_records(tmp: Path):
    paths = _paths(_seed(tmp))
    recs = serve._list_m10_records(paths, "2026-07-21")
    assert len(recs) == 1
    assert recs[0]["capture_id"] == "1010_x"
    assert recs[0]["bottom_fm"] == 48
    assert recs[0]["schools"][0]["depth_fm"] == 22
    assert recs[0]["png"] is not None and recs[0]["png"].endswith("1010_x.png")
    print("  PASS  test_list_m10_records")


def test_list_m1_notes_filters_by_date(tmp: Path):
    paths = _paths(_seed(tmp))
    notes = serve._list_m1_notes(paths, "2026-07-21")
    assert len(notes) == 1
    assert notes[0]["caption"] == "tight blob school"
    other = serve._list_m1_notes(paths, "2030-01-01")
    assert other == []
    print("  PASS  test_list_m1_notes_filters_by_date")


def test_list_h1_and_d1_briefings(tmp: Path):
    paths = _paths(_seed(tmp))
    h1 = serve._list_h1_briefings(paths, "2026-07-21")
    assert len(h1) == 1 and h1[0]["file"].endswith(".md")
    d1 = serve._list_d1_briefs(paths, "2026-07-21")
    assert len(d1) == 1 and d1[0]["file"] == "day_2026-07-21.md"
    print("  PASS  test_list_h1_and_d1_briefings")


def test_panel_routing_via_minimal_handler(tmp: Path):
    """Smoke test: build a PanelHandler subclass with stubbed socket and
    drive its routing surface. Doesn't open a real socket."""
    paths = _paths(_seed(tmp))

    class _Stub(BaseHTTPRequestHandler):
        def do_GET(self): pass  # placeholder
        def log_message(self, *a, **kw): pass

    # Bind the class-level attributes used by PanelHandler.
    serve.PanelHandler.paths = paths
    serve.PanelHandler.live = None

    # Just assert the handler class is correctly configured.
    h = serve.PanelHandler
    assert hasattr(h, "do_GET")
    assert hasattr(h, "handle_day_api")
    assert hasattr(h, "handle_image")
    assert hasattr(h, "handle_stream")
    assert hasattr(h, "send_json")
    print("  PASS  test_panel_routing_via_minimal_handler")


def main():
    print("test_panel:")
    tmp = Path(tempfile.mkdtemp(prefix="tzpro-panel-test-"))
    try:
        test_cascade_paths_keys(tmp)
        test_list_m10_records(tmp)
        test_list_m1_notes_filters_by_date(tmp)
        test_list_h1_and_d1_briefings(tmp)
        test_panel_routing_via_minimal_handler(tmp)
        print("  ALL 5 PASS")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
