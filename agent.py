#!/usr/bin/env python3
"""agent.py — TzPro-Agent on-demand interface.

Called by Riker when the Captain asks a question about the TZ Pro display.
Takes a fresh screenshot, crops and analyzes the sounder, pairs with live
NMEA position, and returns structured data for the Captain's answer.

Usage:
  python agent.py               # full snap + analysis, print JSON
  python agent.py --brief        # concise summary only
  python agent.py --log          # snap + log observation + print JSON
"""

from __future__ import annotations
import json, logging, sys
from datetime import datetime, timezone

from screenshot import capture_full, crop_region
from sounder_analyzer import analyze_sounder
from logger import log_observation

log = logging.getLogger("tzpro.agent")


def snap() -> dict:
    """Take an on-demand screenshot + full analysis.

    Returns structured dict with:
      - ts, timestamp_akdt
      - full_frame, sounder_crop (filenames)
      - sounder_analysis (from sounder_analyzer)
      - nmea (position from bridge)
      - log_entry (structured observation for persistence)
    """
    result = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "timestamp_akdt": datetime.now().strftime("%H:%M:%S"),
    }

    # 1. Capture full frame
    full = capture_full()
    if not full:
        result["error"] = "capture failed"
        return result
    result["full_frame"] = full.name

    # 2. Crop sounder
    sounder = crop_region(full)
    if sounder:
        result["sounder_crop"] = sounder.name

    # 3. Analyze sounder
    if sounder:
        result["sounder_analysis"] = analyze_sounder(sounder)

    # 4. Read NMEA position
    result["nmea"] = _read_nmea()

    # 5. Build log entry
    result["log_entry"] = _build_log_entry(result)

    # 6. Persist to daily log
    log_observation(result["log_entry"])

    return result


def _read_nmea() -> dict:
    """Fetch current position from hermitd vessel endpoint."""
    try:
        import urllib.request
        from config import NMEA_VESSEL_URL
        req = urllib.request.Request(NMEA_VESSEL_URL)
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}


def _build_log_entry(snap_result: dict) -> dict:
    """Build a structured observation from snap results."""
    nmea = snap_result.get("nmea", {})
    pos = nmea.get("position") or {}
    if not pos and isinstance(nmea.get("window"), list):
        pos = nmea["window"][-1] if nmea["window"] else {}

    analysis = snap_result.get("sounder_analysis", {})

    return {
        "ts": snap_result["ts"],
        "type": "on_demand",
        "location": {
            "lat": pos.get("lat"),
            "lon": pos.get("lon"),
        },
        "vessel": {
            "sog": pos.get("sog"),
            "cog": pos.get("cog"),
        },
        "sounder": {
            "depth_fm": analysis.get("bottom_depth_fm"),
            "bottom_type": analysis.get("bottom_type"),
            "confidence": analysis.get("bottom_confidence"),
            "fish_returns": analysis.get("fish_returns"),
            "thermoclines": analysis.get("thermoclines"),
            "depth_scale": analysis.get("depth_scale"),
        },
    }


def cli():
    """CLI entry point."""
    logging.basicConfig(level=logging.WARNING)

    if "--brief" in sys.argv:
        result = snap()
        log_entry = result.get("log_entry", {})
        sounder = log_entry.get("sounder", {})
        loc = log_entry.get("location", {})
        print(f"[{result.get('timestamp_akdt', '?')}] "
              f"Lat {loc.get('lat','?'):.4f}  "
              f"Lon {loc.get('lon','?'):.4f}  "
              f"Depth {sounder.get('depth_fm','?'):.1f} fm  "
              f"Bottom {sounder.get('bottom_type','?')}  "
              f"Fish {sounder.get('fish_returns',{}).get('distribution','none')}")
        return

    result = snap()
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    cli()
