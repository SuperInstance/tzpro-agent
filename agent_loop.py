#!/usr/bin/env python3
"""
agent_loop.py — ZeroClaw tactical agent loop.

The alert engine. Runs alongside the capture daemon, reads observations,
queries the forward look, and generates actionable alerts for the Captain.

Alert severity levels:
    CRITICAL — Immediate action required (anchor/grounding hazard)
    WARNING  — Pay attention soon (gear contour crossing)
    INFO     — Interesting observation (depth anomaly, fish concentration)
    DEBUG    — System status (logged but not surfaced)

Design:
    Runs as a polling loop on a configurable interval (default: 30s).
    Reads the latest capture + analysis from the filesystem or database.
    No GPU inference yet — that's Phase 5 (Florence-2).

Usage:
    python agent_loop.py              # Start the agent loop
    python agent_loop.py --oneshot    # Single evaluation, print alerts
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Local
from contour_query import get_depth_fm, get_gear_clearance, get_contour_bands
from forward_look import predict_ahead, prediction_stats
from anomaly_logger import log_anomaly, stats as anomaly_stats
from config import NMEA_VESSEL_URL, WORKSPACE

log = logging.getLogger("tzpro.agent_loop")

# ── Config ──────────────────────────────────────────────────────────
POLL_INTERVAL = 30  # seconds between evaluation cycles
ALERT_HISTORY = []  # in-memory alert buffer (last 50)
MAX_ALERTS = 50

# Captain's critical depth lines
GEAR_DEPTH_FM = 48
ANCHOR_SAFE_FM = 5

# Suppression: don't repeat the same alert within this window
ALERT_COOLDOWN_S = 300  # 5 minutes


class Alert:
    """An actionable observation for the Captain."""
    
    def __init__(
        self,
        severity: str,
        message: str,
        lat: float = None,
        lon: float = None,
        depth_fm: float = None,
        details: dict = None,
    ):
        self.ts = datetime.now(timezone.utc).isoformat()
        self.severity = severity
        self.message = message
        self.lat = lat
        self.lon = lon
        self.depth_fm = depth_fm
        self.details = details or {}
        self.fingerprint = self._make_fingerprint()
    
    def _make_fingerprint(self) -> str:
        """Create a dedup key so we don't repeat the same alert."""
        # Use message + rounded position
        lat_r = round(self.lat, 3) if self.lat else 0
        lon_r = round(self.lon, 3) if self.lon else 0
        return f"{self.severity}:{self.message[:60]}:{lat_r}:{lon_r}"
    
    def should_suppress(self, history: list) -> bool:
        """Check if a similar alert was sent recently."""
        cutoff = time.time() - ALERT_COOLDOWN_S
        for a in history:
            if a.fingerprint == self.fingerprint:
                return True
        return False
    
    def to_dict(self) -> dict:
        return {
            "ts": self.ts,
            "severity": self.severity,
            "message": self.message,
            "lat": self.lat,
            "lon": self.lon,
            "depth_fm": self.depth_fm,
        }
    
    def __repr__(self) -> str:
        return f"[{self.severity}] {self.message}"


def read_vessel_position() -> Optional[dict]:
    """Fetch current NMEA position from hermitd."""
    try:
        import urllib.request
        req = urllib.request.Request(NMEA_VESSEL_URL)
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
        if data.get("position"):
            return {
                "lat": data["position"]["lat"],
                "lon": data["position"]["lon"],
                "sog": data["position"].get("sog"),
                "cog": data["position"].get("cog"),
            }
    except Exception as e:
        log.debug("NMEA read: %s", e)
    return None


def evaluate_alerts(position: dict) -> list[Alert]:
    """Evaluate current position against all alert rules.
    
    This is the core reasoning function. Every 30 seconds, this runs
    and generates any actionable alerts.
    """
    alerts = []
    lat, lon = position.get("lat"), position.get("lon")
    sog = position.get("sog")
    cog = position.get("cog")
    
    if not lat or not lon:
        return []
    
    # ── Rule 1: Gear contour check ──────────────────────────────────
    # Is the vessel near or across the gear depth contour?
    try:
        gear = get_gear_clearance(lat, lon, GEAR_DEPTH_FM)
        if "error" not in gear:
            clearance = gear["clearance_fm"]
            status = gear["status"]
            
            if status == "hazard":
                alerts.append(Alert(
                    severity="CRITICAL",
                    message=f"GEAR HAZARD — bottom ({gear['charted_fm']} fm) shallower than gear depth ({GEAR_DEPTH_FM} fm) by {abs(clearance):.0f} fm!",
                    lat=lat, lon=lon,
                    depth_fm=gear["charted_fm"],
                    details={"clearance_fm": clearance, "gear_fm": GEAR_DEPTH_FM},
                ))
            elif status == "close":
                alerts.append(Alert(
                    severity="WARNING",
                    message=f"Approaching gear depth — {clearance:.0f} fm above {GEAR_DEPTH_FM} fm contour",
                    lat=lat, lon=lon,
                    depth_fm=gear["charted_fm"],
                    details={"clearance_fm": clearance},
                ))
    except Exception as e:
        log.debug("Gear check: %s", e)
    
    # ── Rule 2: Anchor contour check ────────────────────────────────
    # Is the vessel in water shallow enough to safely anchor?
    try:
        current_depth = get_depth_fm(lat, lon)
        if current_depth is not None and current_depth < ANCHOR_SAFE_FM:
            alerts.append(Alert(
                severity="INFO",
                message=f"Anchor-able depth — {current_depth:.0f} fm at position (safe anchor at {ANCHOR_SAFE_FM} fm)",
                lat=lat, lon=lon,
                depth_fm=current_depth,
            ))
    except Exception as e:
        log.debug("Anchor check: %s", e)
    
    # ── Rule 3: Forward look ────────────────────────────────────────
    # What's ahead? Any contour crossings coming up?
    if sog is not None and cog is not None:
        try:
            fwd = predict_ahead(lat, lon, float(cog or 0), float(sog))
            if "alerts" in fwd:
                for a in fwd["alerts"]:
                    alerts.append(Alert(
                        severity=a["severity"],
                        message=a["message"],
                        lat=lat, lon=lon,
                        depth_fm=current_depth if current_depth else None,
                        details={
                            "distance_nm": a.get("distance_nm"),
                            "contour_fm": a.get("contour_fm"),
                            "forward_profile": fwd.get("profile"),
                        },
                    ))
        except Exception as e:
            log.debug("Forward look: %s", e)
    
    # ── Rule 4: Anchor drift check ──────────────────────────────────
    # If at anchor (SOG ~0), are we drifting toward shallow water?
    if sog is not None and sog < 0.5:
        # Check all 8 compass points for nearest gear crossing
        try:
            min_dist = None
            min_hdg = None
            for hdg in range(0, 360, 45):
                fwd = predict_ahead(lat, lon, hdg, max(sog, 0.5))
                nearest = fwd.get("nearest_crossing")
                if nearest:
                    d = nearest.get("crossing_distance_nm")
                    if d and (min_dist is None or d < min_dist):
                        min_dist = d
                        min_hdg = hdg
            
            if min_dist is not None and min_dist < 0.1:
                cardinal = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
                dir_label = cardinal[min_hdg // 45] if min_hdg is not None else "?"
                alerts.append(Alert(
                    severity="WARNING",
                    message=f"Drift check: nearest gear contour crossing {min_dist:.2f} nm to {dir_label} ({min_hdg}°)",
                    lat=lat, lon=lon,
                    details={"min_distance_nm": min_dist, "direction_deg": min_hdg},
                ))
        except Exception as e:
            log.debug("Drift check: %s", e)
    
    # ── Rule 5: Contour bands nearby ────────────────────────────────
    # Interesting bottom structure? Multiple contour bands = complex bottom
    try:
        bands = get_contour_bands(lat, lon)
        if len(bands) >= 4:
            alerts.append(Alert(
                severity="INFO",
                message=f"Complex bottom — {len(bands)} contour bands within 0.01°: {list(bands.keys())}",
                lat=lat, lon=lon,
                depth_fm=current_depth if current_depth else None,
                details={"contour_bands": list(bands.keys())},
            ))
    except Exception as e:
        log.debug("Contour bands: %s", e)
    
    return alerts


def cycle(position: dict) -> list[Alert]:
    """One evaluation cycle. Returns new alerts."""
    global ALERT_HISTORY
    
    new_alerts = evaluate_alerts(position)
    
    # Filter suppressed alerts
    unsuppressed = [a for a in new_alerts if not a.should_suppress(ALERT_HISTORY)]
    
    # Add to history
    for a in unsuppressed:
        ALERT_HISTORY.append(a)
    
    # Trim history
    if len(ALERT_HISTORY) > MAX_ALERTS:
        ALERT_HISTORY = ALERT_HISTORY[-MAX_ALERTS:]
    
    return unsuppressed


def main_loop():
    """Background agent loop — polls position every 30s, evaluates alerts."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    
    log.info("=" * 50)
    log.info("ZeroClaw Agent Loop v1")
    log.info("  Poll interval: %ds", POLL_INTERVAL)
    log.info("  Rules: gear=%dfm, anchor=%dfm", GEAR_DEPTH_FM, ANCHOR_SAFE_FM)
    log.info("=" * 50)
    
    cycle_count = 0
    while True:
        cycle_count += 1
        
        position = read_vessel_position()
        if not position:
            log.warning("No position data — waiting")
            time.sleep(POLL_INTERVAL)
            continue
        
        alerts = cycle(position)
        
        for a in alerts:
            log.warning("%s", a)
        
        if alerts:
            log.info("--- %d alert(s) for this cycle ---", len(alerts))
        elif cycle_count % 10 == 0:
            lat = position.get("lat", "?")
            lon = position.get("lon", "?")
            log.info("All clear at (%.4f, %.4f) — cycle %d", lat, lon, cycle_count)
        
        # Sync with anomaly logger
        try:
            stats = anomaly_stats()
            if stats.get("total"):
                log.debug("Anomaly DB: %d observations", stats["total"])
        except Exception:
            pass
        
        time.sleep(POLL_INTERVAL)


def oneshot() -> dict:
    """Single evaluation cycle. Returns alerts + state."""
    position = read_vessel_position()
    if not position:
        return {"error": "No position data"}
    
    # Get current depth
    depth = get_depth_fm(position.get("lat"), position.get("lon"))
    gear = get_gear_clearance(position.get("lat"), position.get("lon"), GEAR_DEPTH_FM)
    
    # Forward look
    sog = position.get("sog") or 0
    cog = position.get("cog") or 0
    fwd = predict_ahead(position["lat"], position["lon"], float(cog), float(sog))
    
    alerts = evaluate_alerts(position)
    
    result = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "position": position,
        "current_depth_fm": depth,
        "gear_clearance": gear,
        "forward_look": fwd,
        "alerts": [a.to_dict() for a in alerts],
        "anomaly_stats": anomaly_stats(),
        "prediction_stats": prediction_stats(),
    }
    
    return result


if __name__ == "__main__":
    if "--oneshot" in sys.argv:
        result = oneshot()
        print(json.dumps(result, indent=2, default=str))
    else:
        main_loop()
