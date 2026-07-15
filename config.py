#!/usr/bin/env python3
"""config.py — Shared constants for the tzpro-agent pipeline."""

from __future__ import annotations
from typing import Tuple

# ── Display Layout ──────────────────────────────────────────────────
# DISPLAY6 is the second monitor: 1920×1080 at X=1920, Y=0
DISPLAY_OFFSET_X = 1920
DISPLAY_WIDTH = 1920
DISPLAY_HEIGHT = 1080

# ── Sounder Crop Region ─────────────────────────────────────────────
# On a 1920×1080 TZ Pro layout, the sounder/fishfinder panel occupies
# the right ~370px of the screen, starting below the top data bars.
SOUNDER_X1 = 1540
SOUNDER_Y1 = 100
SOUNDER_X2 = 1910
SOUNDER_Y2 = 1000

SOUNDER_CROP: Tuple[int, int, int, int] = (SOUNDER_X1, SOUNDER_Y1, SOUNDER_X2, SOUNDER_Y2)
SOUNDER_WIDTH = SOUNDER_X2 - SOUNDER_X1   # 370
SOUNDER_HEIGHT = SOUNDER_Y2 - SOUNDER_Y1  # 900

# ── Depth Scale ─────────────────────────────────────────────────────
# The depth scale is a ~20px strip on the right edge of the sounder panel.
# Within the cropped sounder (370px wide), the scale starts at x≈350.
DEPTH_SCALE_X = 350

# In the default TZ Pro sounder layout at this zoom, the depth scale
# likely spans 0–60 or 0–80 fathoms over 900px. We calibrate this by
# reading the tick-mark numbers via OCR on first frame, then caching.
DEFAULT_MAX_DEPTH_FM = 80  # fallback until calibrated

# ── Capture Cadence ─────────────────────────────────────────────────
SOUNDER_INTERVAL = 30   # seconds between sounder-only captures
FULL_INTERVAL = 240     # 4 minutes between full frames

# ── Sounder Palette ─────────────────────────────────────────────────
# Confirmed by Captain: dark blue background with blue→cyan→yellow→orange→red
# as signal intensity increases. This is the traditional fishfinder palette.
#
# Color profile of the dark background (measured from multiple captures):
#   avg rgb(18, 36, 53)  — very dark navy blue
#   avg RGB total ≈ 107
#
# Return intensity mapping (RGB total of all three channels):
#   < 130 total RGB = background noise (blue palette baseline)
#   130-180 total RGB = weak returns (soft mud, plankton, surface clutter)
#   180-250 total RGB = medium returns (fish schools, thermoclines, soft bottom)
#   250+ total RGB = strong returns (hard bottom, dense schools, orange/red returns)
#
# These thresholds are tuned for the blue palette on this specific display.
# The key insight: in a blue palette, the background IS blue. Fish and bottom
# returns are warmer-colored (green/yellow/orange). Pure brightness thresholding
# catches too much background noise. Ideally we'd use color-channel ratios.
RGB_THRESHOLD_BACKGROUND = 107  # avg background total RGB
RGB_THRESHOLD_FISH = 180        # medium returns (fish, thermoclines)
RGB_THRESHOLD_STRONG = 250      # strong returns (hard bottom, dense schools)

# ── Bottom Detection ────────────────────────────────────────────────
# How many pixels above the detected bottom line to exclude from fish
# detection (avoids counting the bottom return band as fish).
BOTTOM_EXCLUSION_PX = 30

# ── NMEA Source ─────────────────────────────────────────────────────
NMEA_VESSEL_URL = "http://127.0.0.1:8654/vessel"
NMEA_TIMEOUT = 3  # seconds

# ── Paths ───────────────────────────────────────────────────────────
from pathlib import Path
WORKSPACE = Path(__file__).parent.resolve()
CAPTURES_DIR = WORKSPACE / "captures"
MEMORY_DIR = WORKSPACE / "memory"
OBSERVATIONS_DIR = MEMORY_DIR / "observations"
DAILY_DIR = MEMORY_DIR / "daily"
SCREENSHOT_PS1 = WORKSPACE / "screenshot.ps1"
