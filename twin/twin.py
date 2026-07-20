"""
twin/twin.py

The Data Twin: Local storage architecture for tzpro-agent.

Follows the governing specification in boat-agent/docs/18_DATA_TWIN_STORAGE.md.
Uses stdlib only: sqlite3, hashlib, json, pathlib, shutil, os, time.

Key principles:
- Atomic writes everywhere (temp + os.replace)
- NEVER delete rows, only tombstone them (tier='gone')
- Provenance field on every record/note
- Degrade gracefully if RTree/FTS5 unavailable
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from uuid import UUID


@dataclass
class FrameResult:
    """Result of adding a frame."""
    frame_id: str
    sha256: str
    is_new: bool


def ulid_timestamp_ms() -> int:
    """Get current timestamp in milliseconds for ULID generation."""
    return int(time.time() * 1000)


def sidecar_ts_to_ms(ts) -> int:
    """Epoch ms from int/float/ISO-8601 str; falls back to now."""
    if ts is None:
        return ulid_timestamp_ms()
    if isinstance(ts, (int, float)):
        return int(ts)
    try:
        return int(ts)
    except (TypeError, ValueError):
        pass
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except ValueError:
        return ulid_timestamp_ms()


def normalize_sidecar(sidecar: dict[str, Any]) -> dict[str, Any]:
    """Normalize heterogeneous capture sidecars to the twin's flat
    epoch-ms shape. Handles tzpro's nested position block and ISO
    timestamps as well as already-flat sidecars."""
    pos = sidecar.get("position") or {}
    flat = dict(sidecar)
    flat["ts_utc"] = sidecar_ts_to_ms(sidecar.get("ts_utc"))
    flat["lat"] = pos.get("lat_dd", sidecar.get("lat"))
    flat["lon"] = pos.get("lon_dd", sidecar.get("lon"))
    flat["sog"] = pos.get("sog_kts", sidecar.get("sog"))
    flat["cog"] = pos.get("cog_deg", sidecar.get("cog"))
    if "display_geom" not in flat and "display" in sidecar:
        flat["display_geom"] = sidecar.get("display")
    return flat


def generate_frame_id(ts_ms: int) -> str:
    """
    Generate a ULID-like frame_id.
    Format: timestamp_hex (12 chars) + random_hex (4 chars)
    Example: '00000192a3e2d8f4c1b2'
    """
    import random
    # 48-bit timestamp (12 hex chars) gives ~8900 years of millisecond precision
    ts_hex = format(ts_ms & 0xFFFFFFFFFFFF, '012x')
    # 16-bit random (4 hex chars) for collision resistance
    rand_hex = format(random.randint(0, 65535), '04x')
    return f"{ts_hex}{rand_hex}"


def compute_sha256(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


class Twin:
    """
    The Data Twin: Local storage for time-synced vessel data.

    Schema follows docs/18_DATA_TWIN_STORAGE.md exactly.
    """

    def __init__(self, root: Path):
        """
        Initialize a Twin instance.

        Args:
            root: Path to the memory/ directory.
        """
        self._root = Path(root)
        self._db_path: Optional[Path] = None
        self._conn: Optional[sqlite3.Connection] = None
        self._has_rtree = False
        self._has_fts5 = False

    @property
    def root(self) -> Path:
        return self._root

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Twin not open. Call open() first.")
        return self._conn

    def open(self, root: Optional[Path] = None) -> None:
        """
        Open the twin database, creating schema if needed.

        Creates the memory/ layout:
        - meta.db (SQLite database with WAL mode)
        - blobs/ (content-addressed storage)
        - manifests/ (per-day verification units)
        - exports/ (Parquet exports)
        - gc/ (two-phase GC staging)

        Args:
            root: Optional path override for the memory directory.
        """
        if root is not None:
            self._root = Path(root)

        # Create directory structure
        self._blobs_dir = self._root / "blobs"
        self._manifests_dir = self._root / "manifests"
        self._exports_dir = self._root / "exports"
        self._gc_dir = self._root / "gc"

        for d in [self._blobs_dir, self._manifests_dir, self._exports_dir, self._gc_dir]:
            d.mkdir(parents=True, exist_ok=True)

        self._db_path = self._root / "meta.db"

        # Open connection
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row

        # Configure for durability (boat rules)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA foreign_keys=ON")

        # Check for FTS5 and RTree support
        self._check_extensions()

        # Create schema
        self._create_schema()

    def _check_extensions(self) -> None:
        """Check which SQLite extensions are available."""
        # Check FTS5
        try:
            r = self.conn.execute("SELECT fts5() FROM pragma_compile_options")
            self._has_fts5 = r.fetchone() is not None
        except sqlite3.OperationalError:
            self._has_fts5 = False

        # Check RTree
        try:
            self.conn.execute("SELECT * FROM sqlite_master WHERE type='table' AND name='rtree_generic'")
            self._has_rtree = True
        except sqlite3.OperationalError:
            self._has_rtree = True  # Available by default

    def _create_schema(self) -> None:
        """Create the database schema per docs/18."""
        cur = self.conn.cursor()

        # Main frames table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS frames (
                frame_id TEXT PRIMARY KEY,
                ts_utc INTEGER NOT NULL,
                lat REAL,
                lon REAL,
                sog REAL,
                cog REAL,
                sha256 TEXT NOT NULL REFERENCES blobs(sha256),
                bytes INTEGER NOT NULL,
                tier TEXT NOT NULL DEFAULT 'hot',
                cadence TEXT NOT NULL,
                novelty REAL,
                keep_reason TEXT,
                display_geom TEXT
            )
        """)

        cur.execute("CREATE INDEX IF NOT EXISTS idx_frames_ts ON frames(ts_utc)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_frames_tier_ts ON frames(tier, ts_utc)")

        # RTree for spatial queries (degrade gracefully)
        if self._has_rtree:
            try:
                cur.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS frames_geo
                    USING rtree(frame_id, min_lon, max_lon, min_lat, max_lat)
                """)
            except sqlite3.OperationalError:
                self._has_rtree = False

        # CAS registry (blobs)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS blobs (
                sha256 TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                bytes INTEGER NOT NULL,
                tier TEXT NOT NULL DEFAULT 'hot',
                created INTEGER NOT NULL
            )
        """)

        # Echogram records (M10 canonical record)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS echogram_records (
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
        cur.execute("CREATE INDEX IF NOT EXISTS idx_records_depth ON echogram_records(depth_top_m, depth_bot_m)")

        # Notes (M1 notes; transient by default)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                note_id TEXT PRIMARY KEY,
                ts_utc INTEGER NOT NULL,
                frame_id TEXT REFERENCES frames(frame_id),
                body TEXT,
                novelty REAL,
                retained INTEGER DEFAULT 0
            )
        """)

        # FTS5 for notes (degrade gracefully)
        if self._has_fts5:
            try:
                cur.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts
                    USING fts5(body, content='notes', content_rowid='rowid')
                """)
                # Trigger to keep FTS in sync
                cur.execute("""
                    CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
                        INSERT INTO notes_fts(rowid, body) VALUES (new.rowid, new.body);
                    END
                """)
                cur.execute("""
                    CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
                        INSERT INTO notes_fts(notes_fts, rowid, body) VALUES ('delete', old.rowid, old.body);
                    END
                """)
                cur.execute("""
                    CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
                        INSERT INTO notes_fts(notes_fts, rowid, body) VALUES ('delete', old.rowid, old.body);
                        INSERT INTO notes_fts(rowid, body) VALUES (new.rowid, new.body);
                    END
                """)
            except sqlite3.OperationalError:
                self._has_fts5 = False

        # FTS5 for records (degrade gracefully)
        if self._has_fts5:
            try:
                cur.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS records_fts
                    USING fts5(vocab_terms, record_json)
                """)
            except sqlite3.OperationalError:
                pass

        # Briefings (H1 output; canonical, never GC'd)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS briefings (
                briefing_id TEXT PRIMARY KEY,
                ts_utc INTEGER NOT NULL,
                period_start INTEGER,
                period_end INTEGER,
                body TEXT,
                body_sha256 TEXT,
                model TEXT
            )
        """)

        # Labels (THE MONEY TABLE: future training sets)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS labels (
                frame_id TEXT REFERENCES frames(frame_id),
                label TEXT,
                labeler TEXT,
                ts_utc INTEGER,
                provenance TEXT,
                PRIMARY KEY(frame_id, label, labeler)
            )
        """)

        self.conn.commit()

    def add_frame(
        self,
        png_path: Path,
        sidecar: dict[str, Any],
        cadence: str = "10min-canonical"
    ) -> FrameResult:
        """
        Add a frame to the twin database.

        STRICT WRITE ORDER:
        1. Compute SHA256 of the PNG file
        2. Copy blob to blobs/<sha[:2]>/<sha[2:4]>/<sha>.png via temp file + os.replace
        3. Insert row in ONE transaction

        Idempotent: same sha256 returns existing frame_id.

        Args:
            png_path: Path to the PNG file.
            sidecar: Dictionary with metadata (ts_utc, lat, lon, sog, cog, etc.)
            cadence: Capture cadence (e.g., '10min-canonical', '30s')

        Returns:
            FrameResult with frame_id, sha256, and is_new flag.
        """
        if not self._conn:
            raise RuntimeError("Twin not open. Call open() first.")

        sidecar = normalize_sidecar(sidecar)

        # Step 1: Compute SHA256
        sha256 = compute_sha256(png_path)

        # Check if already exists
        cur = self.conn.cursor()
        existing = cur.execute(
            "SELECT frame_id FROM frames WHERE sha256 = ?",
            (sha256,)
        ).fetchone()

        if existing:
            return FrameResult(
                frame_id=existing["frame_id"],
                sha256=sha256,
                is_new=False
            )

        # Step 2: Copy blob atomically
        blob_dir = self._blobs_dir / sha256[:2] / sha256[2:4]
        blob_dir.mkdir(parents=True, exist_ok=True)
        blob_path = blob_dir / f"{sha256}.png"

        # Atomic copy via temp file
        with tempfile.NamedTemporaryFile(
            dir=blob_dir,
            prefix=f".tmp_{sha256[:8]}_",
            suffix=".png",
            delete=False
        ) as tmp:
            tmp_path = Path(tmp.name)
            shutil.copy(png_path, tmp_path)

        try:
            os.replace(tmp_path, blob_path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

        # Step 3: Insert rows in ONE transaction
        # IMPORTANT: Insert blob first because frame has FK to blobs
        file_size = os.stat(blob_path).st_size
        ts_ms = sidecar.get("ts_utc", ulid_timestamp_ms())
        frame_id = generate_frame_id(ts_ms)

        # Register blob in CAS first
        cur.execute("""
            INSERT INTO blobs (sha256, path, bytes, tier, created)
            VALUES (?, ?, ?, ?, ?)
        """, (sha256, str(blob_path.relative_to(self._root)), file_size, "hot", int(time.time() * 1000)))

        # Now insert frame (blob FK must exist first)
        cur.execute("""
            INSERT INTO frames (
                frame_id, ts_utc, lat, lon, sog, cog,
                sha256, bytes, tier, cadence, novelty, keep_reason, display_geom
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            frame_id,
            ts_ms,
            sidecar.get("lat"),
            sidecar.get("lon"),
            sidecar.get("sog"),
            sidecar.get("cog"),
            sha256,
            file_size,
            "hot",
            cadence,
            sidecar.get("novelty"),
            sidecar.get("keep_reason"),
            json.dumps(sidecar.get("display_geom")) if sidecar.get("display_geom") else None
        ))

        self.conn.commit()

        return FrameResult(
            frame_id=frame_id,
            sha256=sha256,
            is_new=True
        )

    def add_record(self, frame_id: str, record: dict[str, Any]) -> None:
        """
        Add an echogram record for a frame.

        Args:
            frame_id: The frame to attach the record to.
            record: Dictionary with record data (depth_top_m, depth_bot_m, etc.)
        """
        cur = self.conn.cursor()

        # Compute record hash for self-verification
        record_json = json.dumps(record, separators=(",", ":"), sort_keys=True)
        record_sha256 = hashlib.sha256(record_json.encode()).hexdigest()

        cur.execute("""
            INSERT OR REPLACE INTO echogram_records (
                frame_id, ts_utc, depth_top_m, depth_bot_m,
                record_json, record_sha256, vocab_terms, model, confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            frame_id,
            record.get("ts_utc", ulid_timestamp_ms()),
            record.get("depth_top_m"),
            record.get("depth_bot_m"),
            record_json,
            record_sha256,
            record.get("vocab_terms"),
            record.get("model"),
            record.get("confidence")
        ))

        self.conn.commit()

    def add_note(
        self,
        note: dict[str, Any],
        provenance: str
    ) -> str:
        """
        Add a note (M1 transient observation).

        Args:
            note: Dictionary with note data (body, frame_id optional, novelty optional)
            provenance: Source of this note (docs/08 rule 1)

        Returns:
            The note_id.
        """
        import uuid
        note_id = str(uuid.uuid4())

        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO notes (
                note_id, ts_utc, frame_id, body, novelty, retained
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            note_id,
            note.get("ts_utc", ulid_timestamp_ms()),
            note.get("frame_id"),
            note.get("body"),
            note.get("novelty"),
            note.get("retained", 0)
        ))

        self.conn.commit()
        return note_id

    def add_briefing(
        self,
        body_md: str,
        period_start: int,
        period_end: int,
        model: str = "default"
    ) -> str:
        """
        Add a briefing (H1 canonical output).

        Args:
            body_md: Markdown body of the briefing.
            period_start: Start timestamp (ms).
            period_end: End timestamp (ms).
            model: Model that generated the briefing.

        Returns:
            The briefing_id.
        """
        import uuid
        briefing_id = str(uuid.uuid4())
        body_sha256 = hashlib.sha256(body_md.encode()).hexdigest()

        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO briefings (
                briefing_id, ts_utc, period_start, period_end,
                body, body_sha256, model
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            briefing_id,
            ulid_timestamp_ms(),
            period_start,
            period_end,
            body_md,
            body_sha256,
            model
        ))

        self.conn.commit()
        return briefing_id

    def add_label(
        self,
        frame_id: str,
        label: str,
        labeler: str,
        provenance: str
    ) -> None:
        """
        Add a label to a frame (THE MONEY TABLE).

        Args:
            frame_id: The frame to label.
            label: The label text.
            labeler: Who/what applied the label.
            provenance: Source of this label (docs/08 rule 1).
        """
        cur = self.conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO labels (
                frame_id, label, labeler, ts_utc, provenance
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            frame_id,
            label,
            labeler,
            ulid_timestamp_ms(),
            provenance
        ))

        self.conn.commit()

    def frames_since(self, ts_ms: int) -> list[sqlite3.Row]:
        """
        Get all frames since a timestamp.

        Args:
            ts_ms: Timestamp in milliseconds.

        Returns:
            List of frame rows.
        """
        cur = self.conn.cursor()
        return cur.execute(
            "SELECT * FROM frames WHERE ts_utc >= ? ORDER BY ts_utc",
            (ts_ms,)
        ).fetchall()

    def records_for_day(self, day_str: str) -> list[sqlite3.Row]:
        """
        Get all echogram records for a specific day.

        Args:
            day_str: Day string in format 'YYYY-MM-DD'.

        Returns:
            List of record rows.
        """
        from datetime import datetime, timezone

        dt = datetime.strptime(day_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        start_ms = int(dt.timestamp() * 1000)
        end_ms = int((dt.replace(hour=23, minute=59, second=59).timestamp() * 1000))

        cur = self.conn.cursor()
        return cur.execute(
            """
            SELECT er.*, f.ts_utc as frame_ts, f.lat, f.lon
            FROM echogram_records er
            JOIN frames f ON er.frame_id = f.frame_id
            WHERE er.ts_utc >= ? AND er.ts_utc <= ?
            ORDER BY er.ts_utc
            """,
            (start_ms, end_ms)
        ).fetchall()

    def get_blob_path(self, sha256: str) -> Optional[Path]:
        """
        Get the file path for a blob by its SHA256.

        Args:
            sha256: The SHA256 hash.

        Returns:
            Path to the blob file, or None if not found.
        """
        blob_path = self._blobs_dir / sha256[:2] / sha256[2:4] / f"{sha256}.png"
        if blob_path.exists():
            return blob_path
        return None

    def integrity_check(self) -> bool:
        """
        Run SQLite integrity checks.

        Returns:
            True if all checks pass, False otherwise.
        """
        cur = self.conn.cursor()

        # Run PRAGMA integrity_check
        result = cur.execute("PRAGMA integrity_check").fetchone()
        if result and result[0] != "ok":
            return False

        # Check for foreign key violations
        result = cur.execute("PRAGMA foreign_key_check").fetchall()
        if result:
            return False

        return True

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "Twin":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()
