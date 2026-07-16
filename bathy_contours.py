#!/usr/bin/env python3
"""
bathy_contours.py -- Phase 2: Bathymetric Contour Extraction
============================================================

Streams a ~10 GB XYZ bathymetry file (~237M points, NOAA survey 71326),
grids it to 0.001deg resolution, and extracts contour polylines at
specified depth intervals using marching squares.

Depth intervals (fathoms -> metres):
    5, 10, 20, 30, 48, 60, 80, 100, 150 fm
  -> 9.144, 18.288, 36.576, 54.864, 87.782, 109.728,
    146.304, 182.88, 274.32 m

Region:  Southeast Alaska (54-59 degN, 130-138 degW)
Grid:    0.001deg  (~100 m at these latitudes)

Output:  tzpro-agent/bathymetry/contours/contours_{depth}fm.geojson
         GeoJSON FeatureCollection of LineString polylines per depth.

Design
------
- **Single-pass streaming**: reads the XYZ once to build a min-elevation
  grid (float32, ~ 160 MB), then runs marching squares in-memory on
  every depth interval.
- **Checkpoint-resumable**: line-count progress saved every 2M rows;
  interrupted runs pick up where they left off.
- **Clean output**: marching-squares line segments are joined into
  contiguous polylines; stray fragments < 5 mdeg are filtered.
"""

from __future__ import annotations

import csv
import json
import math
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

# ===========================================================================
# Constants
# ===========================================================================

LAT_MIN = 54.0
LAT_MAX = 59.0
LON_MIN = -138.0
LON_MAX = -130.0

GRID_RES = 0.001  # degrees
N_LAT = int((LAT_MAX - LAT_MIN) / GRID_RES)  # 5000
N_LON = int((LON_MAX - LON_MIN) / GRID_RES)  # 8000

FM_TO_M = 1.8288
DEPTH_INTERVALS = [(fm, fm * FM_TO_M) for fm in (5, 10, 20, 30, 48, 60, 80, 100, 150)]

XYZ_PATH = Path(r"C:\Users\casey\all\71326.xyz")
OUTPUT_DIR = Path(r"C:\Users\casey\.openclaw\workspace\tzpro-agent\bathymetry\contours")
GRID_CACHE = OUTPUT_DIR / "elevation_grid.npy"
CHECKPOINT_PATH = OUTPUT_DIR / "grid_checkpoint.json"

CHECKPOINT_EVERY = 2_000_000    # lines
MIN_POLYLINE_LEN_DEG = 0.005    # ~ 500 m
MIN_POLYLINE_POINTS = 3

# ===========================================================================
# Marching squares lookup table
# ===========================================================================
#
# Cell corners  (bit index in the 4-bit case number):
#   0 -- bottom-left   (i,   j  )
#   1 -- bottom-right  (i+1, j  )
#   2 -- top-right     (i+1, j+1)
#   3 -- top-left      (i,   j+1)
#
# Edges  (labelled by the corner indices they connect):
#   0 -- bottom  (0 -> 1)
#   1 -- right   (1 -> 2)
#   2 -- top     (3 -> 2)
#   3 -- left    (0 -> 3)
#
# Case index  = b0 + 2.b1 + 4.b2 + 8.b3
# where  bm = 1  when the corner value is >= threshold  (shallower water).
#
# Each table entry is a list of (edge_a, edge_b) pairs -- one per contour
# line segment crossing this cell.
# ---------------------------------------------------------------------------

MARCHING_SQUARES: Dict[int, List[Tuple[int, int]]] = {
    0:  [],
    1:  [(0, 3)],
    2:  [(0, 1)],
    3:  [(1, 3)],
    4:  [(1, 2)],
    5:  [(0, 3), (1, 2)],
    6:  [(0, 2)],
    7:  [(2, 3)],
    8:  [(2, 3)],
    9:  [(0, 2)],
    10: [(0, 1), (2, 3)],
    11: [(1, 2)],
    12: [(1, 3)],
    13: [(0, 1)],
    14: [(0, 3)],
    15: [],
}

# ===========================================================================
# Grid helpers
# ===========================================================================

def ij_to_latlon(i: float, j: float) -> Tuple[float, float]:
    return LAT_MIN + i * GRID_RES, LON_MIN + j * GRID_RES


def latlon_to_ij(lat: float, lon: float) -> Tuple[int, int]:
    return int((lat - LAT_MIN) / GRID_RES), int((lon - LON_MIN) / GRID_RES)


def in_roi(lat: float, lon: float) -> bool:
    return (LAT_MIN <= lat < LAT_MAX) and (LON_MIN <= lon < LON_MAX)


# ===========================================================================
# Phase 1 -- Grid building  (streaming + checkpoint)
# ===========================================================================

def load_checkpoint() -> int:
    if not CHECKPOINT_PATH.exists():
        return 0
    try:
        data = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
        return int(data.get("lines_processed", 0))
    except (json.JSONDecodeError, KeyError, ValueError):
        return 0


def save_checkpoint(lines: int) -> None:
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CHECKPOINT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps({"lines_processed": lines, "ts": time.time()}), encoding="utf-8")
    tmp.replace(CHECKPOINT_PATH)


def build_elevation_grid() -> np.ndarray:
    """Stream XYZ -> min-elevation grid.  Cache to .npy for reuse."""

    if GRID_CACHE.exists():
        grid = np.load(GRID_CACHE)
        if grid.shape == (N_LAT, N_LON):
            n_occ = int(np.sum(~np.isnan(grid)))
            print(f"[grid] Loaded cached grid  {N_LAT}x{N_LON}  "
                  f"({grid.nbytes / 1e6:.0f} MB, {n_occ:,} / {N_LAT * N_LON:,} cells)")
            return grid
        print("[grid] Cached grid shape mismatch -- rebuilding")

    grid = np.full((N_LAT, N_LON), np.nan, dtype=np.float32)
    print(f"[grid] Fresh {N_LAT}x{N_LON} float32 grid  ({grid.nbytes / 1e6:.0f} MB)")

    t0 = time.time()
    start_line = load_checkpoint()
    if start_line:
        print(f"[grid] Resuming from line {start_line:,}")

    rows_in_roi = 0

    with open(XYZ_PATH, "r", encoding="utf-8", buffering=64 * 1024 * 1024) as fh:
        reader = csv.reader(fh)
        header = next(reader)  # skip "long, lat, elevation"
        print(f"[grid] Header: {header}")

        for _ in range(start_line):
            try:
                next(reader)
            except StopIteration:
                break

        batch_t0 = time.time()
        for ix, row in enumerate(reader, start=start_line + 1):
            try:
                lon, lat, elev = float(row[0]), float(row[1]), float(row[2])
            except (ValueError, IndexError):
                continue

            if not in_roi(lat, lon):
                continue

            i, j = latlon_to_ij(lat, lon)
            if not (0 <= i < N_LAT and 0 <= j < N_LON):
                continue

            cur = grid[i, j]
            if np.isnan(cur) or elev < cur:
                grid[i, j] = elev

            rows_in_roi += 1

            if ix % CHECKPOINT_EVERY == 0:
                save_checkpoint(ix)
                dt = time.time() - batch_t0
                rate = CHECKPOINT_EVERY / dt if dt > 0 else 0
                print(f"[grid]   line {ix:>13,}   roi={rows_in_roi:>11,}   "
                      f"{rate:,.0f} r/s   delta={dt:.0f}s")
                batch_t0 = time.time()

    save_checkpoint(ix)
    elapsed = time.time() - t0
    n_occ = int(np.sum(~np.isnan(grid)))
    print(f"[grid] Done -- {ix:,} lines in {elapsed:.0f}s  ({ix / elapsed:,.0f} r/s)")
    print(f"[grid]        {rows_in_roi:,} pts in ROI  |  "
          f"{n_occ:,} / {N_LAT * N_LON:,} cells ({100 * n_occ / (N_LAT * N_LON):.1f}%)")

    np.save(GRID_CACHE, grid)
    print(f"[grid] Cached -> {GRID_CACHE}")
    return grid


# ===========================================================================
# Phase 2 -- Marching squares
# ===========================================================================

def _interp_along_edge(
    v0: float, v1: float,
    lat0: float, lat1: float,
    lon0: float, lon1: float,
    threshold: float,
) -> Tuple[float, float]:
    """Linear interpolation of (lon, lat) where value crosses *threshold*."""
    denom = v1 - v0
    if abs(denom) < 1e-12:
        return 0.5 * (lon0 + lon1), 0.5 * (lat0 + lat1)
    t = (threshold - v0) / denom
    t = max(0.0, min(1.0, t))
    return lon0 + t * (lon1 - lon0), lat0 + t * (lat1 - lat0)


def extract_contour_segments(
    grid: np.ndarray,
    threshold_m: float,
) -> List[Tuple[Tuple[float, float], Tuple[float, float]]]:
    """
    Marching squares on *grid* at elevation *threshold_m*.

    A cell is "shallow" when  grid[i,j] >= threshold_m  (elevation is
    shallower than the contour).  For bathymetry elevations are negative
    and threshold_m = -depth_m, so the 5-fm contour threshold is -9.144.

    Cells where any corner is NaN are skipped (no data -> no contour).
    """
    n_lat, n_lon = grid.shape

    # Pre-compute cell-corner lat / lon (grid point at cell centre)
    lats = np.linspace(LAT_MIN + GRID_RES / 2, LAT_MAX - GRID_RES / 2, n_lat, dtype=np.float64)
    lons = np.linspace(LON_MIN + GRID_RES / 2, LON_MAX - GRID_RES / 2, n_lon, dtype=np.float64)

    segments: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []

    ncells_i = n_lat - 1
    ncells_j = n_lon - 1
    total_cells = ncells_i * ncells_j

    for i in range(ncells_i):
        # Progress every ~10 % of rows
        if ncells_i > 10 and i % max(1, ncells_i // 10) == 0:
            pct = 100.0 * i * ncells_j / total_cells
            print(f"  [march]   row {i:>5,} / {ncells_i:,}  ({pct:.0f}%)")

        for j in range(ncells_j):
            # --- corner values and NaN check ---
            c0, c1 = grid[i, j],       grid[i + 1, j]
            c2, c3 = grid[i + 1, j + 1], grid[i, j + 1]

            if np.isnan(c0) or np.isnan(c1) or np.isnan(c2) or np.isnan(c3):
                continue

            # --- binary state for each corner ---
            b0 = 1 if c0 >= threshold_m else 0
            b1 = 1 if c1 >= threshold_m else 0
            b2 = 1 if c2 >= threshold_m else 0
            b3 = 1 if c3 >= threshold_m else 0

            case = (b0 << 0) | (b1 << 1) | (b2 << 2) | (b3 << 3)
            pairs = MARCHING_SQUARES.get(case, [])
            if not pairs:
                continue

            # --- corner lat / lon ---
            clat = [lats[i], lats[i + 1], lats[i + 1], lats[i]]
            clon = [lons[j], lons[j],     lons[j + 1], lons[j + 1]]

            for ea, eb in pairs:
                # Interpolate on edge *ea*
                # Edge endpoint indices (corner -> corner)
                a0, a1 = _edge_corners(ea)
                lon_a, lat_a = _interp_along_edge(
                    (c0, c1, c2, c3)[a0], (c0, c1, c2, c3)[a1],
                    clat[a0], clat[a1],
                    clon[a0], clon[a1],
                    threshold_m,
                )
                # Interpolate on edge *eb*
                b0, b1 = _edge_corners(eb)
                lon_b, lat_b = _interp_along_edge(
                    (c0, c1, c2, c3)[b0], (c0, c1, c2, c3)[b1],
                    clat[b0], clat[b1],
                    clon[b0], clon[b1],
                    threshold_m,
                )
                segments.append(((lon_a, lat_a), (lon_b, lat_b)))

    print(f"  [march]   {len(segments):,} raw segments extracted")
    return segments


def _edge_corners(edge_idx: int) -> Tuple[int, int]:
    """Map edge index (0-3) -> corner indices (ca, cb)."""
    return [(0, 1), (1, 2), (3, 2), (0, 3)][edge_idx]


# ===========================================================================
# Phase 3 -- Segment -> polyline joining
# ===========================================================================

_SNAP = 1e-7  # degree snap tolerance for endpoint matching


def join_segments_to_polylines(
    segments: List[Tuple[Tuple[float, float], Tuple[float, float]]],
) -> List[List[Tuple[float, float]]]:
    """
    Chain marching-squares line segments into contiguous polylines.

    1. Snap all endpoints to a fine grid -> build adjacency map
       {snapped_pt: [(seg_idx, which_end), ...]}.
    2. Greedily walk each connected component, emitting one polyline at a time.
       A junction (> 2 segments sharing an endpoint) terminates the walk.
    3. Filter polylines shorter than MIN_POLYLINE_POINTS.
    """
    if not segments:
        return []

    n = len(segments)

    # Pre-snap all endpoints
    snapped_ends: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
    adj: Dict[Tuple[float, float], List[Tuple[int, int]]] = defaultdict(list)

    for seg_idx, (p0, p1) in enumerate(segments):
        s0 = (_sn(p0[0]), _sn(p0[1]))
        s1 = (_sn(p1[0]), _sn(p1[1]))
        snapped_ends.append((s0, s1))
        adj[s0].append((seg_idx, 0))
        adj[s1].append((seg_idx, 1))

    used = [False] * n
    polylines: List[List[Tuple[float, float]]] = []

    for seed in range(n):
        if used[seed]:
            continue

        s0, s1 = snapped_ends[seed]
        # Start polyline with the seed segment
        poly: List[Tuple[float, float]] = [segments[seed][0], segments[seed][1]]
        used[seed] = True

        # Walk forward (from tail = s1)
        _walk_forward(segments, snapped_ends, adj, used, poly)
        # Walk backward (from head = s0)
        _walk_backward(segments, snapped_ends, adj, used, poly)

        if len(poly) >= MIN_POLYLINE_POINTS:
            polylines.append(poly)

    return polylines


def _sn(v: float) -> float:
    return round(v / _SNAP) * _SNAP


def _walk_forward(
    segments, snapped_ends, adj, used, poly,
) -> None:
    """Extend *poly* at its tail while a unique continuation exists."""
    while True:
        tail = poly[-1]
        key = (_sn(tail[0]), _sn(tail[1]))
        cands = adj.get(key, [])
        # Find the first unused neighbour
        next_seg = None
        for si, ep in cands:
            if not used[si]:
                next_seg = (si, ep)
                break
        if next_seg is None:
            return
        si, ep = next_seg
        used[si] = True
        # Add the *other* endpoint of the neighbour
        poly.append(segments[si][1] if ep == 0 else segments[si][0])


def _walk_backward(
    segments, snapped_ends, adj, used, poly,
) -> None:
    """Prepend to *poly* at its head while a unique continuation exists."""
    while True:
        head = poly[0]
        key = (_sn(head[0]), _sn(head[1]))
        cands = adj.get(key, [])
        next_seg = None
        for si, ep in cands:
            if not used[si]:
                next_seg = (si, ep)
                break
        if next_seg is None:
            return
        si, ep = next_seg
        used[si] = True
        poly.insert(0, segments[si][0] if ep == 0 else segments[si][1])


# ===========================================================================
# Phase 4 -- GeoJSON export
# ===========================================================================

def polylines_to_geojson(
    polylines: List[List[Tuple[float, float]]],
    depth_fm: int,
    depth_m: float,
) -> dict:
    features = []
    for idx, poly in enumerate(polylines):
        features.append({
            "type": "Feature",
            "properties": {
                "depth_fm": depth_fm,
                "depth_m": round(depth_m, 3),
                "segment_id": idx,
            },
            "geometry": {
                "type": "LineString",
                "coordinates": [[lon, lat] for lon, lat in poly],
            },
        })
    return {
        "type": "FeatureCollection",
        "properties": {
            "depth_fm": depth_fm,
            "depth_m": round(depth_m, 3),
            "region": (f"SE Alaska {LAT_MIN}-{LAT_MAX}degN, "
                       f"{abs(LON_MIN)}-{abs(LON_MAX)}degW"),
            "grid_resolution_deg": GRID_RES,
            "polyline_count": len(features),
        },
        "features": features,
    }


def polyline_length_deg(poly: List[Tuple[float, float]]) -> float:
    """Euclidean length in degrees (cheap; good enough for filtering)."""
    total = 0.0
    for (x0, y0), (x1, y1) in zip(poly, poly[1:]):
        total += math.hypot(x1 - x0, y1 - y0)
    return total


# ===========================================================================
# Main
# ===========================================================================

def main() -> None:
    print("=" * 68)
    print("  bathy_contours.py -- Phase 2 Contour Extraction")
    print("=" * 68)
    print(f"  ROI:       {LAT_MIN}-{LAT_MAX}degN, {abs(LON_MIN)}-{abs(LON_MAX)}degW")
    print(f"  Grid:      {N_LAT} x {N_LON} cells @ {GRID_RES}deg")
    print(f"  XYZ:       {XYZ_PATH}")
    print(f"  Output:    {OUTPUT_DIR}/")
    depths_str = ", ".join(f"{fm}fm" for fm, _ in DEPTH_INTERVALS)
    print(f"  Depths:    {depths_str}")
    print()

    # -- Phase 1: grid --------------------------------------------------
    print("-" * 50)
    print("  Phase 1 -- Build / load elevation grid")
    print("-" * 50)
    t0 = time.time()
    grid = build_elevation_grid()
    print(f"  Grid ready  ({time.time() - t0:.0f}s)\n")

    # Quick stats
    valid = grid[~np.isnan(grid)]
    print(f"  Grid stats:  min={np.min(valid):.1f}m  max={np.max(valid):.1f}m  "
          f"median={np.median(valid):.1f}m")
    for fm, dm in DEPTH_INTERVALS:
        n_shallow = int(np.sum(valid >= -dm))
        print(f"    <= {fm:>3}fm  ({-dm:>8.2f}m):  {n_shallow:>10,} shallow cells  "
              f"({100 * n_shallow / valid.size:.1f}%)")
    print()

    # -- Phase 2: contours ----------------------------------------------
    print("-" * 50)
    print("  Phase 2 -- Marching squares + polyline joining")
    print("-" * 50)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    grand_total = time.time()

    for depth_fm, depth_m in DEPTH_INTERVALS:
        thr = -depth_m
        label = f"{depth_fm}fm ({depth_m:.3f}m)"
        print(f"\n  >> {label}   threshold = {thr:.3f} m")

        t1 = time.time()

        # Marching squares
        segs = extract_contour_segments(grid, thr)
        if not segs:
            print(f"     ! No contour at {label} -- skipping")
            continue
        print(f"     {len(segs):,} segments  ({time.time() - t1:.1f}s)")

        # Join -> polylines
        t2 = time.time()
        polys = join_segments_to_polylines(segs)
        n_raw = len(polys)

        # Filter short fragments
        polys = [p for p in polys if polyline_length_deg(p) >= MIN_POLYLINE_LEN_DEG]
        n_filt = n_raw - len(polys)
        print(f"     {n_raw:,} polylines joined, {n_filt} short filtered "
              f"-> {len(polys):,} kept  ({time.time() - t2:.1f}s)")

        # Total points in kept polylines
        total_pts = sum(len(p) for p in polys)
        print(f"     {total_pts:,} vertices across {len(polys):,} polylines")

        # Export
        geojson = polylines_to_geojson(polys, depth_fm, depth_m)
        out_path = OUTPUT_DIR / f"contours_{depth_fm}fm.geojson"
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(geojson, fh, indent=None, separators=(",", ":"))
        mb = out_path.stat().st_size / 1e6
        print(f"     -> {out_path.name}  ({mb:.1f} MB)  "
              f"[{time.time() - t1:.1f}s total]")

    # -- Summary --------------------------------------------------------
    elapsed = time.time() - grand_total
    print(f"\n{'=' * 68}")
    print(f"  Done -- total: {elapsed:.0f}s  ({elapsed / 60:.1f} min)")
    print(f"  Output directory:  {OUTPUT_DIR}")
    for p in sorted(OUTPUT_DIR.glob("contours_*fm.geojson")):
        print(f"    {p.name:32s} {p.stat().st_size / 1e6:8.1f} MB")
    print(f"{'=' * 68}")


if __name__ == "__main__":
    main()
