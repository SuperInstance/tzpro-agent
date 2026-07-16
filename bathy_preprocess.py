#!/usr/bin/env python3
"""
bathy_preprocess.py — Phase 1: Scan and index the XYZ bathymetry archive.

Builds a spatial index of the 237M sounding points, extracts key statistics,
and prepares for contour extraction at user-specified depth intervals.

Usage:
    python bathy_preprocess.py [--sample N] [--grid-size M]
"""

import csv
import json
import math
import os
import sys
import time
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────
XYZ_PATH = Path(r"C:\Users\casey\all\71326.xyz")
WORKSPACE = Path(__file__).parent.resolve()
BATHY_DIR = WORKSPACE / "bathymetry"
BATHY_DIR.mkdir(exist_ok=True)

# Captain's known depth intervals (from OpenCPN/TZ Pro config)
INTEREST_DEPTHS_FM = [5, 10, 20, 30, 48, 60, 80, 100, 150]
INTEREST_DEPTHS_M = [d * 1.8288 for d in INTEREST_DEPTHS_FM]  # fathoms to meters

# Sampling strategy: scan in chunks, build quadtree stats
GRID_DEGREES = 0.1  # ~11 km cells for initial index
SCAN_CHUNK = 500_000  # rows per progress update


def scan_xyz(path: Path, grid_deg: float = GRID_DEGREES):
    """Fast first pass: get bounds, depth range, and grid occupancy stats."""
    print(f"Scanning {path}")
    print(f"Grid cell size: {grid_deg}° ({grid_deg*111:.0f} km)")
    print()

    fsize = path.stat().st_size
    print(f"File size: {fsize/1024**3:.1f} GB")

    # Statistics accumulators
    min_lat = max_lat = min_lon = max_lon = None
    min_depth = max_depth = None
    total_points = 0
    depth_buckets = {d: 0 for d in INTEREST_DEPTHS_FM}  # count points near each depth

    # Grid occupancy: dict of (lon_idx, lat_idx) -> point_count
    grid_cells: dict[tuple[int, int], int] = {}
    grid_counts: dict[tuple[int, int], dict] = {}  # per-cell depth stats

    start = time.time()
    last_report = start

    with open(path, 'r', newline='', encoding='ascii') as f:
        reader = csv.reader(f)
        header = next(reader)
        print(f"Header: {header}")
        print()

        for i, row in enumerate(reader, 1):
            try:
                lon = float(row[0])
                lat = float(row[1])
                depth = float(row[2])  # negative = underwater
            except (ValueError, IndexError):
                continue

            # Update global bounds
            if min_lat is None:
                min_lat = max_lat = lat
                min_lon = max_lon = lon
                min_depth = max_depth = depth
            else:
                if lat < min_lat: min_lat = lat
                if lat > max_lat: max_lat = lat
                if lon < min_lon: min_lon = lon
                if lon > max_lon: max_lon = lon
                if depth < min_depth: min_depth = depth
                if depth > max_depth: max_depth = depth

            # Update grid occupancy
            gx = int(math.floor(lon / grid_deg))
            gy = int(math.floor(lat / grid_deg))
            key = (gx, gy)
            if key not in grid_cells:
                grid_cells[key] = 0
                grid_counts[key] = {"min": depth, "max": depth, "count": 0}
            grid_cells[key] += 1
            gc = grid_counts[key]
            gc["count"] += 1
            if depth < gc["min"]: gc["min"] = depth
            if depth > gc["max"]: gc["max"] = depth

            # Depth band proximity (within 5m of interest depth)
            depth_abs = abs(depth)
            for df, dm in zip(INTEREST_DEPTHS_FM, INTEREST_DEPTHS_M):
                if abs(depth_abs - dm) < 2.5:  # within 2.5m
                    depth_buckets[df] += 1

            total_points = i
            if i % SCAN_CHUNK == 0:
                now = time.time()
                rate = SCAN_CHUNK / (now - last_report)
                mb_processed = (fsize * i / 236817592) / (1024*1024)
                print(f"  {i:>10,} rows — {rate:,.0f} rows/sec", flush=True)
                last_report = now

    elapsed = time.time() - start
    print()
    print(f"=== SCAN COMPLETE ===")
    print(f"Total points: {total_points:,}")
    print(f"Time: {elapsed:.0f}s ({total_points/elapsed:,.0f} pts/sec)")
    print(f"Lat range: {min_lat:.6f} to {max_lat:.6f}")
    print(f"Lon range: {min_lon:.6f} to {max_lon:.6f}")
    print(f"Depth range: {min_depth:.1f}m to {max_depth:.1f}m")
    print(f"Non-empty grid cells: {len(grid_cells):,}")

    # Depth band proximity summary
    print(f"\nDepth band proximity (±2.5m of target):")
    for df in INTEREST_DEPTHS_FM:
        dm = df * 1.8288
        pct = (depth_buckets[df] / total_points) * 100 if total_points else 0
        print(f"  {df:>3} fm ({dm:5.1f}m): {depth_buckets[df]:>8,} pts ({pct:.2f}%)")

    # Save metadata
    meta = {
        "total_points": total_points,
        "lat_min": min_lat,
        "lat_max": max_lat,
        "lon_min": min_lon,
        "lon_max": max_lon,
        "depth_min_m": min_depth,
        "depth_max_m": max_depth,
        "grid_deg": grid_deg,
        "grid_cells_occupied": len(grid_cells),
        "interest_depths_fm": INTEREST_DEPTHS_FM,
        "depth_band_counts": depth_buckets,
        "elapsed_seconds": elapsed,
    }
    meta_path = BATHY_DIR / "scan_metadata.json"
    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=2)
    print(f"\nMetadata saved to {meta_path}")

    # Save grid occupancy (top N cells by point density)
    sorted_cells = sorted(grid_cells.items(), key=lambda x: -x[1])
    top_cells = []
    for (gx, gy), count in sorted_cells[:100]:
        lon_center = (gx + 0.5) * grid_deg
        lat_center = (gy + 0.5) * grid_deg
        gc = grid_counts[(gx, gy)]
        top_cells.append({
            "cell": f"{gx},{gy}",
            "lon_center": round(lon_center, 4),
            "lat_center": round(lat_center, 4),
            "points": count,
            "depth_min_m": round(gc["min"], 1),
            "depth_max_m": round(gc["max"], 1),
        })
    cells_path = BATHY_DIR / "top_grid_cells.json"
    with open(cells_path, 'w') as f:
        json.dump(top_cells, f, indent=2)
    print(f"Top-100 grid cells saved to {cells_path}")

    return meta


if __name__ == "__main__":
    print("="*60)
    print("BATHYMETRY PREPROCESSOR — Phase 1: Scan & Index")
    print("="*60)
    print()

    meta = scan_xyz(XYZ_PATH)

    print()
    print("Phase 1 complete. Next: Phase 2 — Contour extraction + ENC download.")
    print(f"Working directory: {BATHY_DIR}")
