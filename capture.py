#!/usr/bin/env python3
"""capture.py — TzPro-Agent screen capture daemon.

Runs in the background with a dual-cadence capture loop:
  - Sounder crop (370×900): every 30 seconds for live analysis
  - Full frame (1920×1080): every 4 minutes for permanent filmstrip record

Usage:
  python capture.py            # run daemon (Ctrl+C to stop)
  python capture.py --oneshot  # single capture + analysis, print JSON, exit
"""

from __future__ import annotations
import asyncio, json, logging, sys, time
from datetime import datetime, timezone
from pathlib import Path

from config import (
    SOUNDER_INTERVAL,
    FULL_INTERVAL,
    SOUNDER_CROP,
    NMEA_VESSEL_URL,
    CAPTURES_DIR,
)
from screenshot import capture_full, crop_region, capture_sounder
from sounder_analyzer import analyze_sounder
from logger import log_observation

# Optional anomaly logger (Phase 3)
try:
    from anomaly_logger import log_anomaly, get_db
    _ANOMALY_ACTIVE = True
except ImportError:
    _ANOMALY_ACTIVE = False

log = logging.getLogger("tzpro.capture")

# Track last capture times
_last_sounder: float = 0.0
_last_full: float = 0.0


def read_nmea() -> dict:
    """Fetch current NMEA position from hermitd's vessel endpoint."""
    try:
        import urllib.request
        req = urllib.request.Request(NMEA_VESSEL_URL)
        with urllib.request.urlopen(req, timeout=3) as resp:
            import json as j
            data = j.loads(resp.read().decode())
        if data.get("position"):
            return {
                "lat": data["position"]["lat"],
                "lon": data["position"]["lon"],
                "sog": data["position"]["sog"],
                "cog": data["position"].get("cog"),
            }
    except Exception as e:
        log.warning("NMEA read: %s", e)
    return {}


async def capture_loop():
    """Main dual-cadence capture loop."""
    global _last_sounder, _last_full

    log.info("=" * 50)
    log.info("TzPro-Agent capture daemon v1")
    log.info("  Sounder crop: every %ds  |  Full frame: every %ds", SOUNDER_INTERVAL, FULL_INTERVAL)
    log.info("  Sounder region: %s", SOUNDER_CROP)
    log.info("  Captures dir: %s", CAPTURES_DIR)
    log.info("=" * 50)

    CAPTURES_DIR.mkdir(parents=True, exist_ok=True)

    while True:
        now = time.time()
        nmea = read_nmea()

        # ── Full frame every 4 minutes ──────────────────────────────
        if now - _last_full >= FULL_INTERVAL:
            full = capture_full()
            if full:
                log.info("Full: %s (%d KB)", full.name, full.stat().st_size // 1024)
                _last_full = now

                # Crop and analyze sounder from full frame
                sounder = crop_region(full)
                if sounder:
                    log.info("Sounder: %s", sounder.name)
                    _log_and_analyze(sounder, nmea)

            _last_sounder = now  # sync sounder timer

        # ── Sounder-only every 30 seconds ───────────────────────────
        elif now - _last_sounder >= SOUNDER_INTERVAL:
            # Fast capture: take full frame, crop sounder, discard full frame
            sounder = capture_sounder()
            if sounder:
                log.info("Sounder@%ds: %s", int(now - _last_sounder), sounder.name)
                _last_sounder = now
                _log_and_analyze(sounder, nmea)
            else:
                log.warning("Sounder capture failed, retrying...")
                _last_sounder = now  # prevent busy-loop

        await asyncio.sleep(5)


def _log_and_analyze(sounder_path: Path, nmea: dict):
    """Analyze a sounder crop and write structured log entry."""
    analysis = analyze_sounder(sounder_path)

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sounder": sounder_path.name,
        "position": {
            "lat": nmea.get("lat"),
            "lon": nmea.get("lon"),
        },
        "vessel": {
            "sog": nmea.get("sog"),
            "cog": nmea.get("cog"),
        },
        "sounder_analysis": {
            "depth_fm": analysis.get("bottom_depth_fm"),
            "pixel_y": analysis.get("bottom_pixel_y"),
            "bottom_type": analysis.get("bottom_type"),
            "confidence": analysis.get("bottom_confidence"),
            "fish": analysis.get("fish_returns"),
            "thermoclines": analysis.get("thermoclines"),
            "profile": analysis.get("signal_profile"),
        },
    }

    log_observation(entry)

    # Log anomaly if we have position and depth
    if _ANOMALY_ACTIVE and nmea.get("lat") and analysis.get("bottom_depth_fm"):
        try:
            # contour_fm=None means we only log the sounder reading;
            # the contour comparison will be added when Phase 2 grid is ready
            log_anomaly(
                lat=nmea["lat"],
                lon=nmea["lon"],
                sounder_fm=analysis["bottom_depth_fm"],
                contour_fm=None,
                sog=nmea.get("sog"),
                source="capture",
            )
        except Exception as e:
            log.debug("Anomaly log: %s", e)

    log.info(
        "Logged: depth=%.1ffm type=%s fish=%s",
        entry["sounder_analysis"].get("depth_fm") or 0,
        entry["sounder_analysis"].get("bottom_type") or "?",
        entry["sounder_analysis"].get("fish", {}).get("distribution") or "none",
    )


def oneshot() -> dict:
    """Single capture + analysis. Returns structured result dict."""
    nmea = read_nmea()
    sounder = capture_sounder()
    if not sounder:
        return {"error": "capture failed"}

    analysis = analyze_sounder(sounder)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sounder": str(sounder.name),
        "position": nmea,
        "analysis": analysis,
    }
    return entry


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )
    CAPTURES_DIR.mkdir(parents=True, exist_ok=True)

    if "--oneshot" in sys.argv:
        result = oneshot()
        print(json.dumps(result, indent=2, default=str))
        return

    try:
        asyncio.run(capture_loop())
    except KeyboardInterrupt:
        log.info("Shutdown")


if __name__ == "__main__":
    main()
