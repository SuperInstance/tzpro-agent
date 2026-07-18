#!/usr/bin/env python3
"""db.py — Local SQLite mirror for the tzpro-agent capture pipeline.

Mirrors structured analysis data from JSON captures to SQLite for fast
offline queries. The JSON files remain the source of truth; this is
a read-optimized mirror only.

Schema:
  - captures: Core capture metadata + heuristic analysis summary
  - catch_labels: Supervised catch reports (from Captain's logs)
  - blobs: Individual echo returns from LF/HF bands

All sync functions are idempotent (INSERT OR REPLACE / ON CONFLICT).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Config ─────────────────────────────────────────────────────────
WORKSPACE = Path(__file__).parent.resolve()
DB_PATH = WORKSPACE / "captures.db"
CAPTURES_V3_DIR = WORKSPACE / "captures" / "v3"

BATCH_SIZE = 100

# Match analyzer.py logging format
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("db")


# ══════════════════════════════════════════════════════════════════════
#  Schema & Connection
# ══════════════════════════════════════════════════════════════════════

SCHEMA_SQL = """
-- Core captures table
CREATE TABLE IF NOT EXISTS captures (
    capture_id TEXT PRIMARY KEY,
    ts_utc TEXT NOT NULL,
    ts_local TEXT,
    lat REAL,
    lon REAL,
    sog_kts REAL,
    cog_deg REAL,
    depth_max_fm INTEGER DEFAULT 60,
    schema_version INTEGER DEFAULT 2,
    mid_zone_mean REAL,
    mid_zone_peak INTEGER,
    blob_count INTEGER,
    thermocline_count INTEGER,
    bottom_depth_fm REAL,
    bottom_confidence TEXT,
    caption TEXT,
    day_folder TEXT,
    analyzed_at TEXT,
    file_size_bytes INTEGER
);

-- Catch labels (supervised learning data)
CREATE TABLE IF NOT EXISTS catch_labels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id TEXT NOT NULL REFERENCES captures(capture_id),
    species TEXT NOT NULL,
    depth_fm INTEGER,
    count INTEGER,
    raw_text TEXT,
    confidence REAL,
    linked_at_utc TEXT,
    UNIQUE(capture_id, species, depth_fm)
);

-- Individual blob detections
CREATE TABLE IF NOT EXISTS blobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id TEXT NOT NULL REFERENCES captures(capture_id),
    band TEXT NOT NULL CHECK(band IN ('lf', 'hf')),
    centroid_depth_fm REAL,
    centroid_x_px INTEGER,
    centroid_y_px INTEGER,
    width_px INTEGER,
    height_px INTEGER,
    area_px INTEGER,
    mean_intensity REAL,
    aspect_ratio REAL,
    predicted_species TEXT,
    prediction_confidence REAL
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_captures_ts ON captures(ts_utc);
CREATE INDEX IF NOT EXISTS idx_captures_pos ON captures(lat, lon);
CREATE INDEX IF NOT EXISTS idx_catches_species ON catch_labels(species);
CREATE INDEX IF NOT EXISTS idx_blobs_capture ON blobs(capture_id);
CREATE INDEX IF NOT EXISTS idx_blobs_depth ON blobs(centroid_depth_fm);
"""


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Create a SQLite connection with WAL mode and reasonable defaults."""
    path = db_path or DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    # WAL mode for better concurrent access
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA mmap_size=268435456")  # 256MB
    return conn


@contextmanager
def db_connection(db_path: Optional[Path] = None):
    """Context manager for database connections."""
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Create/connect to database and run CREATE TABLE IF NOT EXISTS.

    Returns the connection (caller must close or use context manager).
    """
    conn = get_connection(db_path)
    conn.executescript(SCHEMA_SQL)
    log.info("Database initialized at %s", db_path or DB_PATH)
    return conn


# ══════════════════════════════════════════════════════════════════════
#  JSON → SQLite Extraction Helpers
# ══════════════════════════════════════════════════════════════════════

def _safe_get(d: dict, *keys, default=None):
    """Safely navigate nested dict with multiple keys."""
    for k in keys:
        if isinstance(d, dict) and k in d:
            d = d[k]
        else:
            return default
    return d


def extract_capture_row(meta: dict, json_path: Path) -> dict:
    """Extract captures table row from capture JSON metadata."""
    analysis = meta.get("analysis", {})
    heuristic = analysis.get("heuristic", {}) or {}
    lf = heuristic.get("lf", {}) or {}
    hf = heuristic.get("hf", {}) or {}

    mid_zone = lf.get("zone_profiles", {}).get("mid", {})
    bottom = lf.get("bottom") or hf.get("bottom")

    ts_utc = meta.get("ts_utc") or datetime.now(timezone.utc).isoformat()

    return {
        "capture_id": meta.get("capture_id"),
        "ts_utc": ts_utc,
        "ts_local": meta.get("ts_local"),
        "lat": _safe_get(meta, "position", "lat_dd"),
        "lon": _safe_get(meta, "position", "lon_dd"),
        "sog_kts": _safe_get(meta, "position", "sog_kts"),
        "cog_deg": _safe_get(meta, "position", "cog_deg"),
        "depth_max_fm": _safe_get(meta, "display", "depth_max_fm", default=60),
        "schema_version": analysis.get("schema_version", 2),
        "mid_zone_mean": mid_zone.get("mean_intensity"),
        "mid_zone_peak": mid_zone.get("peak_intensity"),
        "blob_count": lf.get("blob_count"),
        "thermocline_count": lf.get("thermocline_count"),
        "bottom_depth_fm": bottom.get("bottom_depth_fm") if bottom else None,
        "bottom_confidence": bottom.get("confidence") if bottom else None,
        "caption": analysis.get("caption"),
        "day_folder": json_path.parent.name,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "file_size_bytes": json_path.stat().st_size if json_path.exists() else None,
    }


def extract_blob_rows(meta: dict) -> list[dict]:
    """Extract blob rows from LF and HF heuristic data."""
    analysis = meta.get("analysis", {})
    heuristic = analysis.get("heuristic", {}) or {}
    rows = []

    for band in ("lf", "hf"):
        band_data = heuristic.get(band, {}) or {}
        blobs = band_data.get("blobs", []) or []

        for blob in blobs:
            pred = blob.get("prediction") or {}
            rows.append({
                "capture_id": meta.get("capture_id"),
                "band": band,
                "centroid_depth_fm": blob.get("centroid_depth_fm"),
                "centroid_x_px": blob.get("centroid_x_px"),
                "centroid_y_px": blob.get("centroid_y_px"),
                "width_px": blob.get("width_px"),
                "height_px": blob.get("height_px"),
                "area_px": blob.get("area_px"),
                "mean_intensity": blob.get("mean_intensity"),
                "aspect_ratio": blob.get("aspect_ratio"),
                "predicted_species": pred.get("species"),
                "prediction_confidence": pred.get("confidence"),
            })

    return rows


def extract_catch_label_rows(meta: dict) -> list[dict]:
    """Extract catch_labels rows from analysis.vocabulary."""
    analysis = meta.get("analysis", {})
    vocab = analysis.get("vocabulary", []) or []

    rows = []
    for label in vocab:
        if not label.get("species"):
            continue
        rows.append({
            "capture_id": meta.get("capture_id"),
            "species": label.get("species"),
            "depth_fm": label.get("depth_fm"),
            "count": label.get("count"),
            "raw_text": label.get("raw_text"),
            "confidence": label.get("confidence"),
            "linked_at_utc": label.get("linked_at_utc"),
        })

    return rows


# ══════════════════════════════════════════════════════════════════════
#  Sync Functions
# ══════════════════════════════════════════════════════════════════════

CAPTURE_INSERT_SQL = """
    INSERT OR REPLACE INTO captures (
        capture_id, ts_utc, ts_local, lat, lon, sog_kts, cog_deg,
        depth_max_fm, schema_version, mid_zone_mean, mid_zone_peak,
        blob_count, thermocline_count, bottom_depth_fm, bottom_confidence,
        caption, day_folder, analyzed_at, file_size_bytes
    ) VALUES (
        :capture_id, :ts_utc, :ts_local, :lat, :lon, :sog_kts, :cog_deg,
        :depth_max_fm, :schema_version, :mid_zone_mean, :mid_zone_peak,
        :blob_count, :thermocline_count, :bottom_depth_fm, :bottom_confidence,
        :caption, :day_folder, :analyzed_at, :file_size_bytes
    )
"""

BLOB_INSERT_SQL = """
    INSERT INTO blobs (
        capture_id, band, centroid_depth_fm, centroid_x_px, centroid_y_px,
        width_px, height_px, area_px, mean_intensity, aspect_ratio,
        predicted_species, prediction_confidence
    ) VALUES (
        :capture_id, :band, :centroid_depth_fm, :centroid_x_px, :centroid_y_px,
        :width_px, :height_px, :area_px, :mean_intensity, :aspect_ratio,
        :predicted_species, :prediction_confidence
    )
"""

CATCH_LABEL_INSERT_SQL = """
    INSERT OR REPLACE INTO catch_labels (
        capture_id, species, depth_fm, count, raw_text, confidence, linked_at_utc
    ) VALUES (
        :capture_id, :species, :depth_fm, :count, :raw_text, :confidence, :linked_at_utc
    )
"""


def sync_capture(capture_json_path: str | Path, conn: sqlite3.Connection) -> bool:
    """Read a capture JSON and upsert into all three tables.

    Returns True on success, False on failure.
    """
    path = Path(capture_json_path)
    if not path.exists():
        log.warning("JSON not found: %s", path)
        return False

    try:
        with open(path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Cannot read %s: %s", path.name, e)
        return False

    capture_id = meta.get("capture_id")
    if not capture_id:
        log.warning("Missing capture_id in %s", path.name)
        return False

    try:
        # Delete existing blobs for this capture (will re-insert)
        conn.execute("DELETE FROM blobs WHERE capture_id = ?", (capture_id,))

        # Upsert capture row
        cap_row = extract_capture_row(meta, path)
        conn.execute(CAPTURE_INSERT_SQL, cap_row)

        # Insert blobs
        blob_rows = extract_blob_rows(meta)
        if blob_rows:
            conn.executemany(BLOB_INSERT_SQL, blob_rows)

        # Upsert catch labels
        label_rows = extract_catch_label_rows(meta)
        if label_rows:
            conn.executemany(CATCH_LABEL_INSERT_SQL, label_rows)

        log.info("Synced: %s (blobs=%d, labels=%d)", capture_id, len(blob_rows), len(label_rows))
        return True

    except sqlite3.Error as e:
        log.error("DB error syncing %s: %s", capture_id, e)
        return False


def _find_all_capture_jsons() -> list[Path]:
    """Return all .json files under captures/v3/ recursively."""
    if not CAPTURES_V3_DIR.exists():
        return []

    files = []
    for day_dir in sorted(CAPTURES_V3_DIR.iterdir()):
        if not day_dir.is_dir():
            continue
        for js_file in sorted(day_dir.glob("*.json")):
            files.append(js_file)
    return files


def _needs_sync(meta: dict, json_path: Path, conn: sqlite3.Connection) -> bool:
    """Check if a capture needs syncing (new or changed)."""
    capture_id = meta.get("capture_id")
    if not capture_id:
        return False

    # Check if exists and compare schema_version + file size
    cur = conn.execute(
        "SELECT schema_version, file_size_bytes FROM captures WHERE capture_id = ?",
        (capture_id,),
    )
    row = cur.fetchone()

    file_size = json_path.stat().st_size
    schema_version = meta.get("analysis", {}).get("schema_version", 2)

    if row is None:
        return True  # New capture

    # Force resync if schema_version bumped or file changed
    if row["schema_version"] != schema_version:
        return True
    if row["file_size_bytes"] != file_size:
        return True

    return False


def sync_all(conn: Optional[sqlite3.Connection] = None, force: bool = False) -> int:
    """Scan captures/v3/ for all JSON files and sync each.

    Returns count of synced captures.
    """
    json_files = _find_all_capture_jsons()
    if not json_files:
        log.info("No capture JSONs found")
        return 0

    log.info("Found %d capture JSONs to check", len(json_files))

    synced = 0
    owns_conn = conn is None

    try:
        if owns_conn:
            conn = get_connection()

        for i, js_file in enumerate(json_files):
            try:
                with open(js_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                log.warning("Cannot read %s: %s", js_file.name, e)
                continue

            if force or _needs_sync(meta, js_file, conn):
                if sync_capture(js_file, conn):
                    synced += 1

            # Periodic commit for large batches
            if (i + 1) % BATCH_SIZE == 0:
                conn.commit()
                log.debug("Progress: %d/%d", i + 1, len(json_files))

        conn.commit()
        log.info("Sync complete: %d/%d captures synced", synced, len(json_files))
        return synced

    finally:
        if owns_conn and conn:
            conn.close()


def sync_one_then_alerts(capture_id: str, conn: Optional[sqlite3.Connection] = None) -> bool:
    """Sync a single capture by ID, then trigger alert checker (placeholder).

    The alert checker will be built later; for now this just syncs.
    """
    # Find the JSON file
    json_files = _find_all_capture_jsons()
    target = None
    for js_file in json_files:
        if js_file.stem == capture_id:
            target = js_file
            break

    if not target:
        log.warning("Capture ID not found: %s", capture_id)
        return False

    owns_conn = conn is None
    try:
        if owns_conn:
            conn = get_connection()

        result = sync_capture(target, conn)
        if result:
            conn.commit()
            # TODO: call alert checker here when implemented
            # check_alerts(capture_id, conn)
            log.info("Synced and alerted: %s", capture_id)

        return result
    finally:
        if owns_conn and conn:
            conn.close()


# ══════════════════════════════════════════════════════════════════════
#  Query Functions
# ══════════════════════════════════════════════════════════════════════

def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    """Convert sqlite3.Row objects to plain dicts."""
    return [dict(r) for r in rows]


def query_recent(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    """Return most recent captures ordered by ts_utc desc."""
    cur = conn.execute(
        "SELECT * FROM captures ORDER BY ts_utc DESC LIMIT ?",
        (limit,),
    )
    return _rows_to_dicts(cur.fetchall())


def query_catches(
    conn: sqlite3.Connection,
    species: Optional[str] = None,
) -> list[dict]:
    """Return catch labels, optionally filtered by species."""
    if species:
        cur = conn.execute(
            "SELECT * FROM catch_labels WHERE species = ? ORDER BY linked_at_utc DESC",
            (species,),
        )
    else:
        cur = conn.execute(
            "SELECT * FROM catch_labels ORDER BY linked_at_utc DESC",
        )
    return _rows_to_dicts(cur.fetchall())


def query_blobs_at_depth(
    conn: sqlite3.Connection,
    depth_fm: float,
    band: str = 'lf',
    tolerance: float = 5.0,
) -> list[dict]:
    """Return blobs within depth ± tolerance, filtered by band.

    Used by real-time alerts.
    """
    min_depth = depth_fm - tolerance
    max_depth = depth_fm + tolerance

    cur = conn.execute(
        """SELECT * FROM blobs
           WHERE band = ? AND centroid_depth_fm BETWEEN ? AND ?
           ORDER BY centroid_depth_fm""",
        (band, min_depth, max_depth),
    )
    return _rows_to_dicts(cur.fetchall())


def query_daily_captures(conn: sqlite3.Connection, date_str: str) -> list[dict]:
    """Return captures for a given date in YYYY-MM-DD format."""
    cur = conn.execute(
        """SELECT * FROM captures
           WHERE date(ts_utc) = ?
           ORDER BY ts_utc""",
        (date_str,),
    )
    return _rows_to_dicts(cur.fetchall())


def query_captures_by_position(
    conn: sqlite3.Connection,
    lat: float,
    lon: float,
    radius_nm: float = 1.0,
) -> list[dict]:
    """Return captures within radius_nm nautical miles of a position.

    Rough approximation: 1 degree lat = 60 nm, 1 degree lon = 60 * cos(lat) nm.
    """
    lat_delta = radius_nm / 60.0
    lon_delta = radius_nm / (60.0 * max(0.1, abs(__import__("math").cos(__import__("math").radians(lat)))))

    cur = conn.execute(
        """SELECT * FROM captures
           WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
           ORDER BY ts_utc DESC""",
        (lat - lat_delta, lat + lat_delta, lon - lon_delta, lon + lon_delta),
    )
    return _rows_to_dicts(cur.fetchall())


def get_stats(conn: sqlite3.Connection) -> dict:
    """Return database statistics."""
    stats = {}
    cur = conn.execute("SELECT COUNT(*) AS c FROM captures")
    stats["captures"] = cur.fetchone()["c"]

    cur = conn.execute("SELECT COUNT(*) AS c FROM catch_labels")
    stats["catch_labels"] = cur.fetchone()["c"]

    cur = conn.execute("SELECT COUNT(*) AS c FROM blobs")
    stats["blobs"] = cur.fetchone()["c"]

    cur = conn.execute("SELECT MIN(ts_utc), MAX(ts_utc) FROM captures")
    row = cur.fetchone()
    stats["date_range"] = [row[0], row[1]] if row[0] else None

    cur = conn.execute("SELECT species, COUNT(*) AS c FROM catch_labels GROUP BY species ORDER BY c DESC")
    stats["catch_by_species"] = _rows_to_dicts(cur.fetchall())

    cur = conn.execute("SELECT band, COUNT(*) AS c FROM blobs GROUP BY band")
    stats["blobs_by_band"] = _rows_to_dicts(cur.fetchall())

    return stats


def close(conn: sqlite3.Connection) -> None:
    """Close a database connection."""
    if conn:
        conn.close()
        log.debug("Database connection closed")


# ══════════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════════

def cli() -> None:
    """CLI entry point for ad-hoc queries and maintenance."""
    import sys

    args = sys.argv[1:]

    if not args or "-h" in args or "--help" in args:
        print("Usage:")
        print("  python db.py init                    # Initialize database")
        print("  python db.py sync [--force]          # Sync all captures")
        print("  python db.py sync-one <capture_id>   # Sync single capture + alerts")
        print("  python db.py recent [N]              # Show N most recent captures")
        print("  python db.py catches [species]       # Show catch labels")
        print("  python db.py blobs <depth> [band] [tolerance]")
        print("  python db.py daily YYYY-MM-DD        # Show captures for a date")
        print("  python db.py stats                   # Database statistics")
        return

    cmd = args[0]

    with db_connection() as conn:
        if cmd == "init":
            init_db()
            print("Database initialized.")

        elif cmd == "sync":
            force = "--force" in args
            count = sync_all(conn, force=force)
            print(f"Synced {count} captures.")

        elif cmd == "sync-one":
            if len(args) < 2:
                print("Usage: python db.py sync-one <capture_id>")
                return
            capture_id = args[1]
            ok = sync_one_then_alerts(capture_id, conn)
            print(f"Sync {'OK' if ok else 'FAILED'} for {capture_id}")

        elif cmd == "recent":
            limit = int(args[1]) if len(args) > 1 else 20
            rows = query_recent(conn, limit)
            for r in rows:
                print(f"  {r['capture_id']}  {r['ts_utc']}  blobs={r['blob_count']}  {r['caption'][:60] if r['caption'] else ''}")

        elif cmd == "catches":
            species = args[1] if len(args) > 1 else None
            rows = query_catches(conn, species)
            for r in rows:
                print(f"  {r['capture_id']}  {r['species']}  {r['depth_fm']}fm  x{r['count']}  {r['raw_text']}")

        elif cmd == "blobs":
            if len(args) < 2:
                print("Usage: python db.py blobs <depth_fm> [band] [tolerance]")
                return
            depth = float(args[1])
            band = args[2] if len(args) > 2 else 'lf'
            tol = float(args[3]) if len(args) > 3 else 5.0
            rows = query_blobs_at_depth(conn, depth, band, tol)
            for r in rows:
                pred = f" -> {r['predicted_species']} ({r['prediction_confidence']:.2f})" if r['predicted_species'] else ""
                print(f"  {r['capture_id']}  {r['band']}  {r['centroid_depth_fm']:.1f}fm  {r['area_px']}px2  {r['mean_intensity']:.1f}{pred}")

        elif cmd == "daily":
            if len(args) < 2:
                print("Usage: python db.py daily YYYY-MM-DD")
                return
            date_str = args[1]
            rows = query_daily_captures(conn, date_str)
            for r in rows:
                print(f"  {r['capture_id']}  {r['ts_utc']}  blobs={r['blob_count']}")

        elif cmd == "stats":
            stats = get_stats(conn)
            print(json.dumps(stats, indent=2, default=str))

        else:
            print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    cli()