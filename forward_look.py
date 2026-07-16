#!/usr/bin/env python3
"""
forward_look.py — Predictive depth profile from survey data.

Given current position, heading, and speed, projects ahead along the
vessel's track and queries the contour grid at regular intervals.

Returns:
  - Depth profile ahead (position, depth, contour crossings)
  - Distance to nearest gear-depth contour (48 fm / configurable)
  - Predicted depth at vessel position (for comparison with real sounder)
  - Alerts for upcoming contour crossings

Synergy with anomaly_logger:
  When the vessel reaches a predicted position, the prediction is compared
  against the real sounder reading. Systematic prediction errors become
  map corrections — same as anomaly_logger, but proactive.

Usage:
    from forward_look import predict_ahead, look_for_contour_crossings
    
    profile = predict_ahead(55.7859, -131.527, heading=180, sog=6.0)
    crossings = look_for_contour_crossings(profile, target_fm=48)
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Optional

import numpy as np

# Local
from contour_query import get_depth_fm, get_gear_clearance, DEPTHS_FM, CONTOURS_DIR

# ── Constants ──────────────────────────────────────────────────────
# Earth radius in meters
R_EARTH = 6371000.0

# Default projection distances (meters ahead)
DEFAULT_DISTANCES_M = [50, 100, 200, 300, 500, 750, 1000, 1500, 2000]

# Log file for prediction → reality comparisons
PREDICTION_LOG = CONTOURS_DIR.parent / "prediction_log.csv"


def _project_position(
    lat: float, lon: float, bearing_deg: float, distance_m: float
) -> tuple[float, float]:
    """Project a position forward along a bearing.
    
    Uses haversine formula. Accurate for distances up to ~100 km.
    
    Args:
        lat: Starting latitude (decimal degrees)
        lon: Starting longitude (decimal degrees)
        bearing_deg: Bearing in degrees (0 = north, 90 = east, 180 = south)
        distance_m: Distance to project in meters
    
    Returns:
        (lat, lon) of projected position
    """
    lat_r = math.radians(lat)
    lon_r = math.radians(lon)
    bearing_r = math.radians(bearing_deg)
    
    angular_dist = distance_m / R_EARTH
    
    new_lat_r = math.asin(
        math.sin(lat_r) * math.cos(angular_dist)
        + math.cos(lat_r) * math.sin(angular_dist) * math.cos(bearing_r)
    )
    
    new_lon_r = lon_r + math.atan2(
        math.sin(bearing_r) * math.sin(angular_dist) * math.cos(lat_r),
        math.cos(angular_dist) - math.sin(lat_r) * math.sin(new_lat_r),
    )
    
    return (math.degrees(new_lat_r), math.degrees(new_lon_r))


def predict_ahead(
    lat: float,
    lon: float,
    heading: float,
    sog: float,
    distances: Optional[list[float]] = None,
    gear_fm: float = 48.0,
) -> dict:
    """Generate depth profile ahead of vessel.
    
    Args:
        lat: Current latitude
        lon: Current longitude
        heading: Current heading in degrees (0 = north)
        sog: Speed over ground in knots
        distances: Distances to project (meters). Defaults to DEFAULT_DISTANCES_M.
        gear_fm: Gear depth for clearance calculation
    
    Returns:
        Dict with profile, alerts, and current state
    """
    if distances is None:
        distances = DEFAULT_DISTANCES_M
    
    # Current depth at vessel position
    current_depth = get_depth_fm(lat, lon)
    if current_depth is None:
        return {
            "error": "Position outside charted region",
            "lat": lat,
            "lon": lon,
        }
    
    # Project forward at each distance
    profile = []
    contour_crossings = []
    prev_segment_above = current_depth < gear_fm
    
    for dist_m in distances:
        proj_lat, proj_lon = _project_position(lat, lon, heading, dist_m)
        depth = get_depth_fm(proj_lat, proj_lon)
        
        if depth is not None:
            profile.append({
                "distance_m": dist_m,
                "distance_nm": round(dist_m / 1852, 3),
                "lat": round(proj_lat, 6),
                "lon": round(proj_lon, 6),
                "depth_fm": round(depth, 1),
                "gear_clearance_fm": round(depth - gear_fm, 1),
                "time_to_reach_s": round(dist_m / (sog * 0.514444)) if sog > 0 else None,
            })
            
            # Detect contour crossings
            segment_above = depth < gear_fm
            if prev_segment_above != segment_above:
                # Crossed the gear contour
                crossing_dist = dist_m
                crossing_time = dist_m / (sog * 0.514444) if sog > 0 else None
                contour_crossings.append({
                    "contour_fm": gear_fm,
                    "crossing_distance_m": crossing_dist,
                    "crossing_distance_nm": round(crossing_dist / 1852, 3),
                    "time_to_crossing_s": round(crossing_time) if crossing_time else None,
                    "direction": "crossing_shoaler" if segment_above else "crossing_deeper",
                })
            prev_segment_above = segment_above
            
            # Also check other contour bands
            for cf in DEPTHS_FM:
                if cf == gear_fm:
                    continue
                above = depth < cf
                if prev_segment_above != above:
                    contour_crossings.append({
                        "contour_fm": cf,
                        "crossing_distance_m": dist_m,
                        "crossing_distance_nm": round(dist_m / 1852, 3),
                        "direction": "crossing_shoaler" if above else "crossing_deeper",
                    })
    
    # Generate alerts
    alerts = []
    for crossing in contour_crossings:
        cf = crossing["contour_fm"]
        dist = crossing["crossing_distance_nm"]
        direction = crossing["direction"]
        
        if cf == gear_fm:
            alerts.append({
                "severity": "warning",
                "message": f"Will cross gear contour ({gear_fm} fm) in {dist:.2f} nm",
                "distance_nm": dist,
                "contour_fm": cf,
            })
        elif cf == 5 and direction == "crossing_shoaler":
            alerts.append({
                "severity": "critical",
                "message": f"Will cross anchor-safe contour (5 fm) in {dist:.2f} nm — GROUNDING HAZARD",
                "distance_nm": dist,
                "contour_fm": cf,
            })
    
    # Time to nearest contour crossing
    nearest_crossing = contour_crossings[0] if contour_crossings else None
    
    return {
        "vessel": {
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "heading": heading,
            "sog_knots": sog,
        },
        "current": {
            "depth_fm": round(current_depth, 1),
            "gear_clearance_fm": round(current_depth - gear_fm, 1),
        },
        "profile": profile,
        "contour_crossings": contour_crossings,
        "alerts": alerts,
        "nearest_crossing": nearest_crossing,
        "timestamp": time.time(),
    }


def look_for_contour_crossings(
    profile: dict, target_fm: float = 48.0
) -> list[dict]:
    """Extract specifically gear/anchor contour crossings from a profile.
    
    Shorthand for checking if the vessel will cross critical depth bands.
    """
    if "error" in profile:
        return []
    
    crossings = profile.get("contour_crossings", [])
    return [c for c in crossings if c["contour_fm"] in (target_fm, 5, 10)]


def log_prediction(lat: float, lon: float, heading: float, sog: float, 
                   actual_depth_fm: float, prediction: dict) -> None:
    """Log a forward-look prediction alongside the actual sounder reading.
    
    This is the synergy point: when the vessel reaches a position that was
    previously predicted, the actual depth is compared against the prediction.
    Systematic errors → map corrections (fed back to anomaly_logger).
    """
    import csv
    from datetime import datetime, timezone
    
    # Get the predicted depth at the nearest distance
    profile = prediction.get("profile", [])
    expected_depth = profile[0]["depth_fm"] if profile else None
    
    delta = actual_depth_fm - expected_depth if expected_depth else None
    
    file_exists = PREDICTION_LOG.exists()
    
    with open(PREDICTION_LOG, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "ts", "lat", "lon", "heading", "sog",
                "predicted_fm", "actual_fm", "delta_fm",
            ])
        writer.writerow([
            datetime.now(timezone.utc).isoformat(),
            round(lat, 6), round(lon, 6),
            heading, sog,
            expected_depth, actual_depth_fm,
            round(delta, 2) if delta is not None else "",
        ])


def prediction_stats() -> dict:
    """Show prediction accuracy statistics from the log."""
    if not PREDICTION_LOG.exists():
        return {"total": 0}
    
    import csv
    deltas = []
    with open(PREDICTION_LOG) as f:
        reader = csv.DictReader(f)
        for row in reader:
            d = row.get("delta_fm", "")
            if d:
                deltas.append(float(d))
    
    if not deltas:
        return {"total_logged": len(deltas)}
    
    arr = np.array(deltas)
    return {
        "total_logged": len(arr),
        "mean_error_fm": round(float(arr.mean()), 2),
        "std_error_fm": round(float(arr.std()), 2),
        "max_underestimate_fm": round(float(arr.min()), 2),
        "max_overestimate_fm": round(float(arr.max()), 2),
        "rms_error_fm": round(float(np.sqrt(np.mean(arr**2))), 2),
    }


def find_safe_heading(
    lat: float,
    lon: float,
    sog: float,
    step_m: float = 50.0,
    max_look_m: float = 5000.0,
    gear_fm: float = 48.0,
) -> dict:
    """Find safest heading from 8 cardinal directions.

    For each cardinal heading (N, NE, E, SE, S, SW, W, NW), projects
    forward in steps and finds the distance to the gear contour crossing.
    Returns the heading with the MOST clearance — i.e., the furthest
    distance before the gear contour is crossed (or the quickest exit
    if currently inside the contour).

    Args:
        lat: Current latitude
        lon: Current longitude
        sog: Speed over ground in knots
        step_m: Step size in meters between depth checks (default 50)
        max_look_m: Maximum look-ahead distance in meters (default 5000)
        gear_fm: Gear depth contour (default 48 fm)

    Returns:
        Dict with:
          - vessel: Current position and SOG
          - current_depth_fm: Depth at current position
          - inside_contour: Whether vessel is inside gear contour
          - best_heading: Heading (deg) with most clearance
          - best_label: Cardinal label for best heading
          - best_distance_m: Distance to contour on best heading
          - best_distance_nm: Distance in nautical miles
          - headings: List of per-heading results
          - timestamp: Unix time
    """
    HEADING_LABELS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    HEADING_DEGREES = [0, 45, 90, 135, 180, 225, 270, 315]

    current_depth = get_depth_fm(lat, lon)
    if current_depth is None:
        return {
            "error": "Position outside charted region",
            "lat": lat,
            "lon": lon,
        }

    inside_contour = current_depth < gear_fm

    results = []
    for hdg, label in zip(HEADING_DEGREES, HEADING_LABELS):
        dist_m = step_m
        crossing_found = False
        prev_depth = current_depth

        while dist_m <= max_look_m + 0.001:
            proj_lat, proj_lon = _project_position(lat, lon, hdg, dist_m)
            depth = get_depth_fm(proj_lat, proj_lon)

            if depth is None:
                # Left charted area — treat as no crossing found
                break

            if inside_contour:
                # Looking for exit to deep water (depth >= gear_fm)
                if prev_depth < gear_fm <= depth:
                    crossing_found = True
                    break
            else:
                # Looking for entry to shallow water (depth <= gear_fm)
                if prev_depth >= gear_fm and depth < gear_fm:
                    crossing_found = True
                    break

            prev_depth = depth
            dist_m += step_m

        results.append({
            "heading": hdg,
            "label": label,
            "distance_m": round(dist_m, 1) if crossing_found else None,
            "distance_nm": round(dist_m / 1852.0, 3) if crossing_found else None,
            "crossing_found": crossing_found,
            "beyond_max": not crossing_found and dist_m > max_look_m,
        })

    # Sort by clearance: if outside contour, most clearance = furthest to contour;
    # if inside contour, most clearance = shortest path back to contour (exit)
    if inside_contour:
        # Shorter distance to exit is better
        sorted_results = sorted(
            results,
            key=lambda r: r["distance_m"] if r.get("crossing_found") else float("inf"),
        )
        best = sorted_results[0] if sorted_results else None
    else:
        # Longer distance to contour is better
        sorted_results = sorted(
            results,
            key=lambda r: r["distance_m"] if r.get("crossing_found") else -1.0,
        )
        best = sorted_results[-1] if sorted_results else None

    return {
        "vessel": {
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "sog_knots": sog,
        },
        "current_depth_fm": round(current_depth, 1),
        "inside_contour": inside_contour,
        "best_heading": best["heading"],
        "best_label": best["label"],
        "best_distance_m": best.get("distance_m"),
        "best_distance_nm": best.get("distance_nm"),
        "headings": results,
        "timestamp": time.time(),
    }


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) >= 4:
        lat, lon = float(sys.argv[1]), float(sys.argv[2])
        hdg, sog = float(sys.argv[3]), float(sys.argv[4]) if len(sys.argv) > 4 else 0.0
    else:
        # Default: Ketchikan harbor, heading east at 6 kts
        lat, lon, hdg, sog = 55.3422, -131.6433, 90, 6.0
    
    result = predict_ahead(lat, lon, hdg, sog)
    
    print(f"=== Forward Look ===")
    print(f"Position: {lat:.4f}, {lon:.4f}  Heading: {hdg}°  SOG: {sog} kts")
    print(f"Current depth: {result.get('current', {}).get('depth_fm', 'N/A')} fm")
    print(f"Gear clearance: {result.get('current', {}).get('gear_clearance_fm', 'N/A')} fm")
    print()
    
    if "error" in result:
        print(f"ERROR: {result['error']}")
        sys.exit(1)
    
    print(f"{'Dist(m)':>8} {'Dist(nm)':>8} {'Depth(fm)':>10} {'Clear':>8} {'Time':>8}")
    print("-" * 50)
    for p in result["profile"]:
        t = p.get("time_to_reach_s")
        t_str = f"{t}s" if t else "—"
        print(f"{p['distance_m']:>8} {p['distance_nm']:>8.2f} {p['depth_fm']:>8.1f} {p['gear_clearance_fm']:>+7.1f} {t_str:>8}")
    
    print()
    if result["alerts"]:
        print("ALERTS:")
        for a in result["alerts"]:
            print(f"  [{a['severity'].upper()}] {a['message']}")
    else:
        print("No contour crossing alerts")
    
    # Show stats if there are logged predictions
    stats = prediction_stats()
    if stats["total"]:
        print(f"\nPrediction accuracy (logged): n={stats['total_logged']}, "
              f"mean error={stats['mean_error_fm']} fm, "
              f"RMS={stats['rms_error_fm']} fm")
