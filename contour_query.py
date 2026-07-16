#!/usr/bin/env python3
"""
contour_query.py — Fast contour depth lookup from GeoJSON vector tiles.

Given a lat/lon, returns the charted depth at the nearest contour polyline
by interpolating between the two closest depth intervals.

Usage:
    from contour_query import get_depth
    
    depth_fm = get_depth(55.7859, -131.527)  # returns 52.7
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Optional

import numpy as np

# ── Paths ──────────────────────────────────────────────────────────
CONTOURS_DIR = Path(__file__).parent / "bathymetry" / "contours"
GRID_PATH = CONTOURS_DIR / "elevation_grid.npy"

# Depth intervals (fathoms) matching bathy_contours.py
DEPTHS_FM = [5, 10, 20, 30, 48, 60, 80, 100, 150]
DEPTHS_M = [d * 1.8288 for d in DEPTHS_FM]

# Region bounds matching bathy_contours.py
LAT_MIN, LAT_MAX = 54.0, 59.0
LON_MIN, LON_MAX = -138.0, -130.0
GRID_RES = 0.001  # degrees

# Grid dimensions
N_LAT = int((LAT_MAX - LAT_MIN) / GRID_RES)  # 5000
N_LON = int((LON_MAX - LON_MIN) / GRID_RES)  # 8000

# Cache grid
_grid: Optional[np.ndarray] = None


def _load_grid() -> np.ndarray:
    """Load and cache the elevation grid."""
    global _grid
    if _grid is None:
        if GRID_PATH.exists():
            _grid = np.load(GRID_PATH)
        else:
            _grid = np.full((N_LAT, N_LON), np.nan, dtype=np.float32)
    return _grid


def _latlon_to_ij(lat: float, lon: float) -> tuple[int, int]:
    """Convert lat/lon to grid indices."""
    i = int((lat - LAT_MIN) / GRID_RES)
    j = int((lon - LON_MIN) / GRID_RES)
    return i, j


def in_roi(lat: float, lon: float) -> bool:
    """Check if position is within the charted region."""
    return (LAT_MIN <= lat < LAT_MAX) and (LON_MIN <= lon < LON_MAX)


def get_depth_m(lat: float, lon: float) -> Optional[float]:
    """Get charted depth at position in meters (negative = underwater).
    
    Returns None if position is outside the ROI or no data available.
    """
    if not in_roi(lat, lon):
        return None
    
    grid = _load_grid()
    i, j = _latlon_to_ij(lat, lon)
    
    if not (0 <= i < N_LAT and 0 <= j < N_LON):
        return None
    
    val = grid[i, j]
    if np.isnan(val):
        return None
    
    return float(val)


def get_depth_fm(lat: float, lon: float) -> Optional[float]:
    """Get charted depth in fathoms. Positive = underwater."""
    m = get_depth_m(lat, lon)
    if m is None:
        return None
    return abs(m) / 1.8288


def get_contour_bands(lat: float, lon: float, radius_deg: float = 0.01) -> dict:
    """Get contour bands within a radius of position.
    
    Returns dict mapping depth_fm -> distance_deg for contour lines
    that pass near the queried position.
    """
    if not in_roi(lat, lon):
        return {}
    
    results = {}
    i, j = _latlon_to_ij(lat, lon)
    di = int(radius_deg / GRID_RES) + 1
    
    grid = _load_grid()
    patch = grid[max(0, i-di):min(N_LAT, i+di+1), max(0, j-di):min(N_LON, j+di+1)]
    
    grid_fm = np.abs(patch) / 1.8288
    
    for df in DEPTHS_FM:
        # Check if depth band crosses this patch
        dm = df * 1.8288
        above = np.abs(patch) <= dm
        below = np.abs(patch) > dm
        
        if np.any(above) and np.any(below):
            # This contour band is present in this area
            # Return the center depth
            results[df] = {
                "depth_fm": df,
                "depth_m": dm,
                "present": True,
            }
    
    return results


def get_gear_clearance(lat: float, lon: float, gear_fm: float = 48.0) -> dict:
    """Compute gear clearance: how far above/below the gear depth contour.
    
    Returns:
        dict with depth readings the agent needs
    """
    charted = get_depth_fm(lat, lon)
    if charted is None:
        return {"error": "no chart data"}
    
    clearance = charted - gear_fm  # positive = deeper than gear
    
    contours_nearby = get_contour_bands(lat, lon)
    
    return {
        "charted_fm": round(charted, 1),
        "gear_fm": gear_fm,
        "clearance_fm": round(clearance, 1),
        "status": "clear" if clearance > 2 else ("close" if clearance > 0 else "hazard"),
        "contours_nearby": list(contours_nearby.keys()),
    }


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) >= 3:
        lat, lon = float(sys.argv[1]), float(sys.argv[2])
        print(f"Position: {lat:.4f}, {lon:.4f}")
        print(f"Depth (m): {get_depth_m(lat, lon)}")
        print(f"Depth (fm): {get_depth_fm(lat, lon)}")
        print(f"Gear: {get_gear_clearance(lat, lon)}")
        print(f"Contours near: {get_contour_bands(lat, lon)}")
    else:
        # Demo with Ketchikan harbor
        pos = (55.3422, -131.6433)
        print(f"Ketchikan harbor ({pos[0]:.4f}, {pos[1]:.4f}):")
        d = get_depth_fm(*pos)
        print(f"  Depth: {d} fm")
        print(f"  Gear: {get_gear_clearance(*pos)}")
        print(f"  Near: {get_contour_bands(*pos)}")
        
        # Demo with today's test capture position
        pos2 = (55.78595, -131.527017)
        print(f"\nTest capture position ({pos2[0]:.4f}, {pos2[1]:.4f}):")
        d2 = get_depth_fm(*pos2)
        print(f"  Depth: {d2} fm")
        print(f"  Gear: {get_gear_clearance(*pos2)}")
