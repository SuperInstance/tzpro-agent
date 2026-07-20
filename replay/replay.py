"""replay/replay.py — perception replay harness v0.

Answers "would we have done the same thing?" by re-running analyzers over
stored frames and comparing fresh results to stored records.

Read-only: never writes to the twin. Deterministic: same input = byte-identical
report (sorted keys, no wall-clock timestamps in output).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Optional


def load_day(twin_root: Path, date: str) -> dict[str, Any]:
    """Load frames, records, and notes for a given day from meta.db.

    Args:
        twin_root: Path to twin directory (contains meta.db)
        date: Date string in YYYY-MM-DD format

    Returns:
        Dictionary with 'frames', 'records', 'notes' keys, each a list of dicts
        sorted by timestamp ascending.

    Raises:
        ValueError: If date format is invalid
        RuntimeError: If database cannot be opened or no data found
    """
    twin_root = Path(twin_root)
    db_path = twin_root / "meta.db"

    if not db_path.exists():
        raise RuntimeError(f"Twin database not found: {db_path}")

    # Parse and validate date
    try:
        dt = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as e:
        raise ValueError(f"Invalid date format '{date}': use YYYY-MM-DD") from e

    start_ms = int(dt.timestamp() * 1000)
    end_ms = int((dt.replace(hour=23, minute=59, second=59, microsecond=999999).timestamp() * 1000))

    conn = None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        # Load frames with blob paths
        frames = []
        cur = conn.cursor()
        for row in cur.execute(
            "SELECT * FROM frames WHERE ts_utc >= ? AND ts_utc <= ? ORDER BY ts_utc",
            (start_ms, end_ms)
        ):
            frames.append(dict(row))

        # Load echogram records
        records = []
        for row in cur.execute(
            """SELECT er.*, f.lat, f.lon, f.sha256, f.bytes
               FROM echogram_records er
               JOIN frames f ON er.frame_id = f.frame_id
               WHERE er.ts_utc >= ? AND er.ts_utc <= ?
               ORDER BY er.ts_utc""",
            (start_ms, end_ms)
        ):
            record = dict(row)
            # Parse record_json if present
            if record.get("record_json"):
                try:
                    record["record_data"] = json.loads(record["record_json"])
                except json.JSONDecodeError:
                    record["record_data"] = None
            records.append(record)

        # Load notes
        notes = []
        for row in cur.execute(
            "SELECT * FROM notes WHERE ts_utc >= ? AND ts_utc <= ? ORDER BY ts_utc",
            (start_ms, end_ms)
        ):
            notes.append(dict(row))

        if not frames and not records and not notes:
            raise RuntimeError(f"No data found for {date}")

        return {
            "date": date,
            "frames": frames,
            "records": records,
            "notes": notes,
        }

    finally:
        if conn:
            conn.close()


def _jaccard_similarity(set1: set[str], set2: set[str]) -> float:
    """Compute Jaccard similarity between two sets."""
    if not set1 and not set2:
        return 1.0
    if not set1 or not set2:
        return 0.0
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    return intersection / union if union > 0 else 0.0


def _compare_records(stored: dict, fresh: dict) -> dict[str, Any]:
    """Compare a stored record with a fresh analysis result.

    Agreement criteria:
    1. same bottom_type (if both present)
    2. |bottom_fm delta| <= 3.0 fathoms
    3. overlapping search_terms (Jaccard >= 0.3)

    Returns:
        Dict with 'agree' (bool) and 'deltas' (list of field differences)
    """
    deltas = []
    agree = True

    # Extract stored values (handle both record_json and record_data)
    stored_data = stored.get("record_data") or {}
    if not stored_data and stored.get("record_json"):
        try:
            stored_data = json.loads(stored["record_json"])
        except json.JSONDecodeError:
            stored_data = {}

    # 1. Bottom type comparison
    stored_bt = stored_data.get("bottom_type") or stored.get("bottom_type")
    fresh_bt = fresh.get("bottom_type")
    if stored_bt and fresh_bt:
        if stored_bt != fresh_bt:
            agree = False
            deltas.append({"field": "bottom_type", "stored": stored_bt, "fresh": fresh_bt})

    # 2. Bottom depth comparison (within 3.0 fathoms)
    stored_fm = stored_data.get("bottom_fm") or stored.get("bottom_fm")
    fresh_fm = fresh.get("bottom_fm")
    if stored_fm is not None and fresh_fm is not None:
        try:
            delta = abs(float(stored_fm) - float(fresh_fm))
            if delta > 3.0:
                agree = False
                deltas.append({"field": "bottom_fm", "stored": stored_fm, "fresh": fresh_fm, "delta": round(delta, 2)})
        except (ValueError, TypeError):
            pass

    # 3. Search terms Jaccard similarity
    stored_terms = set(stored_data.get("search_terms") or [])
    if not stored_terms and isinstance(stored.get("vocab_terms"), str):
        stored_terms = set(stored["vocab_terms"].split())
    fresh_terms = set(fresh.get("search_terms") or [])

    if stored_terms or fresh_terms:
        jaccard = _jaccard_similarity(stored_terms, fresh_terms)
        if jaccard < 0.3:
            agree = False
            deltas.append({
                "field": "search_terms",
                "stored": sorted(stored_terms),
                "fresh": sorted(fresh_terms),
                "jaccard": round(jaccard, 3)
            })

    return {"agree": agree, "deltas": deltas}


def _stub_analyzer(frame_path: Path, sidecar: dict) -> dict:
    """Default stub analyzer that returns the stored record (self-consistency).

    This stub returns data from the sidecar's embedded record_data if available,
    ensuring self-consistency checks yield 1.0 agreement.

    Real model-based analyzers should be passed via --model flag.
    """
    # Return stored record data for self-consistency
    record_data = sidecar.get("record_data", {})
    if not record_data and sidecar.get("record_json"):
        try:
            record_data = json.loads(sidecar["record_json"])
        except json.JSONDecodeError:
            pass
    return record_data


def _get_blob_path(twin_root: Path, sha256: str) -> Optional[Path]:
    """Get the blob path for a given SHA256 hash."""
    blob_path = twin_root / "blobs" / sha256[:2] / sha256[2:4] / f"{sha256}.png"
    return blob_path if blob_path.exists() else None


def replay_day(
    twin_root: Path,
    date: str,
    analyzer_fn: Optional[Callable[[Path, dict], dict]] = None
) -> dict[str, Any]:
    """Re-run analyzer over each frame and compare to stored records.

    Args:
        twin_root: Path to twin directory
        date: Date string in YYYY-MM-DD format
        analyzer_fn: Callable taking (frame_path, sidecar) -> dict analysis result.
                     Defaults to stub that returns stored record (1.0 agreement).

    Returns:
        Structured report with keys:
        - date: replay date string
        - frames: total frames processed
        - replayed: count of frames with fresh analysis
        - agreement_rate: float 0.0-1.0
        - per_frame: list of dicts with frame_id, stored, fresh, agree, deltas

    Raises:
        RuntimeError: If date has no data
    """
    twin_root = Path(twin_root)

    # Use stub analyzer if none provided
    if analyzer_fn is None:
        analyzer_fn = _stub_analyzer

    # Load day's data
    day_data = load_day(twin_root, date)

    # Build lookup: frame_id -> echogram_record
    records_by_frame: dict[str, dict] = {}
    for record in day_data["records"]:
        frame_id = record.get("frame_id")
        if frame_id:
            records_by_frame[frame_id] = record

    # Replay each frame in timestamp order
    per_frame = []
    replayed_count = 0
    agreement_count = 0

    for frame in day_data["frames"]:
        frame_id = frame["frame_id"]
        sha256 = frame["sha256"]

        # Get blob path for this frame
        frame_path = _get_blob_path(twin_root, sha256)
        if frame_path is None:
            # Frame blob missing - skip
            per_frame.append({
                "frame_id": frame_id,
                "stored": None,
                "fresh": None,
                "agree": None,
                "deltas": [{"error": "blob_missing"}]
            })
            continue

        # Get stored record (if any)
        stored_record = records_by_frame.get(frame_id)

        # Prepare sidecar for analyzer (include stored record for stub)
        sidecar = {
            "frame_id": frame_id,
            "ts_utc": frame["ts_utc"],
            "lat": frame.get("lat"),
            "lon": frame.get("lon"),
            "sog": frame.get("sog"),
            "cog": frame.get("cog"),
        }

        # If using stub, embed stored record data for self-consistency
        if stored_record and analyzer_fn == _stub_analyzer:
            sidecar["record_data"] = stored_record.get("record_data")
            if not sidecar["record_data"] and stored_record.get("record_json"):
                try:
                    sidecar["record_data"] = json.loads(stored_record["record_json"])
                except json.JSONDecodeError:
                    pass

        # Run fresh analysis
        try:
            fresh_result = analyzer_fn(frame_path, sidecar)
            replayed_count += 1
        except Exception as e:
            per_frame.append({
                "frame_id": frame_id,
                "stored": stored_record,
                "fresh": None,
                "agree": False,
                "deltas": [{"error": f"analysis_failed: {e}"}]
            })
            continue

        # Compare if we have a stored record
        if stored_record:
            comparison = _compare_records(stored_record, fresh_result)
            agree = comparison["agree"]
            if agree:
                agreement_count += 1

            per_frame.append({
                "frame_id": frame_id,
                "stored": {
                    "bottom_type": stored_record.get("bottom_type"),
                    "bottom_fm": stored_record.get("bottom_fm"),
                    "search_terms": stored_record.get("vocab_terms"),
                },
                "fresh": {
                    "bottom_type": fresh_result.get("bottom_type"),
                    "bottom_fm": fresh_result.get("bottom_fm"),
                    "search_terms": fresh_result.get("search_terms"),
                },
                "agree": agree,
                "deltas": comparison["deltas"]
            })
        else:
            # No stored record to compare against
            per_frame.append({
                "frame_id": frame_id,
                "stored": None,
                "fresh": fresh_result,
                "agree": None,
                "deltas": [{"note": "no_stored_record"}]
            })

    # Calculate agreement rate
    agreement_rate = (
        agreement_count / replayed_count if replayed_count > 0 else 0.0
    )

    return {
        "date": date,
        "frames": len(day_data["frames"]),
        "replayed": replayed_count,
        "agreement_rate": round(agreement_rate, 4),
        "per_frame": per_frame,
    }


def _model_analyzer(twin_root: Path, model: str = "gemma4:12b") -> Callable[[Path, dict], dict]:
    """Factory returning an analyzer that calls cascade's ollama vision model.

    The returned function loads cascade modules and runs M10 analysis.

    Args:
        twin_root: Path to twin root (for cascade module resolution)
        model: Model name to use for inference

    Returns:
        Analyzer function compatible with replay_day
    """
    # Import cascade components lazily (only when --model is used)
    try:
        # Add parent directory to path for cascade imports
        import sys
        root_dir = Path(__file__).parent.parent
        if str(root_dir) not in sys.path:
            sys.path.insert(0, str(root_dir))

        from cascade import ollama_client as oll
        from cascade import config
    except ImportError as e:
        raise RuntimeError(f"Failed to import cascade modules: {e}")

    def analyzer(frame_path: Path, sidecar: dict) -> dict:
        """Run M10-style vision analysis on a frame."""
        from cascade.decaminute_loop import PROMPT

        # Build context from sidecar
        context = f"Frame: {sidecar.get('frame_id')}"
        if sidecar.get("lat") and sidecar.get("lon"):
            context += f" at ({sidecar['lat']}, {sidecar['lon']})"

        prompt = f"{PROMPT}\n\n{context}"

        # Run vision inference
        raw = oll.vision_prompt(
            frame_path,
            prompt,
            model,
            config.M10_MAX_TOKENS
        )

        if raw is None:
            raise RuntimeError("Vision inference failed")

        # Extract JSON response
        parsed = oll.extract_json(raw) or {}
        if not parsed:
            raise RuntimeError("Failed to extract JSON from model response")

        return parsed

    return analyzer
