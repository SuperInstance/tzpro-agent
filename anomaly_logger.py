#!/usr/bin/env python3
"""
anomaly_logger.py — Phase 3: Bathymetric Anomaly Logger

Compares real sounder readings against charted contours, logs discrepancies,
and exports correction data for map updates.

Table: bathymetry_anomalies
    ts         TEXT    — ISO timestamp
    lat        REAL    — decimal degrees
    lon        REAL    — decimal degrees
    sog        REAL    — speed over ground (knots)
    sounder_fm REAL    — what the sounder actually read (fathoms)
    contour_fm REAL    — what the contour says should be there (fathoms)
    delta_fm   REAL    — anomaly magnitude (positive = sounder deeper)
    source     TEXT    — 'capture' or 'manual'
    cruise     TEXT    — cruise/trip identifier (optional)

Exports:
    qgis_corrections.csv — lat, lon, corrected_depth (negative meters)
"""

from __future__ import annotations

import csv
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Paths ──────────────────────────────────────────────────────────
WORKSPACE = Path(__file__).parent.resolve()
BATHY_DIR = WORKSPACE / "bathymetry"
DB_PATH = BATHY_DIR / "anomalies.db"
CSV_EXPORT = BATHY_DIR / "qgis_corrections.csv"

# ── Schema ──────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS bathymetry_anomalies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    lat         REAL NOT NULL,
    lon         REAL NOT NULL,
    sog         REAL,
    sounder_fm  REAL NOT NULL,
    contour_fm  REAL,
    delta_fm    REAL,
    source      TEXT DEFAULT 'capture',
    cruise      TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_anomalies_latlon ON bathymetry_anomalies(lat, lon);
CREATE INDEX IF NOT EXISTS idx_anomalies_ts ON bathymetry_anomalies(ts);
CREATE INDEX IF NOT EXISTS idx_anomalies_delta ON bathymetry_anomalies(delta_fm);
"""


def get_db() -> sqlite3.Connection:
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def log_anomaly(
    lat: float,
    lon: float,
    sounder_fm: float,
    contour_fm: Optional[float] = None,
    sog: Optional[float] = None,
    source: str = "capture",
    cruise: Optional[str] = None,
) -> dict:
    """Log a single anomaly observation to the database.

    Returns the inserted row as a dict.
    """
    delta_fm = sounder_fm - contour_fm if contour_fm is not None else None
    ts = datetime.now(timezone.utc).isoformat()

    db = get_db()
    try:
        cur = db.execute(
            """INSERT INTO bathymetry_anomalies
               (ts, lat, lon, sog, sounder_fm, contour_fm, delta_fm, source, cruise)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ts, lat, lon, sog, sounder_fm, contour_fm, delta_fm, source, cruise),
        )
        db.commit()
        row_id = cur.lastrowid
        return {
            "id": row_id,
            "ts": ts,
            "lat": lat,
            "lon": lon,
            "sounder_fm": sounder_fm,
            "contour_fm": contour_fm,
            "delta_fm": delta_fm,
            "source": source,
        } | ({"sog": sog} if sog is not None else {})
    finally:
        db.close()


def export_qgis(min_delta_fm: float = 1.0) -> int:
    """Export anomalies above threshold as QGIS-ready CSV.

    CSV format: Longitude, Latitude, Depth (negative meters, as QGIS expects).
    Only exports rows where |delta_fm| >= min_delta_fm and contour_fm is known.

    Returns number of rows exported.
    """
    db = get_db()
    try:
        rows = db.execute(
            """SELECT lon, lat, sounder_fm, delta_fm
               FROM bathymetry_anomalies
               WHERE contour_fm IS NOT NULL
                 AND abs(delta_fm) >= ?
               ORDER BY ts DESC""",
            (min_delta_fm,),
        ).fetchall()

        with open(CSV_EXPORT, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Longitude", "Latitude", "Depth"])
            for r in rows:
                # QGIS convention: depth in negative meters
                depth_m = -(r["sounder_fm"] * 1.8288)
                writer.writerow([r["lon"], r["lat"], round(depth_m, 2)])

        return len(rows)
    finally:
        db.close()


def export_json(min_delta_fm: float = 1.0) -> str:
    """Export anomalies as a compact GeoJSON FeatureCollection for the ZeroClaw."""
    db = get_db()
    try:
        rows = db.execute(
            """SELECT ts, lat, lon, sounder_fm, contour_fm, delta_fm, sog, source
               FROM bathymetry_anomalies
               WHERE contour_fm IS NOT NULL
                 AND abs(delta_fm) >= ?
               ORDER BY ts DESC""",
            (min_delta_fm,),
        ).fetchall()

        features = []
        for r in rows:
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [r["lon"], r["lat"]],
                },
                "properties": {
                    "ts": r["ts"],
                    "sounder_fm": r["sounder_fm"],
                    "contour_fm": r["contour_fm"],
                    "delta_fm": round(r["delta_fm"], 2),
                    "sog": r["sog"],
                    "source": r["source"],
                },
            })

        fc = {
            "type": "FeatureCollection",
            "features": features,
        }

        out_path = BATHY_DIR / "anomalies.geojson"
        with open(out_path, "w") as f:
            json.dump(fc, f, indent=2)

        return str(out_path)
    finally:
        db.close()


def stats() -> dict:
    """Quick summary of the anomaly database."""
    db = get_db()
    try:
        total = db.execute("SELECT count(*) FROM bathymetry_anomalies").fetchone()[0]

        if total == 0:
            return {"total": 0}

        recent_10 = db.execute(
            """SELECT lat, lon, delta_fm, abs(delta_fm) as mag
               FROM bathymetry_anomalies
               ORDER BY ts DESC LIMIT 10"""
        ).fetchall()

        summary = db.execute(
            """SELECT
                   min(delta_fm) as max_negative,
                   max(delta_fm) as max_positive,
                   avg(abs(delta_fm)) as avg_magnitude
               FROM bathymetry_anomalies
               WHERE delta_fm IS NOT NULL"""
        ).fetchone()

        by_source = db.execute(
            """SELECT source, count(*) as cnt
               FROM bathymetry_anomalies GROUP BY source"""
        ).fetchall()

        return {
            "total": total,
            "largest_negative_fm": round(summary[0], 2) if summary[0] else None,
            "largest_positive_fm": round(summary[1], 2) if summary[1] else None,
            "avg_magnitude_fm": round(summary[2], 2) if summary[2] else None,
            "by_source": {r["source"]: r["cnt"] for r in by_source},
            "recent": [
                {
                    "lat": r["lat"],
                    "lon": r["lon"],
                    "delta_fm": round(r["delta_fm"], 2),
                }
                for r in recent_10
            ],
        }
    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Bathymetric Anomaly Logger")
    parser.add_argument("--log", nargs=5, metavar=("lat", "lon", "sounder_fm", "contour_fm", "sog"),
                        help="Log a single anomaly: lat lon sounder_fm contour_fm sog")
    parser.add_argument("--export-csv", action="store_true",
                        help="Export to QGIS CSV")
    parser.add_argument("--export-geojson", action="store_true",
                        help="Export to GeoJSON for ZeroClaw")
    parser.add_argument("--min-delta", type=float, default=1.0,
                        help="Minimum |delta| in fathoms to include in export (default: 1.0)")
    parser.add_argument("--stats", action="store_true",
                        help="Show database statistics")

    args = parser.parse_args()

    if args.log:
        lat, lon, sf, cf, sog = args.log
        result = log_anomaly(
            lat=float(lat),
            lon=float(lon),
            sounder_fm=float(sf),
            contour_fm=float(cf) if cf.lower() != "none" else None,
            sog=float(sog) if sog.lower() != "none" else None,
        )
        print(f"[anomaly] logged id={result['id']} "
              f"({result['lat']:.4f}, {result['lon']:.4f}) "
              f"delta={result['delta_fm']}fm")

    if args.export_csv:
        n = export_qgis(min_delta_fm=args.min_delta)
        print(f"[export] {n} rows -> {CSV_EXPORT}")

    if args.export_geojson:
        p = export_json(min_delta_fm=args.min_delta)
        print(f"[export] GeoJSON -> {p}")

    if args.stats:
        s = stats()
        if s["total"]:
            print(f"[stats] {s}")
        else:
            print("[stats] database is empty")

    if not any([args.log, args.export_csv, args.export_geojson, args.stats]):
        parser.print_help()
