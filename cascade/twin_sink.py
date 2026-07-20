"""cascade/twin_sink.py — optional persistence of cascade outputs into the
data twin (boat-agent docs/18).

NON-FATAL BY CONTRACT: if the twin package or DB is unavailable, the loops
keep their file outputs and log quietly. Perception must never fail
because storage failed (docs/17 constraint 5: degrade, don't die).
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from . import config

log = logging.getLogger("cascade.twin_sink")

_twin = None
_tried = False


def get_twin():
    """Lazily open the twin at <workspace>/memory. Returns None if absent."""
    global _twin, _tried
    if _tried:
        return _twin
    _tried = True
    try:
        from twin import Twin  # sibling package in tzpro-agent

        t = Twin(Path(config.WORKSPACE) / "memory")
        t.open()
        _twin = t
        log.info("twin connected at %s", Path(config.WORKSPACE) / "memory")
    except Exception as e:
        log.info("twin unavailable (%s) — file outputs only", e)
    return _twin


def _to_ms(ts) -> int:
    """Epoch ms from int/float/ISO-8601 str; falls back to now."""
    if ts is None:
        return int(time.time() * 1000)
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
        return int(time.time() * 1000)


def _normalize_sidecar(sidecar: dict) -> dict:
    """Adapt tzpro capture sidecars (nested position, ISO ts) to the
    twin's flat epoch-ms shape. The twin stays clean; adapters live here."""
    pos = sidecar.get("position") or {}
    return {
        "ts_utc": _to_ms(sidecar.get("ts_utc")),
        "lat": pos.get("lat_dd", sidecar.get("lat")),
        "lon": pos.get("lon_dd", sidecar.get("lon")),
        "sog": pos.get("sog_kts", sidecar.get("sog")),
        "cog": pos.get("cog_deg", sidecar.get("cog")),
        "display_geom": sidecar.get("display", sidecar.get("display_geom")),
    }


def add_frame(png_path, sidecar: dict, cadence: str = "10min-canonical") -> str | None:
    """Register a frame (idempotent by content hash). Returns frame_id or None."""
    t = get_twin()
    if not t:
        return None
    try:
        return t.add_frame(Path(png_path), _normalize_sidecar(sidecar), cadence).frame_id
    except Exception as e:
        log.warning("twin.add_frame failed for %s: %s", png_path, e)
        return None


def add_note(note: dict) -> None:
    t = get_twin()
    if not t:
        return
    try:
        t.add_note(note, provenance=f"cascade.m1/{note.get('model', 'unknown')}")
    except Exception as e:
        log.warning("twin.add_note failed: %s", e)


def add_record(record: dict) -> None:
    t = get_twin()
    if not t:
        return
    frame_id = record.get("frame_id")
    if not frame_id:
        return
    try:
        t.add_record(frame_id, record)
    except Exception as e:
        log.warning("twin.add_record failed: %s", e)


def add_briefing(body_md: str, model: str) -> None:
    t = get_twin()
    if not t:
        return
    try:
        now_ms = int(time.time() * 1000)
        t.add_briefing(body_md, now_ms - 3600_000, now_ms, model)
    except Exception as e:
        log.warning("twin.add_briefing failed: %s", e)
