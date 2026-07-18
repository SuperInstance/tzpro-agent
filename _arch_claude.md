# tzpro-agent v3 Architecture — The Capture/Analysis Pipeline

> **For:** F/V EILEEN, Ketchikan Alaska  
> **Date:** July 17, 2026  
> **Context:** Shift from single-strip sounder analysis to full-frame dual-band echogram capture with multi-track DAW correlation, text-summary analysis, and supervised vocabulary building.

---

## Table of Contents

1. [Paradigm Shift](#1-paradigm-shift)
2. [Display Layout Reference](#2-display-layout-reference)
3. [Capture Pipeline](#3-capture-pipeline)
4. [Analyzer Design](#4-analyzer-design)
5. [Text Summary Schema](#5-text-summary-schema)
6. [Multi-Track Correlation](#6-multi-track-correlation)
7. [Storage Strategy](#7-storage-strategy)
8. [Vocabulary Building](#8-vocabulary-building)
9. [Implementation Phasing](#9-implementation-phasing)
10. [Files & Module Map](#10-files--module-map)

---

## 1. Paradigm Shift

### What Changed

| Aspect | v1 (July 15) | v3 (July 17+) |
|--------|-------------|---------------|
| Display | Nav layout, sounder was right 370px strip | Full-screen dual-band sounder-only |
| Capture | 30s cadence, 370×900 crop | 10min cadence, full 1920×1080 frame |
| Analyzer | OpenCV pixel thresholds | Text-summary agent describing echogram state |
| NMEA | Paired per capture | Dedicated track on timeline |
| Retroactivity | None | Core feature — re-analyze old captures with new knowledge |
| Learning | Anomaly detection (depth deltas) | Vocabulary building from captain reports |
| Storage | JSONL observations + SQLite anomalies | Image archive + text summaries + catch events + vocabulary db |

### The DAW Metaphor (Concrete)

Each capture/analysis pipeline produces one **track** on a multi-track timeline:

| Track # | Name | Content | Producer | Cadence |
|---------|------|---------|----------|---------|
| 1 | **LF Echogram** | Full left-band image | `capture_v3.py` | 10 min |
| 2 | **HF Echogram** | Full right-band image | `capture_v3.py` | 10 min |
| 3 | **NMEA Snapshot** | Position, SOG, COG at capture time | `hermitd` / vessel endpoint | On capture |
| 4 | **Text Summary** | Structured echogram description | `analyzer_v3.py` | 10 min |
| 5 | **Catch Events** | Captain-reported species, count, depth | `catch_logger.py` | As reported |
| 6 | **Vocabulary Matches** | Learned pattern matches with confidence | `vocabulary.py` | Async / on query |

All tracks share a single timestamp. Any track can be queried by time range.
Any old capture can be re-analyzed and produce a NEW text summary (track 4) without deleting the old one.

---

## 2. Display Layout Reference

### Physical Setup

```
Second monitor: 1920×1080, offset X=1920, Y=0
TZ Pro running in: full-screen dual-band sounder-only view (echogram history mode)

┌─────────────────────────────────────────────────────────────────────┐
│  ┌─────────────────────────────────┐    ┌─────────────────────────┐ │
│  │  LOW FREQUENCY (LF) Band        │  │ │  HIGH FREQUENCY (HF)   │ │
│  │  ~930px wide                     │  │ │  ~940px wide           │ │
│  │  12+ min scrolling echogram     │  │ │  12+ min echogram     │ │
│  │                                  │  │ │                        │ │
│  │  Each column = one ping         │  │ │  Each column = ping   │ │
│  │  Colors: blue→cyan→yellow→red   │  │ │  Palette same but     │ │
│  │  as return intensity increases  │  │ │  higher frequency =    │ │
│  │                                  │  │ │  higher resolution    │ │
│  │                                  │  │ │  shallower penetration│ │
│  │                                  │  │ │                        │ │
│  │   Bottom / fish visible here    │  │ │  (often quiet — shows │ │
│  │   if returns present             │  │ │   surface clutter,    │ │
│  │                                  │  │ │   near-surface fish)  │ │
│  └─────────────────────────────────┘  │ └─────────────────────────┘ │
│                                       │                            │
└─────────────────────────────────────────────────────────────────────┘
  x=0        x=8                    x=945 x=950               x=1890 x=1919
```

### Measured Pixel Coordinates

From the capture at 08:45 AKDT (tzpro_20260717_084557.png):

| Feature | X Range | Y Range | Notes |
|---------|---------|---------|-------|
| LF band (active area) | 8–945 | 0–1080 | Scrolling echogram |
| LF→HF divider | 945–950 | 0–1080 | White vertical line (bright) |
| HF band (active area) | 950–1890 | 0–1080 | Scrolling echogram |
| Depth scale ticks (HF) | 1870–1890 | full height | Numeric depth markers |
| UI element (left edge) | 0–8 | full height | Bright yellow-green gradient |
| Bottom return (LF) | 8–945 | 480–530 | Brightest cluster — bright yellow/orange |

### Color Profile

| Object | Approx RGB | Total | Interpretation |
|--------|-----------|-------|----------------|
| Quiet water background | (0, 32, 99) | ~131 | Dark blue — no return |
| Scattered plankton/clutter | (40, 90, 140) | ~270 | Light blue-cyan |
| Medium fish return | (100, 180, 80) | ~360 | Yellow-green |
| Strong return (bottom) | (200, 160, 40) | ~400 | Orange |
| Very strong (hard bottom) | (230, 100, 30) | ~360 | Red-orange |
| White divider | (255, 255, 255) | 765 | Full white |
| Surface clutter line | (80, 150, 100) | ~330 | Cyan-green near top |

---

## 3. Capture Pipeline

### 3.1 New Config

```python
# config_v3.py — New layout constants

from pathlib import Path

# ── Display Layout ──────────────────────────────────────────────────
DISPLAY_OFFSET_X = 1920
DISPLAY_WIDTH = 1920
DISPLAY_HEIGHT = 1080

# ── Dual-Band Sounder Regions ──────────────────────────────────────
LF_BAND = (8, 0, 945, 1080)        # (x1, y1, x2, y2)
HF_BAND = (950, 0, 1890, 1080)
DIVIDER_X = 945                     # center of white divider

# ── Depth Scale ─────────────────────────────────────────────────────
DEPTH_SCALE_X = 1870                # right edge of HF band
DEPTH_SCALE_WIDTH = 30              # pixels for depth numbers

# ── Analyzer Pixel Zones ────────────────────────────────────────────
# Vertical zones as fraction of panel height (0=top, 1=bottom)
ZONE_SURFACE = (0.00, 0.05)        # Surface clutter / transducer noise
ZONE_UPPER_COLUMN = (0.05, 0.30)   # Upper water column
ZONE_MID_COLUMN = (0.30, 0.60)     # Mid water column
ZONE_LOWER_COLUMN = (0.60, 0.85)   # Lower water column (fish near bottom)
ZONE_BOTTOM_BAND = (0.85, 1.00)    # Bottom return area

# ── Bottom Detection ────────────────────────────────────────────────
# In the dual-band view (930px wide LF), the bottom spans the full width.
# We sample vertical profiles at multiple horizontal positions.
BOTTOM_SAMPLE_COLS = 20             # Number of horizontal positions to sample
BOTTOM_EXCLUSION_PX = 40            # Pixels above bottom to exclude for fish detection

# ── Capture Cadence ─────────────────────────────────────────────────
CAPTURE_INTERVAL_SEC = 600          # 10 minutes between captures
MIN_OVERLAP_SEC = 120               # Minimum acceptable overlap (2 min)
# Max interval such that two consecutive captures overlap by MIN_OVERLAP:
# If echogram shows 12 min of history: max interval = 720 - 120 = 600 sec
# We'll track actual overlap at capture time.

# ── NMEA Source ─────────────────────────────────────────────────────
NMEA_VESSEL_URL = "http://127.0.0.1:8654/vessel"
NMEA_TIMEOUT = 3

# ── Paths ───────────────────────────────────────────────────────────
WORKSPACE = Path(__file__).parent.resolve()
CAPTURES_DIR = WORKSPACE / "captures" / "v3"
SUMMARIES_DIR = WORKSPACE / "memory" / "summaries"
VOCAB_DIR = WORKSPACE / "memory" / "vocabulary"
CATCH_DIR = WORKSPACE / "memory" / "catches"
REANALYSIS_DIR = WORKSPACE / "memory" / "reanalysis"
```

### 3.2 Capture Daemon

```python
# capture_v3.py

"""
capture_v3.py — Full-frame dual-band capture daemon.

Cadence: every 10 minutes (configurable via CAPTURE_INTERVAL_SEC).
Each cycle:
  1. Capture full 1920×1080 frame → disk
  2. Crop and save LF band (x=8-945) 
  3. Crop and save HF band (x=950-1890)
  4. Fetch NMEA snapshot (lat, lon, SOG, COG)
  5. Generate overlap tracking record
  6. Trigger analyzer (synchronous or async)

Overlap tracking:
  - Each capture records: capture_window_sec = 720 (12 min echogram history)
  - Overlap between capture at T and capture at T-600 = 120 seconds
  - Overlap tracking enables stitching and cross-capture correlation
  
NMEA sync:
  - Fetch NMEA at capture time (± 0.5 sec)
  - Record position as "pin" — this capture happened HERE at THIS time
  - Store in both image metadata (EXIF) and summary record
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from screenshot import capture_full  # reuse from v1 — captures DISPLAY6
from config_v3 import (
    CAPTURE_INTERVAL_SEC, MIN_OVERLAP_SEC,
    LF_BAND, HF_BAND,
    CAPTURES_DIR, NMEA_VESSEL_URL,
)
from crop_bands import crop_lf_hf  # new module — crops both bands from one frame
from analyzer_v3 import analyze_bands  # text summary generation
from nmea_snapshot import fetch_nmea_snapshot  # structured NMEA record

log = logging.getLogger("tzpro.capture_v3")


async def capture_loop():
    """Main capture loop — 10-minute cadence."""
    CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
    
    last_capture_ts = 0.0
    
    while True:
        now = time.time()
        
        if now - last_capture_ts >= CAPTURE_INTERVAL_SEC:
            result = await capture_cycle()
            if result:
                log.info(
                    "Capture: %s | pos=(%.4f, %.4f) | SOG=%.1f",
                    result["frame_stem"],
                    result["nmea"].get("lat", 0),
                    result["nmea"].get("lon", 0),
                    result["nmea"].get("sog", 0),
                )
                last_capture_ts = now
            else:
                log.warning("Capture cycle failed")
        
        await asyncio.sleep(10)  # poll every 10 seconds


async def capture_cycle() -> dict | None:
    """One complete capture cycle.
    
    Returns dict with paths and metadata, or None on failure.
    """
    ts = datetime.now(timezone.utc)
    ts_iso = ts.isoformat(timespec="seconds")
    stem = ts.strftime("tzpro_%Y%m%d_%H%M%S")
    
    # 1. Capture full frame
    full = capture_full()
    if not full:
        return None
    
    # Rename to our stem-based naming
    frame_path = CAPTURES_DIR / f"{stem}_full.png"
    full.rename(frame_path)
    
    # 2. Crop both bands
    bands = crop_lf_hf(frame_path, LF_BAND, HF_BAND)
    if not bands:
        log.error("Band crop failed for %s", frame_path)
        return None
    
    lf_path, hf_path = bands  # saved as {stem}_lf.png, {stem}_hf.png
    
    # 3. Fetch NMEA snapshot
    nmea = fetch_nmea_snapshot()
    
    # 4. Build capture record
    capture_record = {
        "ts": ts_iso,
        "ts_unix": ts.timestamp(),
        "stem": stem,
        "frame_path": str(frame_path.name),
        "lf_path": str(lf_path.name),
        "hf_path": str(hf_path.name),
        "capture_window_sec": 720,  # 12 minutes of history on screen
        "nmea": nmea or {},
        "analysis": None,  # filled async or on next cycle
    }
    
    # 5. Trigger analysis (synchronous for now, could be background)
    analysis = analyze_bands(lf_path, hf_path, nmea)
    capture_record["analysis"] = analysis
    
    # 6. Write summary record
    _write_summary(stem, capture_record)
    
    return capture_record


def _write_summary(stem: str, record: dict):
    """Write the structured summary to disk."""
    import json
    from config_v3 import SUMMARIES_DIR
    SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
    
    path = SUMMARIES_DIR / f"{stem}_summary.json"
    with open(path, "w") as f:\n        json.dump(record, f, indent=2, default=str)\n```\n\n### 3.3 Band Cropping\n\n```python\n# crop_bands.py\n\n"""
crop_bands.py — Crop both LF and HF echogram bands from a full frame.

The white divider at x~945 is used as an alignment reference.
We crop strictly to the active echogram area, excluding UI elements.
"""

from pathlib import Path
from typing import Optional, Tuple

from PIL import Image


def crop_lf_hf(
    full_path: Path,
    lf_region: Tuple[int, int, int, int],
    hf_region: Tuple[int, int, int, int],
) -> Optional[Tuple[Path, Path]]:
    """Crop LF and HF bands from a full frame.
    
    Args:
        full_path: Path to full 1920×1080 frame
        lf_region: (x1, y1, x2, y2) for LF band
        hf_region: (x1, y1, x2, y2) for HF band
    
    Returns:
        (lf_path, hf_path) or None on failure
    """
    try:
        img = Image.open(full_path).convert("RGB")
        stem = full_path.stem.replace("_full", "")
        parent = full_path.parent
        
        # Crop LF
        lf_img = img.crop(lf_region)
        lf_path = parent / f"{stem}_lf.png"
        lf_img.save(lf_path)
        
        # Crop HF
        hf_img = img.crop(hf_region)
        hf_path = parent / f"{stem}_hf.png"
        hf_img.save(hf_path)
        
        return (lf_path, hf_path)
    
    except Exception as e:\n        import logging\n        logging.getLogger("tzpro.crop").error("Crop failed: %s", e)
        return None
```

### 3.4 Overlap Tracking

Because the echogram shows 12 minutes of scrolling history and we capture every 10 minutes, consecutive captures overlap by 2 minutes. This is a **feature**, not waste.

```
Capture 1 (T=0):     |████████████|  shows T-720 to T=0
Capture 2 (T=600):       |████████████|  shows T-120 to T=600
                      ^^^^^^
                   2 min overlap
```

The overlap is useful for:
1. **Stitching verification** — does the analysis in the overlap zone agree?
2. **Transition detection** — did something change during those 2 shared minutes?
3. **Confidence boosting** — if two analyses of the same time window agree, confidence rises

Overlap tracking is automatic: each capture records `capture_window_sec: 720` and its `ts_unix`. Any two captures where `|ts1 - ts2| < 720` overlap by `720 - |ts1 - ts2|` seconds.

---

## 4. Analyzer Design

### 4.1 Philosophy

The analyzer does NOT use pixel thresholds. Instead, it produces a **text summary** describing what's visible in the echogram. This text is searchable, appendable, and can be re-generated when the model learns something new.

The analysis pipeline has two stages:

**Stage 1: Pixel Analysis (deterministic, always available)**
- Detect the bottom return band (strongest horizontal signal)
- Read depth from scale markings (edge detection, tick counting)
- Compute vertical signal profile (intensity per depth zone)
- Detect significant horizontal bands (thermoclines, surface clutter)
- All output is structured numeric data

**Stage 2: Text Description (agent-generated, async)**
- Given pixel analysis + raw image, generate a natural-language description
- Describe: shapes, colors, depth ranges, bottom type, anomalies
- This is what gets searched, correlated, and appended
- Can be re-generated when vocabulary grows (retroactive analysis)

### 4.2 Pixel Analysis (Stage 1)

```python
# analyzer_v3.py — Stage 1: pixel analysis

"""
analyzer_v3.py — Dual-band echogram analysis pipeline.

Stage 1: Deterministic pixel analysis (always available, no AI needed)
Stage 2: Text description (agent-generated, can be re-run)

The analyzer produces a structured dict that feeds both:
  - The text summary (Stage 2 prompt context)
  - The multi-track timeline database
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional, Tuple, List
import numpy as np
from PIL import Image


# ── Constants (tuned for this display) ──────────────────────────────
QUIET_WATER_RGB_TOTAL = 131       # (0, 32, 99)
STRONG_RETURN_RGB_TOTAL = 350     # orange-red palette
VERY_STRONG_RGB_TOTAL = 400       # hard bottom

DEPTH_ZONES_FM = {
    "surface": (0, 5),
    "upper": (5, 20),
    "mid": (20, 40),
    "lower": (40, 60),
    "deep": (60, None),
}


def analyze_bands(
    lf_path: Path,
    hf_path: Path,
    nmea: dict
) -> dict:
    """Analyze both echogram bands and produce structured observations.
    
    Returns:
        dict with lf_analysis, hf_analysis, composite_analysis
    """
    result = {
        "lf": _analyze_single_band(lf_path),
        "hf": _analyze_single_band(hf_path, is_hf=True),
    }
    
    # Composite: combine information from both bands
    result["composite"] = _composite_analysis(result["lf"], result["hf"])
    
    return result


def _analyze_single_band(band_path: Path, is_hf: bool = False) -> dict:
    """Stage 1 analysis of one echogram band."""
    img = Image.open(band_path).convert("RGB")
    arr = np.array(img)  # shape (H, W, 3), values 0-255
    h, w, _ = arr.shape
    
    # ── 1. Vertical Signal Profile ──────────────────────────────────
    # Average across all columns to get a 1D depth-intensity profile
    rgb_total = arr.sum(axis=2)  # (H, W)
    horizontal_mean = rgb_total.mean(axis=1)  # (H,) — y-resolution signal
    
    # Normalize to 0-1
    sig_min = horizontal_mean.min()
    sig_max = horizontal_mean.max()
    signal_profile = ((horizontal_mean - sig_min) / (sig_max - sig_min + 1e-6)).tolist()
    
    # ── 2. Bottom Detection ─────────────────────────────────────────
    # The bottom is the strongest horizontal return — the row where 
    # signal intensity peaks and stays elevated for several pixels.
    # We look for the sharpest transition from high to low bottom-up.
    
    # Find the bottom row: scan from bottom, find first significant drop
    threshold_strong = 0.6  # 60% of max signal
    bottom_y = None
    bottom_confidence = "none"
    
    # Smooth the profile to find the main bottom band
    from scipy.ndimage import uniform_filter1d
    smooth = uniform_filter1d(horizontal_mean, size=5)
    
    # Find all regions above threshold
    above_thresh = smooth > (sig_min + threshold_strong * (sig_max - sig_min))
    
    if above_thresh.any():
        # The highest (closest to surface) strong return region
        bottom_indices = np.where(above_thresh)[0]
        # Group into contiguous regions
        regions = _contiguous_regions(bottom_indices)
        if regions:
            # The deepest strong region is likely the bottom
            deepest_region = regions[-1]
            bottom_y = int(deepest_region.mean())
            bottom_confidence = "high" if len(deepest_region) > 5 else "medium"
    
    # ── 3. Bottom Type Classification ───────────────────────────────
    bottom_type = "unknown"
    bottom_hardness = 0.0
    if bottom_y is not None:
        # Look at color channels in the bottom band
        band_start = max(0, bottom_y - 15)
        band_end = min(h, bottom_y + 15)
        bottom_band = arr[band_start:band_end, :, :]
        
        avg_r = float(bottom_band[:, :, 0].mean())
        avg_g = float(bottom_band[:, :, 1].mean())
        avg_b = float(bottom_band[:, :, 2].mean())
        
        # Blue palette interpretation:
        # - Red dominance → hard / rock
        # - Green dominance → medium / gravel-sand
        # - Blue dominance → soft mud / silt
        # - All low → very soft / deep
        max_ch = max(avg_r, avg_g, avg_b)
        if max_ch < 80:
            bottom_type = "very_soft"
            bottom_hardness = 0.1
        elif avg_r > 180 and avg_g > 100:
            bottom_type = "hard"
            bottom_hardness = 0.9
        elif avg_g > avg_r and avg_g > 130:
            bottom_type = "medium"
            bottom_hardness = 0.5
        elif avg_b > avg_r:\n            bottom_type = "soft_mud"
            bottom_hardness = 0.3
        else:
            bottom_type = "mixed"
            bottom_hardness = 0.5
    
    # ── 4. Depth Range Estimation ──────────────────────────────────
    # For now: proportional estimate assuming the depth scale covers
    # the full height of the band. In v3 we calibrate by reading the
    # depth scale markings on first known-stepped frame.
    depth_fm = None
    if bottom_y is not None:
        depth_fraction = bottom_y / h
        depth_fm = round(depth_fraction * 80, 1)  # assume 80 fm range
    
    # ── 5. Return Analysis by Depth Zone ────────────────────────────
    zone_returns = {}
    for zone_name, (z_min, z_max) in DEPTH_ZONES_FM.items():
        if z_max is None:
            z_max_fm = depth_fm if depth_fm else 80
        else:
            z_max_fm = z_max
        
        if depth_fm:
            z_min_px = int((z_min / depth_fm) * h) if depth_fm > 0 else 0
            z_max_px = int((z_max_fm / depth_fm) * h) if depth_fm > 0 else h
        else:
            z_min_px = int(z_min / 80 * h)
            z_max_px = int(z_max_fm / 80 * h)
        
        z_min_px = max(0, z_min_px)
        z_max_px = min(h, z_max_px)
        
        zone_pixels = arr[z_min_px:z_max_px, :, :]
        zone_signal = zone_pixels.sum(axis=2)  # (z_height, W)
        
        # Mean signal in zone
        zone_mean = float(zone_signal.mean())
        
        # Pixel count above threshold (return detected)
        above_bg = int((zone_signal > QUIET_WATER_RGB_TOTAL).sum())
        total_zone_px = zone_signal.size
        return_density = round(above_bg / total_zone_px, 3) if total_zone_px > 0 else 0
        
        zone_returns[zone_name] = {
            "mean_signal": round(zone_mean, 1),
            "return_density": return_density,
            "pixel_count_above_bg": above_bg,
        }
    
    # ── 6. Horizontal Band Detection (Thermoclines / Layers) ───────
    # Look for rows where horizontal intensity is uniform (low variance)
    # and significantly above background, indicating a horizontal layer.
    row_variances = np.var(rgb_total, axis=1)  # (H,) — variance across each row
    row_means = rgb_total.mean(axis=1)
    
    # Detect bands: low variance + high mean = uniform horizontal signal
    # Normalize both to detect the ratio
    bands = []
    for y in range(0, h, 2):  # sample every 2 rows
        if row_means[y] > QUIET_WATER_RGB_TOTAL * 1.5 and row_variances[y] < 2000:
            bands.append({
                "y": y,
                "depth_frac": round(y / h, 3),
                "mean_signal": round(float(row_means[y]), 1),
                "uniformity": round(float(row_variances[y]), 0),
            })
    
    # Group adjacent bands into layers
    layers = _group_bands_into_layers(bands)
    
    # ── 7. Shape Detection (for Stage 2 text prompt) ────────────────
    shapes = _detect_shapes(rgb_total, bottom_y, h, w)
    
    return {
        "band_type": "lf" if not is_hf else "hf",
        "width_px": w,
        "height_px": h,
        "bottom": {
            "y": bottom_y,
            "depth_fm": depth_fm,
            "type": bottom_type,
            "hardness": bottom_hardness,
            "confidence": bottom_confidence,
        },
        "signal_profile": signal_profile,
        "zone_returns": zone_returns,
        "horizontal_layers": layers,
        "shapes": shapes,
        "color_summary": _color_summary(arr),
    }


def _contiguous_regions(indices: np.ndarray) -> list[np.ndarray]:
    """Split sorted indices into contiguous groups (gap > 1 = separator)."""
    if len(indices) == 0:
        return []
    regions = []
    start = 0
    for i in range(1, len(indices)):
        if indices[i] - indices[i-1] > 1:
            regions.append(indices[start:i])
            start = i
    regions.append(indices[start:])
    return regions


def _group_bands_into_layers(bands: list) -> list:
    """Group adjacent detected bands into named layers."""
    if not bands:
        return []
    
    layers = []
    current = [bands[0]]
    
    for b in bands[1:]:
        if b["y"] - current[-1]["y"] <= 5:
            current.append(b)
        else:
            layers.append(_summarize_layer(current))
            current = [b]
    
    layers.append(_summarize_layer(current))
    return layers


def _summarize_layer(bands: list) -> dict:
    """Summarize a group of adjacent band rows."""
    ys = [b["y"] for b in bands]
    signals = [b["mean_signal"] for b in bands]
    return {
        "y_center": int(np.mean(ys)),
        "depth_frac": round(np.mean([b["depth_frac"] for b in bands]), 3),
        "thickness_px": max(ys) - min(ys) + 1,
        "mean_signal": round(float(np.mean(signals)), 1),
        "uniformity": round(float(np.mean([b["uniformity"] for b in bands])), 0),
    }


def _detect_shapes(
    rgb_total: np.ndarray,
    bottom_y: int | None,
    h: int, w: int
) -> dict:
    """Detect echogram shapes — arches, columns, scattered blobs.
    
    Returns categorized shapes for the text description prompt.
    This is a heuristic; the agent description (Stage 2) refines it.
    """
    if bottom_y is None:
        return {"columns": [], "arches": [], "scatter_zones": []}
    
    # Exclude bottom band
    water_column = rgb_total[:max(0, bottom_y - 40), :]
    if water_column.size == 0:
        return {"columns": [], "arches": [], "scatter_zones": []}
    
    # Threshold for significant returns
    mask = water_column > QUIET_WATER_RGB_TOTAL * 2
    
    # Find vertical columns (returns spanning multiple rows at same x)
    # and scattered zones
    from scipy.ndimage import label as nd_label
    from scipy.ndimage import find_objects
    
    labeled, num_features = nd_label(mask)
    
    columns = []
    for i in range(1, num_features + 1):
        region_slice = find_objects(labeled == i)[0]
        ry = region_slice[0]
        rx = region_slice[1]
        
        height_px = ry.stop - ry.start
        width_px = rx.stop - rx.start
        area_px = height_px * width_px
        aspect = height_px / max(width_px, 1)
        
        shape_type = "blob"
        if aspect > 2.0 and height_px > 20:
            shape_type = "column"
        elif width_px > 30 and height_px < 20:
            shape_type = "band"
        elif aspect > 0.5 and aspect < 2.0 and width_px > 10:
            shape_type = "arch_like"
        
        columns.append({
            "x": rx.start,
            "x_width": width_px,
            "y_center": (ry.start + ry.stop) // 2,
            "height": height_px,
            "area": area_px,
            "shape": shape_type,
        })
    
    return {
        "total_regions": num_features,
        "columns": [c for c in columns if c["shape"] == "column"],
        "arches": [c for c in columns if c["shape"] == "arch_like"],
        "blobs": [c for c in columns if c["shape"] == "blob"],
        "bands": [c for c in columns if c["shape"] == "band"],
    }


def _color_summary(arr: np.ndarray) -> dict:
    """Dominant colors and palette information."""
    avg_r = float(arr[:, :, 0].mean())
    avg_g = float(arr[:, :, 1].mean())
    avg_b = float(arr[:, :, 2].mean())
    
    return {
        "avg_rgb": [round(avg_r, 1), round(avg_g, 1), round(avg_b, 1)],
        "palette_dominance": "red" if avg_r > max(avg_g, avg_b) 
                              else "green" if avg_g > avg_b 
                              else "blue",
        "signal_strength": round((avg_r + avg_g + avg_b) / (255 * 3), 3),
    }


def _composite_analysis(lf: dict, hf: dict) -> dict:
    """Combine LF and HF analysis into a single picture."""
    
    # Active band: which one has more signal
    lf_sig = lf.get("color_summary", {}).get("signal_strength", 0)
    hf_sig = hf.get("color_summary", {}).get("signal_strength", 0)
    
    active_band = "lf" if lf_sig > hf_sig * 1.5 else "both" if lf_sig > 0 and hf_sig > 0 else "neither"
    
    # Best bottom reading (LF usually more reliable)
    lf_bottom = lf.get("bottom", {})
    hf_bottom = hf.get("bottom", {})
    
    best_bottom = lf_bottom if lf_bottom.get("confidence") in ("high", "medium") else hf_bottom
    
    # Zones — use the more informative band for each zone
    lf_zones = lf.get("zone_returns", {})
    hf_zones = hf.get("zone_returns", {})
    
    enriched_zones = {}
    for zone in list(DEPTH_ZONES_FM.keys()):
        lf_z = lf_zones.get(zone, {})
        hf_z = hf_zones.get(zone, {})
        
        if lf_z.get("return_density", 0) > hf_z.get("return_density", 0):
            enriched_zones[zone] = {**lf_z, "best_band": "lf"}
        else:
            enriched_zones[zone] = {**hf_z, "best_band": "hf"}
    
    return {
        "active_band": active_band,
        "best_bottom": best_bottom,
        "enriched_zones": enriched_zones,
        "lf_signal": lf_sig,
        "hf_signal": hf_sig,
    }
```

### 4.3 Text Description (Stage 2)

The Stage 2 analysis is a **text description** generated by an LLM agent. It takes the Stage 1 pixel analysis as structured context and produces a human-readable, searchable description.

```
Stage 2 Prompt Template:

    You are analyzing a dual-band fishfinder echogram.
    
    === Pixel Analysis (Structured) ===
    {json.dumps(stage1_result, indent=2)}
    
    === Context ===
    Position: {lat}, {lon}
    SOG: {sog} kn
    Time: {ts_iso}
    
    === Report ===
    Write a concise text description covering:
    
    1. Bottom — depth, type, confidence. Is the bottom clear or diffuse?
    2. Water column — signal strength per depth zone. Any fish arches or columns?
    3. Shapes — describe any interesting shapes (columns, arches, clouds, bands)
       with their depth range. Color notes (yellow-green, orange, red).
    4. LF vs HF comparison — which band shows more activity? Where?
    5. Anomalies — anything unusual? Missing bottom? Sudden shallow? Pattern
       changes within the 12-minute window?
    6. Vocabulary tags — 3-5 short tags for search. Examples:
       ["chum_arch", "mid_column_25fm", "hard_bottom_gradient"]
    
    Format as a structured JSON object with these fields:
    {{
      "description": "2-3 paragraph summary",
      "bottom_estimate": {{"depth_fm": float, "type": str, "confidence": str}},
      "shapes": [{{"type": str, "depth_range": [float, float], "description": str}}],
      "comparison": "text comparing LF and HF bands",
      "anomalies": ["text describing anything unusual"],
      "vocabulary_tags": ["tag1", "tag2", "tag3"]
    }}
```

The Stage 2 output is stored alongside the Stage 1 analysis. It can be **re-generated later** when the model learns new vocabulary, without re-capturing the image.

### 4.4 Depth Scale Calibration

The depth scale on the right edge of the HF band (x~1870-1890) shows tick marks and numbers in fathoms. We need to calibrate pixel-y → depth-fm.

**Approach:** One-time calibration on the first known-stepped frame (a frame with clear depth markings visible). The Captain can help by reading the visible depth numbers.

```python
# depth_calibrate.py

"""
depth_calibrate.py — Calibrate pixel Y to depth in fathoms.

On first capture with visible depth scale markings, the system
requests calibration from the agent or Captain. The result is cached.

Calibration result example:
    {
        "pixel_ranges": {0: 0, 216: 10, 432: 20, 648: 30, 864: 40, 1080: 50},
        "pixels_per_fm": 21.6,
        "calibration_ts": "2026-07-17T09:15:00+00:00",
        "source": "captain_read"
    }
"""

CALIBRATION_CACHE = {}


def pixel_y_to_depth(y: int, h: int, calibration: dict | None = None) -> float | None:
    """Convert pixel Y position to depth in fathoms.
    
    Uses calibration data if available, otherwise proportional estimate.
    """
    if calibration and "pixels_per_fm" in calibration:
        return round(y / calibration["pixels_per_fm"], 1)
    
    # Fallback: proportional
    frac = y / h
    return round(frac * 80, 1)  # assume 80 fm range
```

---

## 5. Text Summary Schema

### 5.1 Capture Summary (Per Cycle)

Saved to `memory/summaries/{stem}_summary.json`:

```json
{
  "ts": "2026-07-17T09:00:00+00:00",
  "ts_unix": 1721214000.0,
  "stem": "tzpro_20260717_090000",
  
  "capture": {
    "frame_path": "tzpro_20260717_090000_full.png",
    "lf_path": "tzpro_20260717_090000_lf.png",
    "hf_path": "tzpro_20260717_090000_hf.png",
    "capture_window_sec": 720
  },
  
  "nmea": {
    "lat": 55.3422,
    "lon": -131.6433,
    "sog": 7.2,
    "cog": 215.0,
    "timestamp": "2026-07-17T09:00:01+00:00"
  },
  
  "analysis": {
    "stage1": {
      "lf": {
        "band_type": "lf",
        "bottom": {
          "y": 490,
          "depth_fm": 36.3,
          "type": "medium",
          "hardness": 0.5,
          "confidence": "high"
        },
        "zone_returns": {
          "surface": {"mean_signal": 185.2, "return_density": 0.15},
          "upper": {"mean_signal": 155.0, "return_density": 0.08},
          "mid": {"mean_signal": 220.4, "return_density": 0.42},
          "lower": {"mean_signal": 290.1, "return_density": 0.65},
          "deep": {"mean_signal": 340.0, "return_density": 0.88}
        },
        "horizontal_layers": [
          {"y_center": 30, "depth_frac": 0.028, "thickness_px": 8, "mean_signal": 210.0}
        ],
        "shapes": {
          "total_regions": 12,
          "columns": [
            {"x": 150, "x_width": 18, "y_center": 320, "height": 45, "area": 810, "shape": "column"}
          ],
          "arches": [],
          "blobs": [
            {"x": 400, "x_width": 35, "y_center": 280, "height": 22, "area": 770, "shape": "blob"}
          ],
          "bands": []
        },
        "color_summary": {
          "avg_rgb": [85.2, 110.3, 78.4],
          "palette_dominance": "green",
          "signal_strength": 0.358
        }
      },
      "hf": {
        "band_type": "hf",
        "bottom": {
          "y": 505,
          "depth_fm": 37.4,
          "type": "soft_mud",
          "hardness": 0.3,
          "confidence": "medium"
        },
        "zone_returns": {
          "surface": {"mean_signal": 140.0, "return_density": 0.05}
        },
        "color_summary": {
          "avg_rgb": [32.1, 55.0, 95.2],
          "palette_dominance": "blue",
          "signal_strength": 0.238
        }
      },
      "composite": {
        "active_band": "lf",
        "best_bottom": {
          "y": 490, "depth_fm": 36.3, "type": "medium", "hardness": 0.5, "confidence": "high"
        },
        "enriched_zones": {
          "surface": {"mean_signal": 185.2, "return_density": 0.15, "best_band": "lf"},
          "upper": {"mean_signal": 155.0, "return_density": 0.08, "best_band": "lf"},
          "mid": {"mean_signal": 220.4, "return_density": 0.42, "best_band": "lf"},
          "lower": {"mean_signal": 290.1, "return_density": 0.65, "best_band": "lf"},
          "deep": {"mean_signal": 340.0, "return_density": 0.88, "best_band": "lf"}
        },
        "lf_signal": 0.358,
        "hf_signal": 0.238
      }
    },
    
    "stage2": {
      "description": "Medium strength returns on LF band with consistent bottom at 36 fm. Bottom type is mixed — suggests gravel-sand transition. Water column shows moderate activity in mid and lower zones: a column-shaped return at x=150 extending from 24-27 fm suggests a fish school or bait column. HF band is mostly quiet (uniform dark blue), indicating returns are primarily low-frequency. No thermocline layers detected. Strongest signal zone is the lower water column (0.65 return density), consistent with demersal fish holding near bottom. Surface clutter minimal.",
      "bottom_estimate": {
        "depth_fm": 36.3,
        "type": "medium",
        "confidence": "high"
      },
      "shapes": [
        {
          "type": "column",
          "depth_range": [24.0, 27.0],
          "description": "Vertical column of returns at left side of LF band, ~45px tall, yellow-green intensity. Possible bait column or small school."
        },
        {
          "type": "blob",
          "depth_range": [20.0, 22.0],
          "description": "Scattered blob mid-water on LF, ~35px wide, moderate intensity. Scattered fish or debris."
        }
      ],
      "comparison": "LF band shows moderate activity throughout water column with strong bottom return. HF band is nearly quiet — only faint surface clutter visible. This is typical for low-frequency dominant returns (deeper water, smaller targets not resolved by HF).",
      "anomalies": [
        "No thermocline layers detected — water column appears well-mixed",
        "HF band bottom is softer than LF band bottom by one classification level"
      ],
      "vocabulary_tags": [
        "mid_column_soft_return",
        "mixed_bottom_36fm",
        "hf_quiet",
        "lf_active_lower_zone"
      ]
    }
  }
}
```

### 5.2 Master Index (`memory/summaries/index.json`)

A fast-lookup index that maps timestamps to stem names. Updated on each capture.

```json
{
  "captures": [
    {"ts": "2026-07-17T09:00:00+00:00", "stem": "tzpro_20260717_090000", "bottom_fm": 36.3},
    {"ts": "2026-07-17T09:10:00+00:00", "stem": "tzpro_20260717_091000", "bottom_fm": 42.1},
    {"ts": "2026-07-17T09:20:00+00:00", "stem": "tzpro_20260717_092000", "bottom_fm": 38.7}
  ],
  "catch_events": [
    {"ts": "2026-07-17T10:15:00+00:00", "species": "chum", "count": 3, "depth_fm": 35}
  ],
  "last_updated": "2026-07-17T10:30:00+00:00"
}
```

---

## 6. Multi-Track Correlation

### 6.1 Data Model

All tracks share the `ts_unix` (float seconds) as the primary key. Any operation on a time range pulls from all tracks.

```
Track 1 (LF Images):    /captures/v3/{stem}_lf.png
Track 2 (HF Images):    /captures/v3/{stem}_hf.png
Track 3 (NMEA):         embedded in summary JSON
Track 4 (Text Summary): /memory/summaries/{stem}_summary.json (stage2.description)
Track 5 (Catch Events): /memory/catches/{date}.jsonl
Track 6 (Vocabulary):   /memory/vocabulary/patterns.json
```

### 6.2 Time Range Query

```python
# correlation.py — Multi-track time range query

"""
correlation.py — Query all tracks for a time range.

Given a time range (t_start, t_end), return:
  - All capture summaries in that range
  - All catch events in that range
  - Any vocabulary matches that overlap
  - NMEA pin for each capture

Used by:
  - Agent for answering "what was happening at X time?"
  - Re-analysis batch jobs
  - Vocabulary matching queries
"""


def query_time_range(
    t_start: float, t_end: float
) -> dict:
    """Query all tracks for a time range.
    
    Returns:
        dict with captures, catch_events, vocabulary_matches
    """
    # 1. Load capture summaries
    captures = _load_captures_in_range(t_start, t_end)
    
    # 2. Load catch events
    catch_events = _load_catches_in_range(t_start, t_end)
    
    # 3. Load vocabulary matches
    vocab_matches = _load_vocab_matches_in_range(t_start, t_end)
    
    return {
        "time_range": [t_start, t_end],
        "captures": captures,
        "catch_events": catch_events,
        "vocabulary_matches": vocab_matches,
    }


def _load_captures_in_range(t_start: float, t_end: float) -> list[dict]:
    """Load all capture summaries between t_start and t_end."""
    import json
    from pathlib import Path
    from config_v3 import SUMMARIES_DIR
    
    captures = []
    for f in sorted(SUMMARIES_DIR.glob("*_summary.json")):
        data = json.loads(f.read_text())
        ts = data.get("ts_unix")
        if ts and t_start <= ts <= t_end:
            captures.append(data)
    
    return captures
```

### 6.3 Retroactive Re-Analysis

When the model learns a new concept or vocabulary term, old captures can be re-analyzed.

```python
# reanalysis.py — Batch re-analysis with new vocabulary

"""
reanalysis.py — Retroactive re-analysis of old captures.

When the vocabulary grows (new pattern discovered), run:
    python reanalysis.py --with-vocabulary chum_arch --date-range 2026-07-15:2026-07-17

This re-generates Stage 2 text analysis for all captures in the range,
using the current vocabulary and patterns.

Old analyses are not deleted — new ones saved alongside with a version tag.
"""


def reanalyze_stage2(
    stem: str,
    new_vocabulary: list[str],
    version: int,
) -> dict:
    """Re-run Stage 2 analysis with updated vocabulary.
    
    Loads the existing Stage 1 pixel analysis, feeds it to the LLM
    with new vocabulary context, and saves the new Stage 2 result.
    """
    import json
    from config_v3 import SUMMARIES_DIR, REANALYSIS_DIR
    
    # Load existing summary
    summary_path = SUMMARIES_DIR / f"{stem}_summary.json"
    if not summary_path.exists():
        return {"error": f"No summary for {stem}"}
    
    summary = json.loads(summary_path.read_text())
    
    # Re-run Stage 2 with new vocabulary context
    new_stage2 = _run_stage2_with_vocab(
        stage1=summary["analysis"]["stage1"],
        nmea=summary.get("nmea", {}),
        ts=summary.get("ts", ""),
        vocabulary=new_vocabulary,
    )
    
    # Save as re-analysis
    REANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    reanalysis = {
        **summary,
        "analysis": {
            **summary["analysis"],
            f"stage2_v{version}": new_stage2,
            "stage2": new_stage2,  # also update default
        },
        "reanalysis_version": version,
        "reanalysis_ts": datetime.now(timezone.utc).isoformat(),
    }
    
    result_path = REANALYSIS_DIR / f"{stem}_v{version}.json"
    with open(result_path, "w") as f:\n        json.dump(reanalysis, f, indent=2, default=str)\n    \n    return reanalysis\n\n\ndef batch_reanalyze(\n    vocabulary: list[str],
    date_range: tuple[str, str] | None = None,
    version: int | None = None,
):
    """Batch re-analyze all captures in date range with new vocabulary."""
    import json
    from config_v3 import SUMMARIES_DIR
    from datetime import datetime
    
    if version is None:
        version = int(datetime.now().timestamp())
    
    # Collect all summaries
    stems = []
    for f in sorted(SUMMARIES_DIR.glob("*_summary.json")):
        stem = f.stem.replace("_summary", "")
        stems.append(stem)
    
    # If date range provided, filter
    if date_range:
        start_dt = datetime.strptime(date_range[0], "%Y-%m-%d")
        end_dt = datetime.strptime(date_range[1], "%Y-%m-%d")
        stems = [s for s in stems if start_dt <= datetime.strptime(s[6:14], "%Y%m%d") <= end_dt]
    
    results = []
    for stem in stems:
        result = reanalyze_stage2(stem, vocabulary, version)
        results.append(result)
    
    return results
```

### 6.4 Label Propagation

When the Captain reports a catch at time T with species S and depth D:\n1. Find the capture nearest to time T (within ±5 min)\n2. Link the catch to that capture's summary\n3. Compute feature vector from the Stage 1 analysis\n4. Store the labeled feature vector in the vocabulary database

```python
# label_propagation.py

"""
label_propagation.py — Link captain catch reports to closest echogram captures.

When a catch is logged:
  1. Find the capture nearest in time (±5 min tolerance)
  2. Extract feature vector from Stage 1 analysis
  3. Store labeled vector in vocabulary database
  4. Optionally flag whether the Stage 2 text mentioned fish at that depth
"""


def propagate_catch_label(
    catch_ts: float,
    species: str,
    count: int,
    reported_depth_fm: float | None,
) -> dict:
    """Link a catch event to the closest capture and extract labeled features."""
    import json
    from config_v3 import SUMMARIES_DIR
    
    # Find closest capture summary
    closest = None
    min_delta = 300  # 5 minutes max
    
    for f in SUMMARIES_DIR.glob("*_summary.json"):
        data = json.loads(f.read_text())
        delta = abs(data["ts_unix"] - catch_ts)
        if delta < min_delta:
            min_delta = delta
            closest = data
    
    if closest is None:
        return {"error": "No capture within 5 minutes of catch"}
    
    # Extract feature vector from Stage 1
    stage1 = closest["analysis"]["stage1"]
    features = _extract_labeled_features(stage1, species, reported_depth_fm)
    
    # Store in vocabulary database
    _store_labeled_pattern(features)
    
    return {
        "species": species,
        "count": count,
        "capture_stem": closest["stem"],
        "time_delta_sec": min_delta,
        "features": features,
    }


def _extract_labeled_features(stage1: dict, species: str, depth_fm: float | None) -> dict:
    """Extract a feature vector suitable for similarity search.
    
    Feature vector (64-element, normalized):
      - bottom_depth_fm (1)
      - bottom_hardness (1)
      - bottom_confidence_score (1)
      - zone_return_density × 5 zones (5)
      - zone_mean_signal × 5 zones (5)
      - shape_counts × 4 types (4)
      - shape_area_sum (1)
      - horizontal_layer_count (1)
      - horizontal_layer_mean_signal (1)
      - color_summary_rgb (3)
      - signal_profile_sampled × 42 bins after bottom (42)
      - Total: 64
    """
    composite = stage1.get("composite", {})
    lf = stage1.get("lf", {})
    
    bottom = composite.get("best_bottom", lf.get("bottom", {}))
    zones = composite.get("enriched_zones", lf.get("zone_returns", {}))
    shapes = lf.get("shapes", {})
    layers = lf.get("horizontal_layers", [])
    color = lf.get("color_summary", {})
    profile = lf.get("signal_profile", [])
    
    # bottom_y to rescale profile
    bottom_y = bottom.get("y")
    
    vector = []
    
    # 1. Bottom
    vector.append(bottom.get("depth_fm", 0) / 80.0)  # normalize to 0-1
    vector.append(bottom.get("hardness", 0))
    conf_map = {"high": 1.0, "medium": 0.6, "low": 0.3, "none": 0.0}
    vector.append(conf_map.get(bottom.get("confidence", "none"), 0))
    
    # 2. Zone returns
    for zone_name in ["surface", "upper", "mid", "lower", "deep"]:
        z = zones.get(zone_name, {})
        vector.append(z.get("return_density", 0))
    for zone_name in ["surface", "upper", "mid", "lower", "deep"]:
        z = zones.get(zone_name, {})
        vector.append(min(z.get("mean_signal", 0) / 400.0, 1.0))
    
    # 3. Shapes
    for st in ["columns", "arches", "blobs", "bands"]:
        vector.append(len(shapes.get(st, [])) / 50.0)
    
    total_area = sum(
        s.get("area", 0) / 10000.0
        for st in ["columns", "arches", "blobs", "bands"]
        for s in shapes.get(st, [])
    )
    vector.append(min(total_area, 1.0))
    
    # 4. Horizontal layers
    vector.append(len(layers) / 10.0)
    if layers:
        vector.append(min(max(l[-1]["mean_signal"] for l in layers) / 400.0, 1.0))
    else:
        vector.append(0.0)
    
    # 5. Color summary
    vector.append(min(color.get("avg_rgb", [0, 0, 0])[0] / 255.0, 1.0))
    vector.append(min(color.get("avg_rgb", [0, 0, 0])[1] / 255.0, 1.0))
    vector.append(min(color.get("avg_rgb", [0, 0, 0])[2] / 255.0, 1.0))
    
    # 6. Signal profile (sample 42 bins above bottom)
    if bottom_y and profile:
        profile_above = profile[:bottom_y] if bottom_y < len(profile) else profile
        # Resample to 42 bins
        sampled = np.interp(
            np.linspace(0, len(profile_above) - 1, 42),
            np.arange(len(profile_above)),
            profile_above
        ).tolist() if len(profile_above) > 1 else [0.0] * 42
        vector.extend(sampled)
    else:
        vector.extend([0.0] * 42)
    
    return {
        "species": species,
        "reported_depth_fm": depth_fm,
        "vector": vector,
        "dimensionality": len(vector),  # should be 64
    }
```

---

## 7. Storage Strategy

### 7.1 Directory Layout

```
tzpro-agent/
├── captures/
│   └── v3/
│       ├── tzpro_20260717_090000_full.png    # Full frame (1920×1080) — large, less frequent
│       ├── tzpro_20260717_090000_lf.png      # LF band crop (~930×1080)
│       ├── tzpro_20260717_090000_hf.png      # HF band crop (~940×1080)
│       ├── tzpro_20260717_091000_full.png
│       ├── tzpro_20260717_091000_lf.png
│       └── tzpro_20260717_091000_hf.png
│
├── memory/
│   ├── summaries/
│   │   ├── tzpro_20260717_090000_summary.json   # Full summary (Stage 1 + Stage 2)
│   │   ├── tzpro_20260717_091000_summary.json
│   │   └── index.json                           # Fast-lookup index
│   │
│   ├── catches/
│   │   └── 2026-07-17.jsonl                     # Catch events per day
│   │
│   ├── vocabulary/
│   │   ├── patterns.json                         # Learned feature vectors with labels
│   │   ├── calibration.json                      # Depth scale calibration
│   │   └── match_history.jsonl                   # Every match attempt + confidence
│   │
│   └── reanalysis/
│       ├── tzpro_20260715_105941_v1.json         # Re-analysis version 1
│       └── tzpro_20260715_105941_v2.json         # Re-analysis version 2
│
└── config_v3.py                                   # New layout constants
```

### 7.2 Storage Budget

| Data Type | Per Capture | Per Day (6/hr × 16h) | Per Season (90 days) |
|-----------|-------------|----------------------|----------------------|
| Full frame (PNG) | ~1.7 MB | ~27 MB | ~2.4 GB |
| LF band (PNG) | ~250 KB (estimated) | ~4 MB | ~360 MB |
| HF band (PNG) | ~250 KB (estimated) | ~4 MB | ~360 MB |
| JSON summary | ~5 KB | ~80 KB | ~7 MB |
| Index | — | ~2 KB | ~180 KB |
| Catch events | — | ~1 KB | ~90 KB |
| Vocabulary | — | ~5 KB | ~450 KB |
| **Total** | **~2.2 MB** | **~35 MB** | **~3.2 GB** |

**Over a full season:** ~3.2 GB of storage. Manageable on any modern SSD.
Full frames can be optionally archived to compress after 30 days (e.g. `jpg --quality 85` → ~200 KB each, saving ~2 GB/season).

### 7.3 Image Retention Policy

```
┌─────────────────────────────────────────────────────────────────────┐
│ Capture → Full frame + LF + HF saved                               │
│    ↓                                                                │
│ After 30 days: full frames optionally compressed (jpg q85)         │
│    ↓                                                                │
│ After 1 year: full frames moved to cold storage                     │
│    ↓                                                                │
│ Forever: LF + HF bands + all summaries + vocabulary retained        │
│    (These are the primary analysis artifacts — small, lossless)     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 8. Vocabulary Building

### 8.1 The Learning Loop

```
                      ┌──────────────────────┐
                      │  Capture + Analyze    │
                      │  (every 10 min)       │
                      └──────┬───────────────┘
                             │ Stage 1 + Stage 2
                             ▼
                      ┌──────────────────────┐
                      │  Vocabulary Match     │◄──── patterns.json
                      │  (compare 64-dim vec  │
                      │   to labeled patterns)│
                      └──────┬───────────────┘
                             │
                             │ No match found        │ Match found
                             ▼                        ▼
                      ┌──────────────┐      ┌──────────────────┐
                      │ Log as       │      │ Log match with   │
                      │ unlabeled    │      │ confidence score │
                      └──────────────┘      └────────┬─────────┘
                                                      │ If confidence
                                                      │ > threshold
                                                      ▼
                                               ┌──────────────────┐
                                               │ Suggest to        │
                                               │ Captain: "This   │
                                               │ looks like X%    │
                                               │ match to chum"   │
                                               └──────────────────┘

                      ┌──────────────────────┐
                      │  Captain catches fish │
                      │  (reports species,    │
                      │   count, depth)       │
                      └──────┬───────────────┘
                             │
                             ▼
                      ┌──────────────────────┐
                      │  Label Propagation    │
                      │  Link catch to nearest│
                      │  capture, extract     │
                      │  feature vector,      │
                      │  store in patterns    │
                      └──────┬───────────────┘
                             │
                             ▼
                      ┌──────────────────────┐
                      │  Update Vocabulary    │
                      │  → stronger confidence│
                      │  → ability to spot    │
                      │    similar patterns   │
                      └──────────────────────┘
```

### 8.2 Vocabulary Database Schema

Stored in `memory/vocabulary/patterns.json`:

```json
{
  "version": 3,
  "last_updated": "2026-07-17T14:00:00+00:00",
  "patterns": [
    {
      "id": "pat_001",
      "species": "chum",
      "feature_vector": [0.45, 0.5, 1.0, ...],  // 64 elements
      "labeled_captures": [
        {"stem": "tzpro_20260717_101000", "catch_ts": "2026-07-17T10:15:00+00:00", "count": 3, "depth_fm": 35}
      ],
      "confidence": 0.75,
      "times_matched": 0,
      "last_match_ts": null,
      "notes": "Chum at 35 fm, mid-column returns, medium bottom"
    },
    {
      "id": "pat_002",
      "species": "halibut",
      "feature_vector": [0.62, 0.8, 1.0, ...],
      "labeled_captures": [
        {"stem": "tzpro_20260716_141000", "catch_ts": "2026-07-16T14:22:00+00:00", "count": 1, "depth_fm": 48}
      ],
      "confidence": 0.60,
      "times_matched": 0,
      "last_match_ts": null,
      "notes": "Halibut on hard bottom at 48 fm — single labeled capture, needs more data"
    }
  ]
}
```

### 8.3 Similarity Matching

```python
# vocabulary.py

"""
vocabulary.py — Similarity matching against labeled patterns.

Core matching logic:
  1. Extract 64-dim feature vector from Stage 1 analysis
  2. Compute cosine similarity against all labeled patterns
  3. Return top 3 matches with confidence scores
  4. If any match > threshold, log and optionally surface to Captain

Confidence scoring:
  - Cosine similarity × (1 - 1/(n+1)) where n = number of labeled captures
  - This weights down patterns with very few data points
  - Minimum 2 labeled captures to produce any match
"""

import json
import math
from pathlib import Path
from typing import Optional
from config_v3 import VOCAB_DIR


def match_vocabulary(
    feature_vector: list[float],
    threshold: float = 0.65,
    min_labeled_captures: int = 1,
) -> list[dict]:
    """Match a feature vector against the vocabulary.
    
    Args:
        feature_vector: 64-dim vector from current capture
        threshold: minimum cosine similarity to consider a match
        min_labeled_captures: minimum labeled captures for a pattern
    
    Returns:
        List of matches, sorted by confidence descending.
        Each match has: species, confidence, capture_stems, depth_fm
    """
    patterns = _load_patterns()
    matches = []
    
    for pat in patterns["patterns"]:
        if len(pat["labeled_captures"]) < min_labeled_captures:
            continue
        
        similarity = _cosine_similarity(feature_vector, pat["feature_vector"])
        if similarity < threshold:
            continue
        
        # Confidence = similarity × label count factor
        n = len(pat["labeled_captures"])
        label_factor = 1 - (1 / (n + 1))  # 0.5 at n=1, 0.67 at n=2, 0.8 at n=4
        confidence = round(similarity * label_factor, 3)
        
        # Average depth if captures reported depth
        depths = [c.get("depth_fm") for c in pat["labeled_captures"] if c.get("depth_fm")]
        avg_depth = round(sum(depths) / len(depths), 1) if depths else None
        
        matches.append({
            "pattern_id": pat["id"],
            "species": pat["species"],
            "confidence": confidence,
            "labeled_captures": n,
            "avg_reported_depth_fm": avg_depth,
        })
    
    # Sort by confidence descending
    matches.sort(key=lambda m: m["confidence"], reverse=True)
    
    # Log match attempt
    _log_match_attempt(feature_vector, matches)
    
    return matches


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(ai * bi for ai, bi in zip(a, b))
    norm_a = math.sqrt(sum(ai * ai for ai in a))
    norm_b = math.sqrt(sum(bi * bi for bi in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _load_patterns() -> dict:
    """Load vocabulary patterns from disk."""
    path = VOCAB_DIR / "patterns.json"
    if not path.exists():
        return {"version": 1, "last_updated": None, "patterns": []}
    return json.loads(path.read_text())


def _save_patterns(patterns: dict):
    """Save vocabulary patterns to disk."""
    VOCAB_DIR.mkdir(parents=True, exist_ok=True)
    path = VOCAB_DIR / "patterns.json"
    patterns["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(path, "w") as f:\n        json.dump(patterns, f, indent=2)\n\n\ndef _log_match_attempt(vector: list[float], matches: list[dict]):
    """Log every vocabulary match attempt to match_history.jsonl."""
    from datetime import datetime, timezone
    import json as j
    
    VOCAB_DIR.mkdir(parents=True, exist_ok=True)
    path = VOCAB_DIR / "match_history.jsonl"
    
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "vector_preview": vector[:5],  # just first 5 for identification
        "matches": matches,
    }
    
    with open(path, "a") as f:\n        f.write(j.dumps(entry) + "\n")


def add_labeled_pattern(
    species: str,
    feature_vector: list[float],
    capture_stem: str,
    catch_ts: str,
    count: int,
    depth_fm: float | None,
) -> dict:
    """Add a labeled pattern to the vocabulary.
    
    If a pattern for this species already exists, appends the capture
    evidence. If not, creates a new pattern entry.
    """
    patterns = _load_patterns()
    
    merged_vector = feature_vector  # for now, use as-is; later could average
    
    # Check if pattern exists for this species
    existing = [p for p in patterns["patterns"] if p["species"] == species]
    
    new_capture_entry = {
        "stem": capture_stem,
        "catch_ts": catch_ts,
        "count": count,
        "depth_fm": depth_fm,
    }
    
    if existing:
        pat = existing[0]
        if new_capture_entry not in pat["labeled_captures"]:
            pat["labeled_captures"].append(new_capture_entry)
            pat["confidence"] = min(1.0, pat["confidence"] + 0.05)
        return pat
    else:
        pat = {
            "id": f"pat_{len(patterns['patterns']) + 1:04d}",
            "species": species,
            "feature_vector": feature_vector,
            "labeled_captures": [new_capture_entry],
            "confidence": 0.5,
            "times_matched": 0,
            "last_match_ts": None,
            "notes": f"First labeled capture for {species}",
        }
        patterns["patterns"].append(pat)
        _save_patterns(patterns)
        return pat
```

### 8.4 Surfacing Matches to the Captain

When a vocabulary match exceeds confidence threshold:

```
Captain → "Hey, I caught chum at 35 fm"
System → stores pattern
         ... 3 days later ...
System → "This capture (position X at Y) shows a 73% match to the
          chum pattern you logged on July 17 at 35 fm. Mid-column
          return structure, medium bottom. Worth checking."
```

This is a push notification. The Captain decides whether to investigate or drop gear.

---

## 9. Implementation Phasing

### Phase 1: Layout Migration (Day 1–2)

**Goal:** Replace the old 370×900 crop with the new dual-band layout.

| Task | File | Est. Effort |
|------|------|-------------|
| Define new layout constants | `config_v3.py` | 30 min |
| Rewrite crop to produce LF + HF bands | `crop_bands.py` | 1 hr |
| Update capture daemon for 10-min cadence | `capture_v3.py` | 2 hr |
| Verify crops with actual capture | Manual | 30 min |
| NMEA snapshot module | `nmea_snapshot.py` | 1 hr |
| Update screenshot.ps1 if needed | `screenshot.py` (v1) | 30 min |

**Verification:** Run one capture cycle, verify LF and HF bands are correctly cropped and aligned with the white divider.

### Phase 2: Pixel Analysis (Stage 1) (Day 2–4)

**Goal:** Deterministic bottom detection, zone profiling, shape detection.

| Task | File | Est. Effort |
|------|------|-------------|
| Vertical signal profile computation | `analyzer_v3.py` — `_analyze_single_band()` | 1 hr |
| Bottom detection (strongest horizontal return) | `analyzer_v3.py` — bottom detection | 2 hr |
| Depth zone segmentation | `analyzer_v3.py` — zone returns | 1 hr |
| Horizontal layer detection (thermoclines) | `analyzer_v3.py` — layer detection | 2 hr |
| Shape detection (columns, arches, blobs) | `analyzer_v3.py` — `_detect_shapes()` | 3 hr |
| Color summary | `analyzer_v3.py` — `_color_summary()` | 30 min |
| Composite analysis (LF + HF merge) | `analyzer_v3.py` — `_composite_analysis()` | 1 hr |
| Depth scale calibration | `depth_calibrate.py` | 2 hr |
| Summary JSON schema + disk write | `capture_v3.py` — `_write_summary()` | 1 hr |
| Multi-column bottom sampling for robustness | `_find_bottom` refinement | 2 hr |

**Total:** ~15 hours. This is the meat of the pipeline. All deterministic — no AI dependency.

### Phase 3: Text Description (Stage 2) (Day 4–6)

**Goal:** LLM-generated text descriptions of echogram state.

| Task | File | Est. Effort |
|------|------|-------------|
| Stage 2 prompt template | Integrated into `analyzer_v3.py` | 1 hr |
| LLM integration (Ollama or Cloudflare Workers AI) | Stage 2 integration | 2 hr |
| Structured JSON output parsing | `analyzer_v3.py` — parse response | 1 hr |
| Prompt iteration (tune description quality) | Manual testing | 3 hr |
| Handle edge cases (no bottom, all quiet, divider only) | Error handling | 2 hr |

**Total:** ~9 hours. The Stage 2 quality improves over time through prompt iteration.

### Phase 4: Vocabulary Building (Day 6–8)

**Goal:** Store and match labeled patterns from captain reports.

| Task | File | Est. Effort |
|------|------|-------------|
| 64-dim feature vector extraction | `label_propagation.py` — `_extract_labeled_features()` | 3 hr |
| Vocabulary storage (patterns.json) | `vocabulary.py` — patterns CRUD | 2 hr |
| Cosine similarity matching | `vocabulary.py` — `match_vocabulary()` | 2 hr |
| Confidence scoring + match history | `vocabulary.py` — match/confidence logic | 2 hr |
| Integration: auto-match on each capture | `capture_v3.py` — hook after analysis | 1 hr |

**Total:** ~10 hours. No new infrastructure — all file-based.

### Phase 5: Catch Events (Day 8–9)

**Goal:** Captain can log catches; system propagates labels.

| Task | File | Est. Effort |
|------|------|-------------|
| Catch event schema | `catches/YYYY-MM-DD.jsonl` | 30 min |
| Catch logger (manual or agent-triggered) | `catch_logger.py` | 1 hr |
| Label propagation (find nearest capture) | `label_propagation.py` — `propagate_catch_label()` | 2 hr |
| Integration: catch → vocabulary update | `catch_logger.py` — vocab hook | 1 hr |
| Master index update on catch | Index integration | 1 hr |

**Total:** ~5.5 hours.

### Phase 6: Retroactive Re-Analysis (Day 9–10)

**Goal:** Re-run Stage 2 on old captures with new vocabulary.

| Task | File | Est. Effort |
|------|------|-------------|
| Re-analysis module | `reanalysis.py` | 3 hr |
| Version tracking per capture | `reanalysis.py` — versioned output | 1 hr |
| Batch re-analysis with date range filter | `reanalysis.py` — `batch_reanalyze()` | 1 hr |
| CLI entry point | `reanalysis.py` — `cli()` | 1 hr |

**Total:** ~6 hours.

### Phase 7: Multi-Track Query & Correlation (Day 10–12)

**Goal:** Query all tracks by time range.

| Task | File | Est. Effort |
|------|------|-------------|
| Index maintenance (append on each capture + catch) | Index integration | 2 hr |
| Time range query across all tracks | `correlation.py` — `query_time_range()` | 2 hr |
| Capture nearest to timestamp | `correlation.py` — nearest capture lookup | 1 hr |
| Track visualization (agent-facing) | Agent prompt templates | 2 hr |
| Master index rebuild from disk | `correlation.py` — `rebuild_index()` | 2 hr |

**Total:** ~9 hours.

### Phase 8: Integration & Cleanup (Day 12–14)

**Goal:** Wire everything together, remove v1 cruft, deploy.

| Task | File | Est. Effort |
|------|------|-------------|
| Wire capture_loop → pipeline (Phases 1-4) | `capture_v3.py` — full flow | 2 hr |
| Wire catch → label → vocabulary | `catch_logger.py` + vocabulary | 1 hr |
| Wire re-analysis batch command | CLI setup | 1 hr |
| Update README.md with v3 architecture | Documentation | 2 hr |
| Deprecate old config.py regions | Config migration | 30 min |
| Create run_capture_v3.py launcher | Launcher script | 30 min |

**Total:** ~7 hours.

### Total Development Effort

| Phase | Hours | Dependencies |
|-------|-------|-------------|
| 1. Layout Migration | 5.5 | None |
| 2. Pixel Analysis (Stage 1) | 15 | Phase 1 |
| 3. Text Description (Stage 2) | 9 | Phase 2 |
| 4. Vocabulary Building | 10 | Phase 2+3 |
| 5. Catch Events | 5.5 | Phase 2 |
| 6. Retroactive Re-Analysis | 6 | Phase 3 |
| 7. Multi-Track Query | 9 | All above |
| 8. Integration & Cleanup | 7 | All above |
| **Total** | **~67 hours** | **~8-10 working days** |

---

## 10. Files & Module Map

```
tzpro-agent/
│
├── config_v3.py              # NEW — Dual-band layout constants, paths
├── capture_v3.py             # NEW — 10-min capture daemon with summary writing
├── crop_bands.py             # NEW — LF/HF band cropping from full frame
├── analyzer_v3.py             # NEW — Stage 1 pixel analysis + Stage 2 text pipeline
├── depth_calibrate.py        # NEW — Pixel Y → depth FM calibration
├── nmea_snapshot.py          # NEW — Structured NMEA fetching at capture time
├── correlation.py            # NEW — Multi-track time range query
├── catch_logger.py           # NEW — Captain catch event logging
├── label_propagation.py      # NEW — Catch → capture linking + feature extraction
├── vocabulary.py             # NEW — Pattern storage, similarity matching, learning
├── reanalysis.py             # NEW — Retroactive Stage 2 re-analysis
│
├── screenshot.py             # KEEP — PowerShell capture (unchanged)
├── screenshot.ps1            # KEEP — PowerShell script (unchanged)
│
├── config.py                 # DEPRECATE — Old single-band crop regions
├── capture.py                # DEPRECATE — Old 30s/4min daemon
├── sounder_analyzer.py       # DEPRECATE — Old OpenCV threshold analysis
├── logger.py                 # DEPRECATE — Old JSONL observation logging
├── vision.py                 # KEEP — Florence-2 integration (Phase 5 future)
├── agent_loop.py             # KEEP — Alert engine (runs alongside new pipeline)
│
├── captures/
│   └── v3/                   # NEW — v3 capture output directory
│
└── memory/
    ├── summaries/            # NEW — JSON summaries + index
    ├── catches/              # NEW — Catch event logs per day
    ├── vocabulary/           # NEW — Feature vectors, patterns, match history
    └── reanalysis/           # NEW — Versioned re-analysis results
```

---

## Appendix: Key Pseudocode for Capture Cycle

```
function capture_cycle():
    ts = now_utc()
    stem = format_ts(ts)  # "tzpro_20260717_090000"
    
    # 1. Capture
    full_frame_path = screenshot_capture()
    rename(full_frame_path, f"{stem}_full.png")
    
    # 2. Crop bands
    lf_path = crop(f"{stem}_full.png", x=8, y=0, x2=945, y2=1080, save=f"{stem}_lf.png")
    hf_path = crop(f"{stem}_full.png", x=950, y=0, x2=1890, y2=1080, save=f"{stem}_hf.png")
    
    # 3. NMEA snapshot
    nmea = fetch_vessel_endpoint()  # {lat, lon, sog, cog, timestamp}
    
    # 4. Stage 1: Deterministic pixel analysis
    stage1_lf = analyze_band(lf_path, is_hf=False)
    stage1_hf = analyze_band(hf_path, is_hf=True)
    stage1 = composite_analysis(stage1_lf, stage1_hf)
    
    # 5. Stage 2: Text description (LLM)
    stage2 = generate_text_description(stage1, nmea, ts)
    
    # 6. Vocabulary matching (against labeled patterns)
    feature_vector = extract_64dim_vector(stage1)
    vocab_matches = match_vocabulary(feature_vector)
    
    # 7. Build summary
    summary = {
        "ts": ts,
        "ts_unix": ts.timestamp(),
        "stem": stem,
        "capture": {
            "frame_path": f"{stem}_full.png",
            "lf_path": f"{stem}_lf.png",
            "hf_path": f"{stem}_hf.png",
            "capture_window_sec": 720,
        },
        "nmea": nmea,
        "analysis": {
            "stage1": stage1,
            "stage2": stage2,
        },
        "vocabulary_matches": vocab_matches,
    }
    
    write_json(f"memory/summaries/{stem}_summary.json", summary)
    append_to_index(f"memory/summaries/index.json", {
        "ts": ts, "stem": stem, "bottom_fm": stage1.composite.best_bottom.depth_fm
    })
    
    # 8. Surface high-confidence vocabulary matches
    for match in vocab_matches:
        if match.confidence > 0.7:
            push_alert_to_captain(
                f"Pattern match: {match.species} at {match.avg_depth} fm "
                f"({match.confidence}% confidence)"
            )
    
    return summary
```

---

*This document is a synthesis of the Captain's July 17 vision, the v2 architecture foundation (Section 4: DAW Dashboard / Learning Loop), and a practical implementation plan for the new capture/analysis pipeline. The old config.py and capture.py regions are deprecated. The new pipeline runs alongside the existing alert engine (agent_loop.py).*

*Riker, Operations Officer | F/V EILEEN, Ketchikan Alaska*
