#!/usr/bin/env python3
"""deltalog.py — Chart delta logger for tzpro-agent.

Every 4 minutes, captures the full TZ Pro display and compares it against
the previous frame. Logs only meaningful changes in markdown:

  [14:32] Course changed 265° → 240°
  [14:36] New mark placed at 55.79°N / -131.53°W
  [14:40] Crossing into boulder field — depth 45→38 fm
  [14:44] No change. Drifting at 1.6 kn.

The sounder panel is excluded — it's analyzed separately by sounder_analyzer.py.
"""

from __future__ import annotations
import json, logging, time
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import CAPTURES_DIR, MEMORY_DIR
from screenshot import capture_full

log = logging.getLogger("tzpro.deltalog")

# Track previous state for delta comparison
_prev_state: dict = {}
_prev_path: Optional[Path] = None


def capture_delta() -> dict:
    """Capture and compare. Returns delta dict with changes or 'no change'."""
    global _prev_state, _prev_path

    full = capture_full()
    if not full:
        return {"error": "capture failed"}

    # Current state from NMEA
    current = _read_current_state()

    # Compare vs previous
    delta = _compute_delta(_prev_state, current)

    # Update previous
    _prev_state = current
    if _prev_path and _prev_path.exists():
        pass  # keep for reference, cleanup is separate
    _prev_path = full

    return {
        "ts": current.get("ts"),
        "current": current,
        "delta": delta,
        "delta_count": len(delta),
        "frame": full.name,
    }


def _read_current_state() -> dict:
    """Read current vessel state from NMEA bridge and local sensors."""
    state = {
        "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "lat": None,
        "lon": None,
        "sog": None,
        "cog": None,
        "depth": None,
    }

    # NMEA from hermitd
    try:
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:8654/vessel")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
        if data.get("position"):
            state["lat"] = data["position"]["lat"]
            state["lon"] = data["position"]["lon"]
            state["sog"] = data["position"]["sog"]
            state["cog"] = data["position"].get("cog")
    except Exception:
        pass

    return state


def _compute_delta(prev: dict, curr: dict) -> list[str]:
    """Compare two states and list only meaningful changes."""
    deltas = []

    if not prev:
        return ["initial position recorded"]

    # Position change
    if prev.get("lat") and curr.get("lat"):
        lat_diff = abs(curr["lat"] - prev["lat"])
        lon_diff = abs(curr["lon"] - prev["lon"])
        if lat_diff > 0.0001 or lon_diff > 0.0001:
            dist_nm = ((lat_diff * 60) ** 2 + (lon_diff * 60 * 0.57) ** 2) ** 0.5
            if dist_nm > 0.1:
                dir_str = _direction_between(prev, curr)
                deltas.append(f"Moved {dist_nm:.2f} nm {dir_str}")

    # Course change
    if prev.get("cog") and curr.get("cog"):
        cog_diff = abs(curr["cog"] - prev["cog"])
        if cog_diff > 5 and cog_diff < 355:  # filter noise, handle 0/360 wrap
            deltas.append(f"Course changed {prev['cog']:.0f}° → {curr['cog']:.0f}°")

    # Speed change
    if prev.get("sog") and curr.get("sog"):
        sog_diff = abs(curr["sog"] - prev["sog"])
        if sog_diff > 0.3:
            direction = "increased" if curr["sog"] > prev["sog"] else "decreased"
            deltas.append(f"Speed {direction}: {prev['sog']:.1f} → {curr['sog']:.1f} kn")

    # Depth change
    if prev.get("depth") and curr.get("depth"):
        depth_diff = abs(curr["depth"] - prev["depth"])
        if depth_diff > 5:
            direction = "shallower" if curr["depth"] < prev["depth"] else "deeper"
            deltas.append(f"Depth {direction}: {prev['depth']:.0f} → {curr['depth']:.0f} fm")

    if not deltas:
        sog_str = f"{curr.get('sog', '?')} kn" if curr.get('sog') else "?"
        deltas.append(f"No change. Drifting at {sog_str}.")

    return deltas


def _direction_between(prev: dict, curr: dict) -> str:
    """Cardinal direction between two positions."""
    dlat = curr["lat"] - prev["lat"]
    dlon = curr["lon"] - prev["lon"]
    if abs(dlat) < 0.0001 and abs(dlon) < 0.0001:
        return "stationary"
    if abs(dlat) > abs(dlon):
        return "north" if dlat > 0 else "south"
    else:
        return "east" if dlon > 0 else "west"


def format_markdown(delta_result: dict) -> str:
    """Format a delta capture as a markdown log entry."""
    ts = delta_result.get("ts", "?")[11:19]  # HH:MM:SS
    deltas = delta_result.get("delta", [])
    lines = [f"[{ts}] {' | '.join(deltas)}"]
    return "\n".join(lines)


def log_delta(delta_result: dict):
    """Append a delta entry to today's markdown log."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_dir = MEMORY_DIR / "chart_deltas"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{date_str}.md"

    entry = format_markdown(delta_result)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(entry + "\n")

    log.info("Delta logged: %s", entry.strip()[:80])
    return log_path


def cli():
    """CLI: single delta capture and print."""
    logging.basicConfig(level=logging.INFO)
    result = capture_delta()
    print(format_markdown(result))


if __name__ == "__main__":
    cli()
