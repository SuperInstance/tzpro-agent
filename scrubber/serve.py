"""
scrubber/serve.py

Local HTTP server for the day scrubber MVP.
Serves frames, records, and blobs from the twin database.

stdlib-only: http.server, sqlite3, json, pathlib, urllib.parse
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

# Default workspace path
DEFAULT_WORKSPACE = Path(r"C:\Users\casey\.openclaw\workspace\tzpro-agent")
STATIC_DIR = Path(__file__).parent / "static"


def parse_day_date(day_str: str) -> tuple[int, int]:
    """
    Parse YYYY-MM-DD to start/end epoch ms.
    """
    dt = datetime.strptime(day_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    start_ms = int(dt.timestamp() * 1000)
    end_ms = int((dt.replace(hour=23, minute=59, second=59, microsecond=999999).timestamp() * 1000))
    return start_ms, end_ms


def format_ts_ms(ts_ms: int) -> str:
    """Format epoch ms to HH:MM:SS."""
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    return dt.strftime("%H:%M:%S")


def format_lat_lon(lat: Optional[float], lon: Optional[float]) -> str:
    """Format lat/lon to DDM° format (e.g., 55°47.6′N)."""
    if lat is None or lon is None:
        return "-- --"

    lat_dir = "N" if lat >= 0 else "S"
    lon_dir = "E" if lon >= 0 else "W"

    lat_abs = abs(lat)
    lon_abs = abs(lon)

    lat_deg = int(lat_abs)
    lon_deg = int(lon_abs)

    lat_min = (lat_abs - lat_deg) * 60
    lon_min = (lon_abs - lon_deg) * 60

    return f"{lat_deg:02d}°{lat_min:04.1f}′{lat_dir} {lon_deg:03d}°{lon_min:04.1f}′{lon_dir}"


def get_db_path(workspace: Path) -> Path:
    """Get path to meta.db."""
    db_path = workspace / "memory" / "meta.db"
    if not db_path.exists():
        return None
    return db_path


def get_blob_path(workspace: Path, sha256: str) -> Optional[Path]:
    """Get path to blob by SHA256."""
    blob_dir = workspace / "memory" / "blobs"
    blob_path = blob_dir / sha256[:2] / sha256[2:4] / f"{sha256}.png"
    if blob_path.exists():
        return blob_path
    return None


def query_day_data(db_path: Path, start_ms: int, end_ms: int) -> dict[str, Any]:
    """
    Query frames and records for a day.
    Returns {frames: [...], records: [...]}.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Query frames
    frames = cur.execute(
        """
        SELECT frame_id, ts_utc, lat, lon, sog, cog, sha256, tier, novelty, keep_reason
        FROM frames
        WHERE ts_utc >= ? AND ts_utc <= ?
        ORDER BY ts_utc
        """,
        (start_ms, end_ms)
    ).fetchall()

    # Query records and join to frames
    records = cur.execute(
        """
        SELECT er.frame_id, er.record_json, er.confidence,
               f.ts_utc, f.lat, f.lon
        FROM echogram_records er
        JOIN frames f ON er.frame_id = f.frame_id
        WHERE f.ts_utc >= ? AND f.ts_utc <= ?
        ORDER BY f.ts_utc
        """,
        (start_ms, end_ms)
    ).fetchall()

    conn.close()

    return {
        "frames": [dict(f) for f in frames],
        "records": [dict(r) for r in records]
    }


def query_highlight(db_path: Path, start_ms: int, end_ms: int) -> Optional[dict[str, Any]]:
    """
    Query the day's highlight with a graceful fallback chain:
      1. max-novelframe from notes (M1 novelty lives in the notes table)
      2. latest frame with a confident record
      3. latest frame of the day
    Degrade, don't 404 (docs/17 constraint 5).
    Caption uses calibrated language — never raw model confidence
    percentages (docs/23 R1: raw scores banned from captain surfaces).
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Notes branch only if the table exists (minimal fixture DBs may lack it)
    has_notes = cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='notes'"
    ).fetchone()

    highlight = None
    if has_notes:
        # 1. Max-novelty NOTE of the day → its frame (novelty lives in
        # notes, not frames, for imported captures)
        highlight = cur.execute(
            """
            SELECT f.frame_id, f.ts_utc, f.lat, f.lon, f.sog, f.cog, f.sha256,
                   n.novelty AS novelty, er.record_json
            FROM notes n
            JOIN frames f ON n.frame_id = f.frame_id
            LEFT JOIN echogram_records er ON f.frame_id = er.frame_id
            WHERE f.ts_utc >= ? AND f.ts_utc <= ? AND n.novelty IS NOT NULL
            ORDER BY n.novelty DESC
            LIMIT 1
            """,
            (start_ms, end_ms)
        ).fetchone()

    # 2a. Highest frames.novelty (when populated, e.g. fixtures)
    if not highlight:
        highlight = cur.execute(
            """
            SELECT f.frame_id, f.ts_utc, f.lat, f.lon, f.sog, f.cog, f.sha256,
                   f.novelty AS novelty, er.record_json
            FROM frames f
            LEFT JOIN echogram_records er ON f.frame_id = er.frame_id
            WHERE f.ts_utc >= ? AND f.ts_utc <= ? AND f.novelty IS NOT NULL
            ORDER BY f.novelty DESC
            LIMIT 1
            """,
            (start_ms, end_ms)
        ).fetchone()

    # 2. Latest frame with a record
    if not highlight:
        highlight = cur.execute(
            """
            SELECT f.frame_id, f.ts_utc, f.lat, f.lon, f.sog, f.cog, f.sha256,
                   NULL AS novelty, er.record_json
            FROM frames f
            JOIN echogram_records er ON f.frame_id = er.frame_id
            WHERE f.ts_utc >= ? AND f.ts_utc <= ?
            ORDER BY f.ts_utc DESC
            LIMIT 1
            """,
            (start_ms, end_ms)
        ).fetchone()

    # 3. Latest frame of the day
    if not highlight:
        highlight = cur.execute(
            """
            SELECT frame_id, ts_utc, lat, lon, sog, cog, sha256,
                   NULL AS novelty, NULL AS record_json
            FROM frames
            WHERE ts_utc >= ? AND ts_utc <= ?
            ORDER BY ts_utc DESC
            LIMIT 1
            """,
            (start_ms, end_ms)
        ).fetchone()

    conn.close()

    if not highlight:
        return None

    # Build caption from record_json if available — calibrated language
    # only, NO raw confidence percentages (docs/23 R1).
    caption = "busiest water of the day"
    if highlight["record_json"]:
        try:
            record = json.loads(highlight["record_json"])
            parts = []
            schools = record.get("schools", [])
            if schools:
                depths = ", ".join(str(s.get("depth_fm", "?")) for s in schools[:2])
                parts.append(f"school at {depths} fm")
            bottom_fm = record.get("bottom_fm") or (record.get("bottom") or {}).get("depth_fm")
            bottom_type = record.get("bottom_type")
            if bottom_fm:
                parts.append(f"bottom {bottom_type + ' ' if bottom_type and bottom_type != 'unknown' else ''}at {bottom_fm} fm")
            if parts:
                caption = ", ".join(parts)
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
            pass

    return {
        "frame_id": highlight["frame_id"],
        "ts_utc": highlight["ts_utc"],
        "lat": highlight["lat"],
        "lon": highlight["lon"],
        "sha256": highlight["sha256"],
        "novelty": highlight["novelty"],
        "caption": caption
    }


def query_briefings(db_path: Path, limit: int = 200) -> list[dict[str, Any]]:
    """
    Query all briefings from the twin briefings table, newest first.

    Returns a list of dicts: briefing_id, ts_utc, period_start,
    period_end, model, body. Degrades to [] if the table is missing
    (minimal fixture DBs may lack it).
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    has_briefings = cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='briefings'"
    ).fetchone()
    if not has_briefings:
        conn.close()
        return []

    rows = cur.execute(
        """
        SELECT briefing_id, ts_utc, period_start, period_end, model, body
        FROM briefings
        ORDER BY ts_utc DESC
        LIMIT ?
        """,
        (limit,)
    ).fetchall()

    conn.close()
    return [dict(r) for r in rows]


class ScrubberRequestHandler(SimpleHTTPRequestHandler):
    """HTTP request handler for the day scrubber."""

    def address_string(self):
        # BaseHTTPRequestHandler does a reverse-DNS lookup per request for
        # logging — on Windows/off-network hosts that costs ~2s PER REQUEST.
        # Never do name resolution on a boat.
        return self.client_address[0]

    def __init__(self, *args, workspace: Path = DEFAULT_WORKSPACE, **kwargs):
        self.workspace = workspace
        self.db_path = get_db_path(workspace)
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self):
        """Route GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        # Static files (including /)
        if path == "/" or path.startswith("/static/"):
            self.serve_static(path)
            return

        # Briefings page (single-file HTML)
        if path == "/briefings":
            self.serve_static("/briefings.html")
            return

        # API: day data
        if path.startswith("/api/day/"):
            self.handle_day_api(path)
            return

        # API: blob
        if path.startswith("/api/blob/"):
            self.handle_blob_api(path)
            return

        # API: briefings list
        if path == "/api/briefings":
            self.handle_briefings_api()
            return

        # 404
        self.send_error(404, "Not found")

    def serve_static(self, path: str):
        """Serve static files."""
        if path == "/":
            path = "/index.html"

        file_path = STATIC_DIR / path.lstrip("/")
        if not file_path.exists():
            self.send_error(404, "Not found")
            return

        self.send_response(200)
        content_type = self.guess_type(str(file_path))
        if content_type:
            self.send_header("Content-type", content_type)
        self.end_headers()

        with open(file_path, "rb") as f:
            self.wfile.write(f.read())

    def handle_day_api(self, path: str):
        """Handle /api/day/<date> and /api/day/<date>/highlight."""
        parts = path.rstrip("/").split("/")
        if len(parts) < 4:
            self.send_error(400, "Invalid path")
            return

        if self.db_path is None:
            self.send_json_error(500, "Database not found")
            return

        day_str = parts[3]
        try:
            start_ms, end_ms = parse_day_date(day_str)
        except ValueError:
            self.send_json_error(400, "Invalid date format, use YYYY-MM-DD")
            return

        # /api/day/<date>/highlight
        if len(parts) >= 5 and parts[4] == "highlight":
            highlight = query_highlight(self.db_path, start_ms, end_ms)
            if highlight is None:
                self.send_json_error(404, "No highlight found for this day")
                return
            self.send_json(highlight)
            return

        # /api/day/<date>
        data = query_day_data(self.db_path, start_ms, end_ms)
        if not data["frames"] and not data["records"]:
            self.send_json_error(404, "No data found for this date")
            return
        self.send_json(data)

    def handle_blob_api(self, path: str):
        """Handle /api/blob/<sha256>."""
        sha256 = path.split("/")[-1]
        if len(sha256) != 64:
            self.send_json_error(400, "Invalid SHA256")
            return

        blob_path = get_blob_path(self.workspace, sha256)
        if blob_path is None or not blob_path.exists():
            self.send_json_error(404, "Blob not found")
            return

        self.send_response(200)
        self.send_header("Content-type", "image/png")
        self.send_header("Content-length", str(blob_path.stat().st_size))
        self.end_headers()

        with open(blob_path, "rb") as f:
            self.wfile.write(f.read())

    def send_json(self, data: Any):
        """Send JSON response."""
        body = json.dumps(data, separators=(",", ":"))
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.send_header("Content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body.encode())

    def handle_briefings_api(self):
        """Handle GET /api/briefings → JSON list, newest first."""
        if self.db_path is None:
            self.send_json_error(500, "Database not found")
            return
        briefings = query_briefings(self.db_path)
        self.send_json({"briefings": briefings})

    def send_json_error(self, code: int, message: str):
        """Send JSON error response."""
        body = json.dumps({"error": message})
        self.send_response(code)
        self.send_header("Content-type", "application/json")
        self.send_header("Content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, format: str, *args):
        """Suppress default logging."""
        pass


def run_server(
    host: str = "127.0.0.1",
    port: int = 8080,
    workspace: Optional[Path] = None
):
    """Run the scrubber HTTP server."""
    if workspace is None:
        workspace = DEFAULT_WORKSPACE

    workspace = Path(workspace)
    db_path = get_db_path(workspace)

    if db_path is None:
        print(f"Warning: Database not found at {workspace / 'memory' / 'meta.db'}")
    else:
        print(f"Serving from workspace: {workspace}")

    # Handler factory with workspace bound
    def handler_factory(*args, **kwargs):
        return ScrubberRequestHandler(*args, workspace=workspace, **kwargs)

    server = HTTPServer((host, port), handler_factory)
    print(f"Scrubber server running at http://{host}:{port}")
    print(f"Press Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Day scrubber HTTP server for tzpro-agent"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port to bind to (default: 8080)"
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=DEFAULT_WORKSPACE,
        help="Path to workspace directory"
    )

    args = parser.parse_args()
    run_server(args.host, args.port, args.workspace)


if __name__ == "__main__":
    main()
