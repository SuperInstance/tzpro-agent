#!/usr/bin/env python3
"""analyzer.py — Echogram analysis watcher for the tzpro-agent pipeline.

Watches captures/v3/ for new .png files, runs computer-vision analysis on
the dual-band fish finder display, and records results alongside the capture.

Requirements: opencv-python-headless, numpy

Display layout (full-frame 1920x1080):
  LF band:   x=8..945   (~937px)
  HF band:   x=950..1890 (~940px)
  Divider:   x=945 (white vertical)
  Depth scale strip on right edge of HF band: x≈1870-1890
  Range: 60 fm → 18 px/fathom
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

# Phase 5: Vocabulary integration
from vocabulary import annotate_blobs, aggregate_vocabulary

# Phase 8: School behavior classification
from school_state import classify_school

# ── Config ─────────────────────────────────────────────────────────
CAPTURES_DIR = Path(__file__).parent.resolve() / "captures" / "v3"
SHIP_LOG_URL = "https://ship-log-search.casey-digennaro.workers.dev/api/log"
SHIP_LOG_TIMEOUT_S = 5
SCAN_INTERVAL_S = 60
DEPTH_MAX_FM = 60
PX_PER_FM = 1080.0 / DEPTH_MAX_FM  # 18.0

# Band crop regions (x offsets on 1920-wide frame)
LF_X_START = 8
LF_X_END = 945
HF_X_START = 950
HF_X_END = 1890

# Depth zones in pixel rows at 18 px/fm
#   Surface:  0-5   fm  → rows   0-90
#   Upper:    5-20  fm  → rows  90-360
#   Mid:     20-40  fm  → rows 360-720   (target chum zone)
#   Lower:   40-55  fm  → rows 720-990
#   Floor:   55-60  fm  → rows 990-1080
ZONES: dict[str, tuple[int, int]] = {
    "surface": (0, 90),
    "upper": (90, 360),
    "mid": (360, 720),
    "lower": (720, 990),
    "floor": (990, 1080),
}

# Blob detection
BLOB_MIN_SIZE_PX = 50
INTENSITY_THRESHOLD = 50  # grayscale threshold for signal vs background

ANALYZED_SCHEMA_VERSION = 3

LOCAL_TZ = timezone(timedelta(hours=-8))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("analyzer")


# ══════════════════════════════════════════════════════════════════════
#  Band Crop
# ══════════════════════════════════════════════════════════════════════

def crop_bands(img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Crop LF (left) and HF (right) bands from full 1920x1080 BGR frame."""
    lf = img[0:1080, LF_X_START:LF_X_END]
    hf = img[0:1080, HF_X_START:HF_X_END]
    return lf, hf


# ══════════════════════════════════════════════════════════════════════
#  Depth Zone Profile
# ══════════════════════════════════════════════════════════════════════

def depth_zone_profile(
    band: np.ndarray, zone_name: str, y_start: int, y_end: int,
) -> dict:
    """Compute per-depth-zone metrics from a BGR band crop.

    Converts to grayscale, computes per-column then per-zone aggregate:
    mean_intensity, peak_intensity, variance, pixel_count_above_threshold.
    """
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    zone = gray[y_start:y_end, :]
    if zone.size == 0:
        return {
            "zone": zone_name,
            "depth_range_fm": (
                round(y_start / PX_PER_FM, 1),
                round(y_end / PX_PER_FM, 1),
            ),
            "mean_intensity": 0.0,
            "peak_intensity": 0.0,
            "variance": 0.0,
            "pixel_count_above_threshold": 0,
        }

    flat = zone.ravel()
    return {
        "zone": zone_name,
        "depth_range_fm": (
            round(y_start / PX_PER_FM, 1),
            round(y_end / PX_PER_FM, 1),
        ),
        "mean_intensity": float(flat.mean()),
        "peak_intensity": int(flat.max()),
        "variance": float(flat.var()),
        "pixel_count_above_threshold": int((flat > INTENSITY_THRESHOLD).sum()),
    }


# ══════════════════════════════════════════════════════════════════════
#  Column Delta Analysis
# ══════════════════════════════════════════════════════════════════════

def column_delta(band: np.ndarray) -> dict:
    """Compare leftmost 5% vs rightmost 5% of columns per depth zone.

    The visible window is ~14 min of scrolling history. Captures happen
    every 10 min, so the left edge is ~4 min older than the previous
    capture's right edge — this reveals temporal change between frames.
    """
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    w = gray.shape[1]
    take = max(1, w // 20)  # 5%

    left_cols = gray[:, :take]
    right_cols = gray[:, w - take :]

    deltas: dict = {}
    for zone_name, (y_start, y_end) in ZONES.items():
        lz = left_cols[y_start:y_end, :]
        rz = right_cols[y_start:y_end, :]
        if lz.size == 0 or rz.size == 0:
            deltas[zone_name] = None
            continue
        lm = float(lz.mean())
        rm = float(rz.mean())
        deltas[zone_name] = {
            "left_mean": round(lm, 1),
            "right_mean": round(rm, 1),
            "delta": round(rm - lm, 1),
        }
    return deltas


# ══════════════════════════════════════════════════════════════════════
#  Blob Detection (echo returns)
# ══════════════════════════════════════════════════════════════════════

def detect_blobs(band: np.ndarray) -> list[dict]:
    """Detect significant echo returns via connected components.

    Steps:
      1. Convert to grayscale.
      2. Adaptive threshold at the 50th percentile of non-background pixels.
      3. Morphological open to remove speckle noise.
      4. connectedComponentsWithStats, filter by min area.
    Returns list sorted by area descending.
    """
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    # Adaptive threshold
    above_bg = gray[gray > 5]
    if above_bg.size == 0:
        return []
    thresh_val = max(INTENSITY_THRESHOLD, int(np.percentile(above_bg, 50)))
    _, binary = cv2.threshold(gray, thresh_val, 255, cv2.THRESH_BINARY)

    # Morphological cleanup
    kernel = np.ones((3, 3), np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        binary, connectivity=8,
    )

    blobs: list[dict] = []
    for i in range(1, num_labels):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < BLOB_MIN_SIZE_PX:
            continue

        x = int(stats[i, cv2.CC_STAT_LEFT])
        y = int(stats[i, cv2.CC_STAT_TOP])
        bw = int(stats[i, cv2.CC_STAT_WIDTH])
        bh = int(stats[i, cv2.CC_STAT_HEIGHT])
        cx, cy = centroids[i]

        mask = (labels == i).astype(np.uint8)
        mean_int = float(cv2.mean(gray, mask=mask)[0])

        blobs.append({
            "centroid_x_px": int(round(cx)),
            "centroid_y_px": int(round(cy)),
            "centroid_depth_fm": round(cy / PX_PER_FM, 1),
            "width_px": bw,
            "height_px": bh,
            "area_px": area,
            "mean_intensity": round(mean_int, 1),
            "aspect_ratio": round(bw / max(bh, 1), 2),
        })

    blobs.sort(key=lambda b: b["area_px"], reverse=True)

    # Phase 5: Cross-reference with catch report vocabulary
    try:
        vocab = aggregate_vocabulary()
        if vocab.get("total_labels", 0) > 0:
            blobs = annotate_blobs(blobs, vocab=vocab)
    except Exception:
        pass  # vocabulary lookup is additive, never blocking

    return blobs


# ══════════════════════════════════════════════════════════════════════
#  Multi-Frame Blob Tracking
# ══════════════════════════════════════════════════════════════════════

DEPTH_MATCH_THRESHOLD_FM = 2.0  # max depth difference to consider same blob


def track_blobs(current: list[dict], previous: list[dict]) -> dict:
    """Match blobs between consecutive frames by depth proximity.

    Uses a greedy nearest-neighbor match on centroid_depth_fm.
    Returns delta metrics: blob_count_delta, migrating counts,
    new_blobs, lost_blobs.

    Args:
        current: list of blob dicts from the current frame (must have
                 centroid_depth_fm)
        previous: list of blob dicts from the previous frame

    Returns:
        blob_count_delta: int (current - previous)
        migrating_up: int — blobs that moved shallower by > DEPTH_MATCH_THRESHOLD_FM
        migrating_down: int — blobs that moved deeper
        new_blobs: int — blobs in current with no close match in previous
        lost_blobs: int — blobs in previous with no close match in current
        matched_pairs: int — number of blob pairs matched
        mean_depth_shift_fm: float — average depth change of matched pairs
    """
    if not current and not previous:
        return {
            "blob_count_delta": 0,
            "migrating_up": 0,
            "migrating_down": 0,
            "new_blobs": 0,
            "lost_blobs": 0,
            "matched_pairs": 0,
            "mean_depth_shift_fm": 0.0,
        }

    # Extract depths
    curr_depths = [b["centroid_depth_fm"] for b in current]
    prev_depths = [b["centroid_depth_fm"] for b in previous]

    blob_count_delta = len(curr_depths) - len(prev_depths)

    if not previous:
        return {
            "blob_count_delta": blob_count_delta,
            "migrating_up": 0,
            "migrating_down": 0,
            "new_blobs": len(curr_depths),
            "lost_blobs": 0,
            "matched_pairs": 0,
            "mean_depth_shift_fm": 0.0,
        }

    if not current:
        return {
            "blob_count_delta": blob_count_delta,
            "migrating_up": 0,
            "migrating_down": 0,
            "new_blobs": 0,
            "lost_blobs": len(prev_depths),
            "matched_pairs": 0,
            "mean_depth_shift_fm": 0.0,
        }

    # Greedy nearest-neighbor matching
    # We'll match each current blob to its closest previous blob (by depth)
    # that hasn't been matched yet and is within threshold
    prev_available = set(range(len(prev_depths)))
    curr_available = set(range(len(curr_depths)))

    matched_pairs = []
    # Sort current blobs by depth so matching is deterministic
    curr_sorted = sorted(enumerate(curr_depths), key=lambda x: x[1])

    for ci, cd in curr_sorted:
        best_prev = None
        best_dist = float("inf")
        for pi in prev_available:
            dist = abs(cd - prev_depths[pi])
            if dist < best_dist:
                best_dist = dist
                best_prev = pi

        if best_prev is not None and best_dist <= DEPTH_MATCH_THRESHOLD_FM:
            matched_pairs.append((ci, best_prev, best_dist, cd - prev_depths[best_prev]))
            prev_available.discard(best_prev)
            curr_available.discard(ci)

    # Analyze matched pairs for migration
    migrating_up = 0
    migrating_down = 0
    depth_shifts = []
    for _ci, _pi, _dist, shift in matched_pairs:
        depth_shifts.append(shift)
        if shift < -DEPTH_MATCH_THRESHOLD_FM:
            migrating_up += 1  # moved shallower (smaller fm)
        elif shift > DEPTH_MATCH_THRESHOLD_FM:
            migrating_down += 1  # moved deeper

    mean_shift = sum(depth_shifts) / len(depth_shifts) if depth_shifts else 0.0

    return {
        "blob_count_delta": blob_count_delta,
        "migrating_up": migrating_up,
        "migrating_down": migrating_down,
        "new_blobs": len(curr_available),
        "lost_blobs": len(prev_available),
        "matched_pairs": len(matched_pairs),
        "mean_depth_shift_fm": round(mean_shift, 2),
    }


# ══════════════════════════════════════════════════════════════════════
#  Thermocline Detection
# ══════════════════════════════════════════════════════════════════════

def detect_thermoclines(band: np.ndarray) -> list[dict]:
    """Detect horizontal bands of consistent gradient (thermoclines).

    Uses horizontal Sobel gradient averaged per row, then finds contiguous
    blocks of rows where gradient exceeds the mean by 0.5 sigma.
    Adjacent bands within 5 rows are merged.
    """
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    h = gray.shape[0]

    sobelx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    grad_mag = np.abs(sobelx)
    row_grad = grad_mag.mean(axis=1)  # (h,)

    mean_g = float(row_grad.mean())
    std_g = float(row_grad.std())
    if std_g < 1e-6:
        return []
    threshold = mean_g + 0.5 * std_g

    above = (row_grad > threshold).astype(np.int8)
    diffs = np.diff(above, prepend=0, append=0)

    starts = np.where(diffs == 1)[0]
    ends = np.where(diffs == -1)[0]

    if len(starts) == 0:
        return []

    # Merge adjacent bands within 5 rows
    raw = [[int(s), int(e)] for s, e in zip(starts, ends) if int(e) - int(s) >= 3]
    if not raw:
        return []

    merged = [raw[0][:]]
    for s, e in raw[1:]:
        if s - merged[-1][1] <= 5:
            merged[-1][1] = e
        else:
            merged.append([s, e])

    layers: list[dict] = []
    for y_start, y_end in merged:
        y_mid = (y_start + y_end) / 2.0
        band_grad = float(row_grad[y_start:y_end].mean())

        if band_grad > mean_g + std_g:
            confidence = "high"
        elif band_grad > mean_g + 0.5 * std_g:
            confidence = "medium"
        else:
            confidence = "low"

        layers.append({
            "depth_range_fm": (
                round(y_start / PX_PER_FM, 1),
                round(y_end / PX_PER_FM, 1),
            ),
            "center_depth_fm": round(y_mid / PX_PER_FM, 1),
            "thickness_px": y_end - y_start,
            "mean_gradient": round(band_grad, 2),
            "confidence": confidence,
        })

    return layers


# ══════════════════════════════════════════════════════════════════════
#  Bottom Detection (optional, additive)
# ══════════════════════════════════════════════════════════════════════

def detect_bottom(band: np.ndarray) -> Optional[dict]:
    """Detect the bottom return — brightest continuous horizontal feature.

    Scans downward from 30 fm (row ~540) for the brightest row in grayscale.
    If found, evaluates continuity via coefficient of variation across that row.
    Returns None when no clear bottom is visible.
    """
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    h = gray.shape[0]

    mid_row = 540  # ~30 fm
    if mid_row >= h:
        return None

    search = gray[mid_row:, :]
    if search.size == 0:
        return None

    row_means = search.mean(axis=1)
    brightest_offset = int(np.argmax(row_means))
    brightest_row = mid_row + brightest_offset
    peak_intensity = float(row_means[brightest_offset])

    # Continuity: CV of pixel values along that row
    row_pixels = gray[brightest_row, :].astype(np.float64)
    row_mean = float(row_pixels.mean())
    row_std = float(row_pixels.std())

    if row_mean < 30:
        return None  # too dark, no bottom visible

    cv_val = row_std / max(row_mean, 1e-6)

    if cv_val > 1.5:
        confidence = "low"
    elif cv_val > 0.8:
        confidence = "medium"
    else:
        confidence = "high"

    return {
        "bottom_depth_fm": round(brightest_row / PX_PER_FM, 1),
        "row_y": brightest_row,
        "peak_intensity": round(peak_intensity, 1),
        "row_mean_intensity": round(row_mean, 1),
        "row_continuity_cv": round(cv_val, 2),
        "confidence": confidence,
    }


# ══════════════════════════════════════════════════════════════════════
#  Boat Proximity (Sounder Interference) Detection
# ══════════════════════════════════════════════════════════════════════

def detect_vertical_lines(
    band: np.ndarray,
    min_intensity: float = 50.0,
    min_vertical_span_ratio: float = 0.3,
    column_width_px: int = 3,
) -> dict:
    """Detect vertical line artifacts from nearby sounder transducers.

    Other boats' transducers create bright vertical columns that span
    multiple depth zones. Unlike fish blobs (localized clusters) or
    bottom returns (bright horizontal), these are narrow vertical streaks.

    Detection: computes mean intensity per column, finds columns where
    mean exceeds threshold, then clusters adjacent hot columns into
    "lines" and evaluates vertical span.

    Returns:
        vertical_line_count: total distinct vertical lines found
        lines_per_zone: {zone_name: count} distribution
        severity: "none" | "few" | "several" | "many" | "dense"
        max_vertical_span_fm: tallest line in fathoms
    """
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    # Per-column mean intensity
    col_means = gray.mean(axis=0)  # shape (w,)

    # Find hot columns above threshold
    hot = col_means > min_intensity

    # Cluster adjacent hot columns
    diffs = np.diff(hot.astype(np.int8), prepend=0, append=0)
    starts = np.where(diffs == 1)[0]
    ends = np.where(diffs == -1)[0]

    # Filter clusters by width (ignore very wide regions — those are schools/bottom)
    lines: list[dict] = []
    for s, e in zip(starts, ends):
        width = e - s
        if width > column_width_px and width < 20:  # 3-20px wide = transducer artifact
            # Check vertical span: sample the column(s) intensity profile
            mid_col = (s + e) // 2
            vertical_profile = gray[:, mid_col - 1 : mid_col + 2].mean(axis=1)
            above_thresh = (vertical_profile > min_intensity).sum()
            vertical_span_ratio = above_thresh / h
            if vertical_span_ratio >= min_vertical_span_ratio:
                top_y = int(np.argmax(vertical_profile > min_intensity))
                bot_y = h - int(np.argmax((vertical_profile > min_intensity)[::-1]))
                lines.append({
                    "x_start": int(s),
                    "x_end": int(e),
                    "width_px": width,
                    "vertical_span_ratio": round(vertical_span_ratio, 2),
                    "top_depth_fm": round(top_y / PX_PER_FM, 1),
                    "bottom_depth_fm": round(bot_y / PX_PER_FM, 1),
                    "span_fm": round((bot_y - top_y) / PX_PER_FM, 1),
                    "mean_intensity": round(float(col_means[s:e].mean()), 1),
                })

    if not lines:
        return {
            "vertical_line_count": 0,
            "lines_per_zone": {},
            "severity": "none",
            "max_vertical_span_fm": 0.0,
            "lines": [],
        }

    # Classify severity by count
    n = len(lines)
    if n >= 25:
        severity = "dense"
    elif n >= 12:
        severity = "many"
    elif n >= 5:
        severity = "several"
    else:
        severity = "few"

    # Per-zone distribution
    lines_per_zone: dict[str, int] = {z: 0 for z in ZONES}
    for ln in lines:
        mid_depth = (ln["top_depth_fm"] + ln["bottom_depth_fm"]) / 2.0
        for zname, (y0, y1) in ZONES.items():
            ztop = y0 / PX_PER_FM
            zbot = y1 / PX_PER_FM
            if ztop <= mid_depth <= zbot:
                lines_per_zone[zname] = lines_per_zone.get(zname, 0) + 1
                break

    spans = [ln["span_fm"] for ln in lines]

    return {
        "vertical_line_count": n,
        "lines_per_zone": lines_per_zone,
        "severity": severity,
        "max_vertical_span_fm": round(max(spans), 1),
        "lines": sorted(lines, key=lambda x: x["mean_intensity"], reverse=True)[:20],
    }


# ══════════════════════════════════════════════════════════════════════
#  Haze Detection (plankton / feed scatterers on HF band)
# ══════════════════════════════════════════════════════════════════════

def detect_haze(band: np.ndarray) -> dict:
    """Detect fine-scale scatterers (plankton/feed) in surface zone.

    Uses connected-components on the surface zone (rows 0-90, 0-5 fm)
    with a low area cutoff (< 15 px²) to catch tiny particles — these
    are "haze" from plankton or baitfish, not discrete fish returns.
    No morphological opening: haze IS the speckle we want to count.

    Returns:
        haze_blob_count: number of small blobs in surface zone
        mean_haze_area: average area of those blobs (px²)
        feed_present: True when count > 20 AND mean_area < 15 px²
        feed_intensity: "none" | "low" | "medium" | "high"
    """
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    surf_y_start, surf_y_end = ZONES["surface"]  # (0, 90)
    surface = gray[surf_y_start:surf_y_end, :]

    if surface.size == 0:
        return {
            "haze_blob_count": 0,
            "mean_haze_area": 0.0,
            "feed_present": False,
            "feed_intensity": "none",
        }

    above_bg = surface[surface > 5]
    if above_bg.size == 0:
        return {
            "haze_blob_count": 0,
            "mean_haze_area": 0.0,
            "feed_present": False,
            "feed_intensity": "none",
        }

    thresh_val = max(INTENSITY_THRESHOLD, int(np.percentile(above_bg, 50)))
    _, binary = cv2.threshold(surface, thresh_val, 255, cv2.THRESH_BINARY)

    # No morphological open — the speckle IS the signal we want
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        binary, connectivity=8,
    )

    haze_blobs: list[dict] = []
    for i in range(1, num_labels):
        area = int(stats[i, cv2.CC_STAT_AREA])
        # Only SMALL blobs (< 15 px²) — these are haze particles
        if area >= 15:
            continue

        x = int(stats[i, cv2.CC_STAT_LEFT])
        y = int(stats[i, cv2.CC_STAT_TOP])
        bw = int(stats[i, cv2.CC_STAT_WIDTH])
        bh = int(stats[i, cv2.CC_STAT_HEIGHT])
        cx, cy = centroids[i]

        mask = (labels == i).astype(np.uint8)
        mean_int = float(cv2.mean(surface, mask=mask)[0])

        haze_blobs.append({
            "centroid_x_px": int(round(cx)),
            "centroid_y_px": int(round(cy)),
            "centroid_depth_fm": round((surf_y_start + cy) / PX_PER_FM, 1),
            "width_px": bw,
            "height_px": bh,
            "area_px": area,
            "mean_intensity": round(mean_int, 1),
        })

    haze_count = len(haze_blobs)
    mean_area = (
        float(np.mean([b["area_px"] for b in haze_blobs]))
        if haze_blobs else 0.0
    )

    feed_present = haze_count > 20 and mean_area < 15

    if haze_count > 100:
        intensity = "high"
    elif haze_count > 50:
        intensity = "medium"
    elif haze_count > 20:
        intensity = "low"
    else:
        intensity = "none"

    return {
        "haze_blob_count": haze_count,
        "mean_haze_area": round(mean_area, 1),
        "feed_present": feed_present,
        "feed_intensity": intensity,
    }


# ══════════════════════════════════════════════════════════════════════
#  Temporal Context — read recent analyses for perspective
# ══════════════════════════════════════════════════════════════════════

def load_recent_context(
    current_json_path: Path, n_frames: int = 5,
) -> list[dict]:
    """Read the previous N analysis JSONs from the same day folder.

    Gives the analyzer temporal perspective: are boats approaching?
    Is the school building? Has the bottom depth changed?

    Returns list of dicts with:
        capture_id, ts_local, vertical_line_count, boat_severity,
        blob_count, thermocline_count, mid_zone_mean, bottom_depth_fm
    """
    day_dir = current_json_path.parent
    if not day_dir.is_dir():
        return []

    jsons = sorted(day_dir.glob("*.json"), reverse=True)
    # Exclude current file
    jsons = [j for j in jsons if j.name != current_json_path.name]

    recent: list[dict] = []
    for js in jsons[:n_frames]:
        try:
            data = json.loads(js.read_text(encoding="utf-8"))
            analysis = data.get("analysis", {})
            heuristic = analysis.get("heuristic", {})
            lf = heuristic.get("lf", {})

            # Boat proximity was vertical lines in prior run
            # On first run, this won't exist yet — that's fine
            boats = lf.get("boat_proximity", {})

            mid = lf.get("zone_profiles", {}).get("mid", {})
            bottom = lf.get("bottom", {})

            recent.append({
                "capture_id": data.get("capture_id", js.stem),
                "ts_local": data.get("ts_local", ""),
                "vertical_line_count": boats.get("vertical_line_count", 0),
                "boat_severity": boats.get("severity", "unknown"),
                "blob_count": lf.get("blob_count", 0),
                "thermocline_count": lf.get("thermocline_count", 0),
                "mid_zone_mean": mid.get("mean_intensity", 0),
                "bottom_depth_fm": bottom.get("bottom_depth_fm") if bottom else None,
            })
        except (json.JSONDecodeError, KeyError, OSError):
            continue

    return recent


# ══════════════════════════════════════════════════════════════════════
#  Per-band orchestrator
# ══════════════════════════════════════════════════════════════════════

def analyze_single(band: np.ndarray, band_name: str = "") -> dict:
    """Run all analyses on one BGR band. Returns structured result dict.

    When band_name is "HF", also runs haze (plankton) detection in
    the surface zone — plankton scatter shows on high-frequency.
    """
    # Depth zone profiles
    zone_profiles: dict[str, dict] = {}
    for zname, (y0, y1) in ZONES.items():
        zone_profiles[zname] = depth_zone_profile(band, zname, y0, y1)

    blobs = detect_blobs(band)
    thermos = detect_thermoclines(band)
    bottom = detect_bottom(band)
    boats = detect_vertical_lines(band)

    result: dict = {
        "zone_profiles": zone_profiles,
        "column_delta": column_delta(band),
        "blobs": blobs,
        "blob_count": len(blobs),
        "thermoclines": thermos,
        "thermocline_count": len(thermos),
        "bottom": bottom,
        "boat_proximity": boats,
    }

    # Haze detection only for HF band (plankton shows on high frequency)
    if band_name.upper() == "HF":
        result["haze"] = detect_haze(band)

    return result


# ══════════════════════════════════════════════════════════════════════
#  Caption Generation
# ══════════════════════════════════════════════════════════════════════

def generate_caption(
    lf: dict, hf: dict,
    recent_context: list[dict] | None = None,
    track_result: dict | None = None,
    school_state: dict | None = None,
) -> str:
    """Generate a 2-4 sentence natural-language summary of both bands.

    If recent_context is provided (list of prior analysis snapshots),
    the caption gains temporal perspective — boat proximity trends,
    school building/declining, etc.

    If track_result is provided (from track_blobs), includes multi-frame
    blob tracking insights (migration direction, new/lost blobs).

    If school_state is provided, includes behavioral classification.
    """
    parts: list[str] = []

    # ── Bottom ──
    lf_bottom = lf.get("bottom")
    hf_bottom = hf.get("bottom")
    bottom = lf_bottom or hf_bottom
    if bottom and bottom.get("confidence") != "low":
        parts.append(
            f"Bottom detected at {bottom['bottom_depth_fm']} fm "
            f"({bottom['confidence']} confidence)."
        )
    else:
        parts.append("No clear bottom return detected in the displayed range.")

    # ── Thermoclines (prefer LF) ──
    thermo_count = lf.get("thermocline_count", 0)
    if thermo_count > 0:
        depths = [
            str(t["center_depth_fm"]) + " fm"
            for t in lf.get("thermoclines", [])
        ]
        depth_str = ", ".join(depths[:3])
        parts.append(
            f"{thermo_count} thermal layer{'s' if thermo_count != 1 else ''} "
            f"detected at {depth_str}."
        )

    # ── Blobs / echo returns ──
    blob_count = lf.get("blob_count", 0)
    if blob_count > 0:
        blobs = lf.get("blobs", [])
        zone_counts: dict[str, int] = {z: 0 for z in ZONES}
        predicted_species: set = set()
        for b in blobs:
            d = b["centroid_depth_fm"]
            if d < 5:
                zone_counts["surface"] += 1
            elif d < 20:
                zone_counts["upper"] += 1
            elif d < 40:
                zone_counts["mid"] += 1
            elif d < 55:
                zone_counts["lower"] += 1
            else:
                zone_counts["floor"] += 1
            # Phase 5: Check for vocabulary predictions
            pred = b.get("prediction")
            if pred and pred.get("species"):
                predicted_species.add(pred["species"])

        active = [z for z, c in zone_counts.items() if c > 0]
        blob_line = (
            f"{blob_count} echo return{'s' if blob_count != 1 else ''} "
            f"detected in the LF band across "
            f"{len(active)} zone{'s' if len(active) != 1 else ''} "
            f"({', '.join(active)})."
        )

        if predicted_species:
            blob_line += (
                f" Vocabulary predicts: {', '.join(sorted(predicted_species))}."
            )

        parts.append(blob_line)
    else:
        parts.append("No significant echo returns in the LF band.")

    # ── Mid-water intensity (target chum zone) ──
    mid = lf.get("zone_profiles", {}).get("mid", {})
    mid_mean = mid.get("mean_intensity", 0)
    mid_peak = mid.get("peak_intensity", 0)
    parts.append(
        f"Mid-water column (20-40 fm) mean intensity "
        f"{mid_mean:.1f}/255, peak {mid_peak}/255."
    )

    # ── Haze (plankton / feed scatterers, HF band surface zone) ──
    haze = hf.get("haze")
    if haze and haze.get("feed_present"):
        intensity = haze.get("feed_intensity", "low")
        parts.append(
            f"HF shallow zone shows {intensity} scatterer activity — "
            f"likely plankton/feed in the upper water column."
        )

    # ── Boat proximity from sounder interference ──
    boats = lf.get("boat_proximity", {})
    n_lines = boats.get("vertical_line_count", 0)
    severity = boats.get("severity", "none")

    if n_lines > 0:
        if severity == "dense":
            boat_str = f"Dense sounder interference detected — likely multiple boats very close."
        elif severity == "many":
            boat_str = f"Strong sounder interference ({n_lines} vertical lines) — other boats nearby."
        elif severity == "several":
            boat_str = f"{n_lines} vertical lines from other transducers — boats in the area."
        else:
            boat_str = f"{n_lines} vertical line{'s' if n_lines != 1 else ''} from nearby vessel."

        # Trend analysis from temporal context
        if recent_context:
            prev_counts = [
                r["vertical_line_count"] for r in recent_context
                if r["vertical_line_count"] > 0
            ]
            if len(prev_counts) >= 2:
                avg_prev = sum(prev_counts) / len(prev_counts)
                if n_lines > avg_prev * 1.5:
                    boat_str += f" Up from avg of {avg_prev:.0f} — boats getting closer."
                elif n_lines < avg_prev * 0.5:
                    boat_str += f" Down from avg of {avg_prev:.0f} — boats moving away."
        parts.append(boat_str)
    elif recent_context:
        # No boats now — were there boats recently?
        any_recent = any(
            r["vertical_line_count"] > 0 for r in recent_context
        )
        all_empty = all(
            r["vertical_line_count"] == 0 for r in recent_context
        )
        if any_recent and not all_empty:
            parts.append(
                "No sounder interference currently. Boats in recent frames are gone — "
                "we may have our school back to ourselves."
            )
        elif not all_empty:
            parts.append("No other boats detected — alone on the grounds.")

    # ── Blob tracking (multi-frame) ──
    try:
        if track_result and track_result.get("matched_pairs", 0) > 0:
            tr = track_result
            track_parts = []
            if tr.get("migrating_up", 0) > 0:
                track_parts.append(f"{tr['migrating_up']} migrating shallower")
            if tr.get("migrating_down", 0) > 0:
                track_parts.append(f"{tr['migrating_down']} diving deeper")
            if track_parts:
                parts.append(f"Blob tracking: {', '.join(track_parts)}. ")
            if tr.get("new_blobs", 0) > 0:
                parts.append(f"{tr['new_blobs']} new echo returns appeared.")
            if tr.get("lost_blobs", 0) > 0:
                parts.append(f"{tr['lost_blobs']} echo returns disappeared.")
    except Exception:
        pass  # tracking is additive, never blocking

    # ── School state (from school_state module) ──
    try:
        if school_state:
            state = school_state.get("state", "unknown")
            conf = school_state.get("confidence", 0)
            if conf >= 0.3:
                state_labels = {
                    "building": "📈 School is building",
                    "dispersing": "📉 School may be dispersing",
                    "holding": "🏠 School appears to be holding",
                    "migrating": "🐟 School appears to be migrating",
                    "absent": "❌ No significant school detected",
                }
                label = state_labels.get(state, f"School state: {state}")
                evidence_items = school_state.get("evidence", [])
                parts.append(
                    f"{label} (confidence {conf:.0%})"
                    + (f": {evidence_items[0]}" if evidence_items else "") + "."
                )
    except Exception:
        pass  # school_state is additive, never blocking

    # ── Signal fusion state (if available) ──
    try:
        from signal_fusion import FusionEngine
        engine = FusionEngine.load_or_new()
        bf = engine.belief_state()
        entropy = engine.entropy()
        if entropy < 2.0:
            # Map belief keys to readable labels
            readable = []
            for k, v in sorted(bf.items(), key=lambda x: abs(x[1]), reverse=True):
                if abs(v) > 0.3:
                    label_k = k.replace("_", " ").capitalize()
                    readable.append(f"{label_k}: {v:+.2f}")
            if readable:
                parts.append(
                    f"Fusion state (entropy {entropy:.2f}): "
                    + ", ".join(readable[:4]) + "."
                )
    except Exception:
        pass  # signal_fusion is additive, never blocking

    # ── Anomaly status (from temporal_mining) ──
    try:
        from temporal_mining import scan_anomalies
        anomalies = scan_anomalies(n_frames=5)
        if anomalies:
            recent_anoms = [a for a in anomalies if a.get("is_anomaly")]
            if recent_anoms:
                parts.append(
                    f"⚠ {len(recent_anoms)} recent anomalous frame(s) detected "
                    f"(z > 2.5)."
                )
    except Exception:
        pass  # temporal_mining is additive, never blocking

    return " ".join(parts)


# ══════════════════════════════════════════════════════════════════════
#  Ship Log POST
# ══════════════════════════════════════════════════════════════════════

def update_ship_log(meta: dict, analysis: dict, caption: str) -> None:
    """POST enriched analysis payload to Ship Log Search."""
    try:
        pos = meta.get("position", {})
        capture_id = meta.get("capture_id", "unknown")
        ts_utc = meta.get("ts_utc", datetime.now(timezone.utc).isoformat())

        lf = analysis.get("lf", {})
        bottom = lf.get("bottom")
        mid = lf.get("zone_profiles", {}).get("mid", {})

        boats = lf.get("boat_proximity", {})
        payload = {
            "text": caption,
            "category": "observation",
            "subcategory": "echogram_analysis",
            "timestamp": ts_utc,
            "lat": pos.get("lat_dd"),
            "lon": pos.get("lon_dd"),
            "location_name": f"{pos.get('lat_ddmm', '?')}N/{pos.get('lon_ddmm', '?')}W",
            "id": f"analysis_{capture_id}",
            "metadata": {
                "capture_id": capture_id,
                "type": "echogram_analysis",
                "schema_version": ANALYZED_SCHEMA_VERSION,
                "bottom_depth_fm": bottom["bottom_depth_fm"] if bottom else None,
                "bottom_confidence": bottom["confidence"] if bottom else None,
                "thermocline_count": lf.get("thermocline_count", 0),
                "blob_count": lf.get("blob_count", 0),
                "mid_zone_mean_intensity": mid.get("mean_intensity"),
                "mid_zone_peak_intensity": mid.get("peak_intensity"),
                "boat_proximity": {
                    "vertical_lines": boats.get("vertical_line_count", 0),
                    "severity": boats.get("severity", "none"),
                },
            },
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            SHIP_LOG_URL,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36"
                ),
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=SHIP_LOG_TIMEOUT_S)
        log.info("Ship Log analysis ingested: %s", capture_id)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        log.warning("Ship Log update failed (non-blocking): %s", e)


# ══════════════════════════════════════════════════════════════════════
#  File I/O
# ══════════════════════════════════════════════════════════════════════

def load_meta(json_path: Path) -> Optional[dict]:
    """Load capture JSON metadata. Returns None on failure."""
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        log.warning("Cannot read %s: %s", json_path.name, e)
        return None


def needs_analysis(meta: dict) -> bool:
    """Return True if schema_version < ANALYZED_SCHEMA_VERSION."""
    analysis = meta.get("analysis", {})
    sv = analysis.get("schema_version", 0)
    return sv < ANALYZED_SCHEMA_VERSION


def write_analysis_json(
    json_path: Path, meta: dict, analysis: dict, caption: str,
) -> bool:
    """Embed analysis results into capture JSON.

    Preserves existing analysis.vocabulary (catch report labels) —
    never overwrite supervised learning data.
    """
    try:
        existing = meta.get("analysis", {})
        existing_vocab = existing.get("vocabulary", None)
        existing_sv = existing.get("schema_version", 0)

        # Don't downgrade schema_version — catch labels may have bumped it to 3+
        new_sv = max(ANALYZED_SCHEMA_VERSION, existing_sv)

        meta["analysis"] = {
            "schema_version": new_sv,
            "heuristic": {
                "lf": analysis["lf"],
                "hf": analysis["hf"],
            },
            "caption": caption,
            "vocabulary": existing_vocab,  # preserve catch labels
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, default=str)
        log.info("JSON analysis written: %s", json_path.name)
        return True
    except Exception as e:
        log.warning("write_analysis_json failed: %s", e)
        return False


def update_markdown(md_path: Path, analysis: dict, caption: str) -> bool:
    """Insert or replace ## Analysis section in the markdown twin."""
    if not md_path.exists():
        log.warning("MD not found: %s", md_path)
        return False

    try:
        lf = analysis.get("lf", {})
        hf = analysis.get("hf", {})
        now_str = datetime.now(LOCAL_TZ).strftime("%H:%M:%S AKDT")

        lines = [
            "## Analysis",
            "",
            caption,
            "",
            "### LF Band",
            "",
        ]

        # Bottom
        bottom = lf.get("bottom") or hf.get("bottom")
        if bottom:
            lines.append(
                f"- **Bottom:** {bottom['bottom_depth_fm']} fm "
                f"({bottom['confidence']} confidence)"
            )
            lines.append("")

        # Zone profiles
        for label, band_data in [("LF", lf), ("HF", hf)]:
            zones = band_data.get("zone_profiles", {})
            if not zones:
                continue
            lines.append(f"**{label} zone intensities (mean / peak):**")
            for zname in ("surface", "upper", "mid", "lower", "floor"):
                z = zones.get(zname)
                if z:
                    lines.append(
                        f"  - {zname.capitalize():>8}  {z['mean_intensity']:.1f} / {z['peak_intensity']}"
                    )
            lines.append("")

        # Boat proximity
        boats = lf.get("boat_proximity", {})
        n_boats = boats.get("vertical_line_count", 0)
        if n_boats > 0:
            sev = boats.get("severity", "unknown")
            lines.append(f"- **Nearby vessels:** {n_boats} vertical line(s) ({sev} interference)")
            lines.append("")

        # Haze (plankton/feed on HF)
        haze = hf.get("haze")
        if haze and haze.get("feed_present"):
            intensity = haze.get("feed_intensity", "low")
            count = haze.get("haze_blob_count", 0)
            area = haze.get("mean_haze_area", 0)
            lines.append(
                f"- **Plankton/feed (HF surface):** {count} haze particles "
                f"(avg {area:.1f} px²) — {intensity} activity"
            )
            lines.append("")

        # Blobs
        blobs_lf = lf.get("blobs", [])
        lines.append(f"- **Echo returns (LF):** {len(blobs_lf)} blob(s) detected")
        if blobs_lf:
            top = blobs_lf[0]
            lines.append(
                f"  - Largest: {top['centroid_depth_fm']} fm, "
                f"{top['area_px']} px², intensity {top['mean_intensity']:.1f}"
            )
            if len(blobs_lf) > 1:
                top2 = blobs_lf[1]
                lines.append(
                    f"  - 2nd: {top2['centroid_depth_fm']} fm, "
                    f"{top2['area_px']} px², intensity {top2['mean_intensity']:.1f}"
                )
        lines.append("")

        # Thermoclines
        thermos = lf.get("thermoclines", [])
        if thermos:
            depths = ", ".join(f"{t['center_depth_fm']} fm" for t in thermos[:4])
            lines.append(
                f"- **Thermoclines (LF):** {len(thermos)} layer(s) at {depths}"
            )
            lines.append("")

        lines.append(f"*Analyzed by analyzer.py at {now_str}*")

        analysis_section = "\n".join(lines)

        # Replace existing ## Analysis block or append
        md_text = md_path.read_text(encoding="utf-8")
        tag = "## Analysis"
        before = md_text.split(tag, 1)[0].rstrip()
        updated = before + "\n\n" + analysis_section + "\n"

        md_path.write_text(updated, encoding="utf-8")
        log.info("Markdown updated: %s", md_path.name)
        return True
    except Exception as e:
        log.warning("update_markdown failed: %s", e)
        return False


# ══════════════════════════════════════════════════════════════════════
#  Watcher Loop
# ══════════════════════════════════════════════════════════════════════


def _build_school_history(json_path: Path, n_frames: int = 5) -> list[dict]:
    """Build a history list for classify_school from recent captures.

    Reads the most recent N analysis JSONs from the same day folder
    and extracts blob_count, blobs, boats, and haze fields.

    Returns list of dicts suitable for classify_school(), oldest first.
    """
    day_dir = json_path.parent
    if not day_dir.is_dir():
        return []

    jsons = sorted(day_dir.glob("*.json"))

    history: list[dict] = []
    for js in jsons:
        try:
            data = json.loads(js.read_text(encoding="utf-8"))
            analysis = data.get("analysis", {})
            heuristic = analysis.get("heuristic", {})
            lf = heuristic.get("lf", {})
            hf = heuristic.get("hf", {})

            blobs = lf.get("blobs", [])
            boats = lf.get("boat_proximity", {})
            haze = hf.get("haze", {})

            history.append({
                "capture_id": data.get("capture_id", js.stem),
                "blob_count": lf.get("blob_count", 0),
                "blobs": blobs,
                "boats": boats.get("vertical_line_count", 0),
                "haze": haze.get("feed_intensity", "none"),
                "zone_distribution": _zone_dist_from_profiles(
                    lf.get("zone_profiles", {})
                ),
            })
        except (json.JSONDecodeError, KeyError, OSError):
            continue

    return history[-n_frames:] if history else []


def _zone_dist_from_profiles(zone_profiles: dict) -> dict[str, float]:
    """Extract mean intensities per zone from profile data."""
    return {
        zname: zone_profiles.get(zname, {}).get("mean_intensity", 0.0)
        for zname in ZONES
    }


# ══════════════════════════════════════════════════════════════════════

def find_unanalyzed_captures() -> list[tuple[Path, Path, Path, dict]]:
    """Scan captures/v3/ for .png files needing analysis.

    Returns (png_path, json_path, md_path, meta) tuples.
    """
    if not CAPTURES_DIR.exists():
        return []

    results: list[tuple[Path, Path, Path, dict]] = []
    for day_dir in sorted(CAPTURES_DIR.iterdir()):
        if not day_dir.is_dir():
            continue
        for png_file in sorted(day_dir.glob("*.png")):
            js = png_file.with_suffix(".json")
            md = png_file.with_suffix(".md")
            if not js.exists():
                continue
            meta = load_meta(js)
            if meta is None:
                continue
            if not needs_analysis(meta):
                continue
            results.append((png_file, js, md, meta))

    return results


def _read_previous_blobs(json_path: Path) -> list[dict]:
    """Read LF blobs from the chronologically previous capture's JSON.

    Scans day-dir JSONs sorted by name, finds the one immediately before
    the current json_path, and returns its LF blobs list.
    """
    day_dir = json_path.parent
    if not day_dir.is_dir():
        return []

    jsons = sorted(day_dir.glob("*.json"))
    try:
        idx = jsons.index(json_path)
    except ValueError:
        return []

    if idx == 0:
        return []  # no previous frame

    prev_json = jsons[idx - 1]
    try:
        data = json.loads(prev_json.read_text(encoding="utf-8"))
        analysis = data.get("analysis", {})
        heuristic = analysis.get("heuristic", {})
        return heuristic.get("lf", {}).get("blobs", [])
    except (json.JSONDecodeError, OSError):
        return []


def process_capture(
    png_path: Path, json_path: Path, md_path: Path, meta: dict,
) -> bool:
    """Run full analysis on a single capture frame. Returns success."""
    log.info("Analyzing: %s", png_path.name)
    try:
        img = cv2.imread(str(png_path))
        if img is None:
            log.warning("Cannot read: %s", png_path)
            return False
        if img.shape != (1080, 1920, 3):
            log.warning("Unexpected shape %s for %s; resizing", img.shape, png_path.name)
            img = cv2.resize(img, (1920, 1080))

        lf_band, hf_band = crop_bands(img)
        analysis_lf = analyze_single(lf_band, band_name="LF")
        analysis_hf = analyze_single(hf_band, band_name="HF")

        analysis = {"lf": analysis_lf, "hf": analysis_hf}

        # Load temporal context for perspective-aware descriptions
        recent_context = load_recent_context(json_path, n_frames=5)

        # Multi-frame blob tracking: compare current LF blobs with previous frame
        prev_blobs = _read_previous_blobs(json_path)
        track_result = track_blobs(analysis_lf["blobs"], prev_blobs)
        analysis["lf"]["tracking"] = track_result

        # Phase 8: Classify school behavior from recent captures
        school_state = None
        try:
            school_history = _build_school_history(json_path, n_frames=5)
            if school_history:
                school_state = classify_school(school_history)
                analysis["school_state"] = school_state
                log.info(
                    "School: %s (conf=%.2f)",
                    school_state["state"],
                    school_state["confidence"],
                )
        except Exception as e:
            log.debug("School classification skipped: %s", e)

        caption = generate_caption(
            analysis_lf, analysis_hf, recent_context,
            track_result=track_result,
            school_state=school_state,
        )

        # Phase 9: Signal fusion
        try:
            from signal_fusion import FusionEngine
            engine = FusionEngine.load_or_new()
            engine.ingest_capture(
                lf=analysis_lf, hf=analysis_hf,
                position=meta.get("position", {}),
                boats=analysis_lf.get("boat_proximity", {})
            )
            engine.save()
            fusion_state = engine.belief_state()
            if engine.entropy() < 1.0:
                log.info("Fusion consensus: %s", fusion_state)
        except Exception as fusion_err:
            log.debug("Signal fusion skipped: %s", fusion_err)

        write_analysis_json(json_path, meta, analysis, caption)
        update_markdown(md_path, analysis, caption)
        update_ship_log(meta, analysis, caption)

        log.info("Analyzed OK: %s — %s", png_path.name, caption[:80])

        # Phase 6: Check real-time alerts after analysis
        try:
            from alerts import check_alerts
            alerts = check_alerts()
            for alert in alerts:
                log.warning("ALERT [%s]: %s", alert.get("severity", "info"), alert.get("message", ""))
        except ImportError:
            pass  # alerts.py not built yet
        except Exception as alert_err:
            log.debug("Alert check skipped: %s", alert_err)

        # Phase 12: Feed capture into memory system
        try:
            from memory_bridge import process_capture as memory_process
            memory_process(json_path)
        except ImportError:
            pass  # memory_bridge not available
        except Exception as mem_err:
            log.debug("Memory bridge skipped: %s", mem_err)

        return True

    except Exception as e:
        log.error("Analysis FAILED for %s: %s", png_path.name, e, exc_info=True)
        return False


def run_forever() -> None:
    """Main watcher loop — scan every SCAN_INTERVAL_S."""
    log.info("=" * 50)
    log.info("analyzer.py starting")
    log.info("Watching: %s", CAPTURES_DIR)
    log.info("Scan: %ds interval", SCAN_INTERVAL_S)
    log.info("Schema: v%d", ANALYZED_SCHEMA_VERSION)
    log.info("=" * 50)

    while True:
        try:
            candidates = find_unanalyzed_captures()
            if candidates:
                log.info("Pending: %d capture(s)", len(candidates))
                for png, js, md, meta in candidates:
                    process_capture(png, js, md, meta)

                # Phase 10: Temporal anomaly check
                try:
                    from temporal_mining import scan_anomalies
                    anomalies = scan_anomalies(n_frames=20)
                    if anomalies:
                        for a in anomalies[:3]:
                            log.info("Anomaly [z=%.1f]: %s", a.get("z_score", 0), a.get("capture_id", "?"))
                except Exception as temporal_err:
                    log.debug("Temporal mining skipped: %s", temporal_err)
            else:
                log.debug("No pending captures")

            # Phase 13: Memory system tick (every loop, regardless of captures)
            try:
                from memory_bridge import tick
                tick()
            except ImportError:
                pass  # memory_bridge not available
            except Exception as mem_tick_err:
                log.debug("Memory tick skipped: %s", mem_tick_err)

        except Exception as e:
            log.error("Loop error: %s", e, exc_info=True)

        time.sleep(SCAN_INTERVAL_S)


# ══════════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════════

def analyze_all_pending(retroactive: bool = False) -> int:
    """Analyze all pending or all captures (retroactive mode).

    In retroactive mode, forces re-analysis of every capture regardless
    of schema_version — applying current vocabulary to old data.
    Returns count of captures analyzed.
    """
    if retroactive:
        log.info("Retroactive re-analysis mode — scanning ALL captures")
        count = 0
        for day_dir in sorted(CAPTURES_DIR.iterdir()):
            if not day_dir.is_dir():
                continue
            for png_file in sorted(day_dir.glob("*.png")):
                js = png_file.with_suffix(".json")
                md = png_file.with_suffix(".md")
                if not js.exists():
                    continue
                meta = load_meta(js)
                if meta is None:
                    continue
                process_capture(png_file, js, md, meta)
                count += 1
        log.info("Retroactive re-analysis complete: %d captures", count)
        return count
    else:
        candidates = find_unanalyzed_captures()
        log.info("Pending captures: %d", len(candidates))
        for png, js, md, meta in candidates:
            process_capture(png, js, md, meta)
        return len(candidates)


def cli() -> None:
    """CLI entry point."""
    import sys

    if "--help" in sys.argv or "-h" in sys.argv:
        print("Usage: python analyzer.py [--oneshot [<png_path>]]")
        print("  (no args)        Watcher loop — scans every 60s")
        print("  --oneshot        Analyze first unanalyzed capture")
        print("  --oneshot <p>    Analyze specific PNG")
        print("  --retroactive    Re-analyze ALL captures with current vocabulary")
        return

    if "--retroactive" in sys.argv:
        count = analyze_all_pending(retroactive=True)
        print(f"Retroactive re-analysis: {count} captures processed.")
        return

    if "--oneshot" in sys.argv:
        idx = sys.argv.index("--oneshot") + 1
        if idx < len(sys.argv):
            png_path = Path(sys.argv[idx])
            if not png_path.exists():
                print(f"File not found: {png_path}")
                return
            json_path = png_path.with_suffix(".json")
            md_path = png_path.with_suffix(".md")
            meta = load_meta(json_path) if json_path.exists() else {
                "capture_id": png_path.stem,
                "ts_utc": datetime.now(timezone.utc).isoformat(),
                "ts_local": datetime.now(LOCAL_TZ).isoformat(),
                "frame_file": png_path.name,
                "display": {"depth_max_fm": DEPTH_MAX_FM},
                "analysis": {"schema_version": 1},
            }
            process_capture(png_path, json_path, md_path, meta)
        else:
            candidates = find_unanalyzed_captures()
            if not candidates:
                print("No unanalyzed captures found.")
                return
            png, js, md, meta = candidates[0]
            process_capture(png, js, md, meta)
    else:
        run_forever()


if __name__ == "__main__":
    cli()
