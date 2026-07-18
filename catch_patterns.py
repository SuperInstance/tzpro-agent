"""catch_patterns.py -- Analyze sounder before catch events.

Queries captures.db to find what echo-return patterns typically precede
catches -- useful for learning "what did a productive set look like
before the fish hit the net?"

Primary entry point:
    analyze_before_catch(capture_id, lookback=3) -> dict

Also provides:
    analyze_all_catches() -> list of per-catch pattern dicts
    typical_pattern() -> aggregate over all labeled catches
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.resolve() / "captures.db"


def analyze_before_catch(capture_id: str, lookback: int = 3) -> dict:
    """Analyze the N captures immediately before a catch event.

    Looks up the given capture_id in catch_labels, then fetches the
    preceding `lookback` captures from the captures table.

    Returns:
        Dict with:
            avg_blob_count_before: float
            avg_mid_zone_intensity: float
            thermocline_count_typical: float (median, rounded)
            prev_captures: list of capture IDs examined
            catch_species: list of species labeled at this capture
            lookback: int
    """
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # 1. Find this capture's timestamp
        cur.execute(
            "SELECT ts_utc FROM captures WHERE capture_id = ?",
            (capture_id,),
        )
        row = cur.fetchone()
        if not row:
            return _empty_result(capture_id, lookback,
                                 "Capture not found in DB", [])

        ts_utc = row["ts_utc"]

        # 2. Find catch labels for this capture
        cur.execute(
            "SELECT species, depth_fm, count, confidence "
            "FROM catch_labels WHERE capture_id = ?",
            (capture_id,),
        )
        catch_rows = cur.fetchall()
        catch_species = sorted(set(r["species"] for r in catch_rows))

        # 3. Find the previous N captures (by timestamp)
        cur.execute(
            """SELECT capture_id, blob_count, mid_zone_mean,
                      thermocline_count
               FROM captures
               WHERE ts_utc < ?
               ORDER BY ts_utc DESC
               LIMIT ?""",
            (ts_utc, lookback),
        )
        prev = cur.fetchall()

        if not prev:
            return _empty_result(capture_id, lookback,
                                 "No previous captures found", catch_species)

        blob_counts = [r["blob_count"] or 0 for r in prev]
        mid_intensities = [r["mid_zone_mean"] or 0 for r in prev]
        thermo_counts = [r["thermocline_count"] or 0 for r in prev]

        avg_blob = sum(blob_counts) / len(blob_counts)
        avg_mid = sum(mid_intensities) / len(mid_intensities)

        # Median thermocline count (more robust)
        sorted_thermo = sorted(thermo_counts)
        mid_idx = len(sorted_thermo) // 2
        med_thermo = (
            sorted_thermo[mid_idx]
            if len(sorted_thermo) % 2 != 0
            else (sorted_thermo[mid_idx - 1] + sorted_thermo[mid_idx]) / 2
        )

        prev_ids = [r["capture_id"] for r in prev]

        conn.close()

        return {
            "capture_id": capture_id,
            "avg_blob_count_before": round(avg_blob, 1),
            "avg_mid_zone_intensity": round(avg_mid, 1),
            "thermocline_count_typical": round(med_thermo, 1),
            "prev_captures": prev_ids,
            "catch_species": catch_species,
            "lookback": lookback,
            "samples": len(prev),
        }

    except sqlite3.Error as e:
        return _empty_result(capture_id, lookback, str(e), [])


def _empty_result(
    capture_id: str,
    lookback: int,
    error: str,
    catch_species: list[str],
) -> dict:
    return {
        "capture_id": capture_id,
        "avg_blob_count_before": 0.0,
        "avg_mid_zone_intensity": 0.0,
        "thermocline_count_typical": 0.0,
        "prev_captures": [],
        "catch_species": catch_species,
        "lookback": lookback,
        "samples": 0,
        "error": error,
    }


def analyze_all_catches(lookback: int = 3) -> list[dict]:
    """Run analyze_before_catch for every labeled catch in the database."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cur = conn.cursor()
        cur.execute(
            """SELECT DISTINCT l.capture_id, c.ts_utc
               FROM catch_labels l
               JOIN captures c ON l.capture_id = c.capture_id
               ORDER BY c.ts_utc ASC"""
        )
        catch_ids = [row[0] for row in cur.fetchall()]
        conn.close()
        return [analyze_before_catch(cid, lookback) for cid in catch_ids]
    except sqlite3.Error:
        return []


def typical_pattern(lookback: int = 3) -> dict:
    """Compute aggregate typical pattern across all labeled catches."""
    results = analyze_all_catches(lookback)
    valid = [r for r in results if r.get("samples", 0) > 0]

    if not valid:
        return {
            "avg_blob_count_before": 0.0,
            "avg_mid_zone_intensity": 0.0,
            "thermocline_count_typical": 0.0,
            "sample_catches": 0,
            "species_summary": {},
        }

    blob_avg = sum(r["avg_blob_count_before"] for r in valid) / len(valid)
    mid_avg = sum(r["avg_mid_zone_intensity"] for r in valid) / len(valid)

    thermo_vals = sorted(r["thermocline_count_typical"] for r in valid)
    mid_idx = len(thermo_vals) // 2
    med_thermo = (
        thermo_vals[mid_idx]
        if len(thermo_vals) % 2 != 0
        else (thermo_vals[mid_idx - 1] + thermo_vals[mid_idx]) / 2
    )

    species_counts: dict[str, int] = {}
    for r in valid:
        for sp in r.get("catch_species", []):
            species_counts[sp] = species_counts.get(sp, 0) + 1

    return {
        "avg_blob_count_before": round(blob_avg, 1),
        "avg_mid_zone_intensity": round(mid_avg, 1),
        "thermocline_count_typical": round(med_thermo, 1),
        "sample_catches": len(valid),
        "species_summary": species_counts,
    }
