#!/usr/bin/env python3
"""sounder_analyzer.py — Analyze TZ Pro sounder/fishfinder cropped images.

The sounder uses a dark blue palette (confirmed by Captain):
  rgb(14, 29, 52) background  →  very dark navy
  blue → cyan → yellow → orange → red  as returns intensify

Thresholds in config.py are tuned for this specific display palette.
"""

from __future__ import annotations
import json, logging, re, sys
from pathlib import Path
from typing import Optional

try:
    from PIL import Image
except ImportError:
    Image = None

from config import (
    DEPTH_SCALE_X,
    SOUNDER_WIDTH,
    SOUNDER_HEIGHT,
    RGB_THRESHOLD_BACKGROUND,
    RGB_THRESHOLD_FISH,
    RGB_THRESHOLD_STRONG,
    BOTTOM_EXCLUSION_PX,
    DEFAULT_MAX_DEPTH_FM,
)

log = logging.getLogger("tzpro.sounder")


# ══════════════════════════════════════════════════════════════════════
#  Public API
# ══════════════════════════════════════════════════════════════════════

def analyze_sounder(image_path: Path) -> dict:
    """Analyze a sounder crop image and return structured observations.

    Returns a dict with:
      - source: filename
      - bottom_depth_fm: estimated bottom depth in fathoms (or None)
      - bottom_pixel_y: raw pixel position of bottom
      - bottom_type: hard / medium / soft_mud / very_soft / mixed
      - bottom_confidence: high / medium / low
      - fish_returns: dict with count, density, depth_range, or empty list
      - thermoclines: dict with layer_count, or empty list
      - depth_scale: list of depths read from scale edge
      - signal_profile: avg color, palette dominance
    """
    result = {
        "source": str(image_path.name),
        "bottom_depth_fm": None,
        "bottom_pixel_y": None,
        "bottom_type": None,
        "bottom_confidence": None,
        "fish_returns": [],
        "thermoclines": [],
        "depth_scale": [],
        "signal_profile": {},
    }

    if not Image:
        result["error"] = "PIL not installed"
        return result

    try:
        img = Image.open(image_path).convert("RGB")
        w, h = img.size
        pixels = img.load()

        # 1. Read depth scale numbers from right edge
        result["depth_scale"] = _read_depth_scale(img, w, h)

        # 2. Find bottom return
        bottom = _find_bottom(img, pixels, w, h)
        if bottom:
            result["bottom_pixel_y"] = bottom["pixel_y"]
            # Calibrate: convert pixel position to fathoms using depth scale
            result["bottom_depth_fm"] = _pixel_to_depth(
                bottom["pixel_y"], h, result["depth_scale"]
            )
            result["bottom_type"] = bottom["type"]
            result["bottom_confidence"] = bottom["confidence"]

        # 3. Detect returns above bottom (fish, thermoclines)
        fish = _find_fish_returns(img, pixels, w, h, bottom)
        if fish:
            result["fish_returns"] = fish

        # 4. Detect thermoclines
        thermo = _find_thermoclines(img, pixels, w, h)
        if thermo:
            result["thermoclines"] = thermo

        # 5. Signal profile
        result["signal_profile"] = _signal_profile(img, pixels, w, h)

    except Exception as e:
        log.warning("Analysis error on %s: %s", image_path.name, e)
        result["error"] = str(e)

    return result


# ══════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════

def _read_depth_scale(img, w: int, h: int) -> list[float]:
    """OCR the depth scale numbers from the right edge of the sounder.

    The depth scale is a ~20px strip at the right of the sounder panel.
    TZ Pro shows tick marks with depth numbers (in fathoms) at intervals.
    Returns a sorted list of depth values found, e.g. [0, 20, 40, 60].
    """
    try:
        import pytesseract
        # Crop just the scale strip
        scale_crop = img.crop((DEPTH_SCALE_X, 0, w, h))
        # OCR with digit-only mode
        text = pytesseract.image_to_string(scale_crop, config="--psm 6 digits")
        nums = re.findall(r"\d+\.?\d*", text)
        return sorted(set(float(n) for n in nums if float(n) > 0))
    except ImportError:
        log.debug("pytesseract not installed — no depth scale OCR")
    except Exception as e:
        log.debug("Depth scale OCR error: %s", e)
    return []


def _pixel_to_depth(pixel_y: int, sounder_height: int, scale_readings: list[float]) -> Optional[float]:
    """Convert a pixel Y position to depth in fathoms.

    Uses the OCR'd depth scale numbers to calibrate the conversion.
    Falls back to proportional estimate using DEFAULT_MAX_DEPTH_FM.
    """
    if not scale_readings:
        # No scale numbers found — use proportional estimate
        frac = pixel_y / sounder_height
        return round(frac * DEFAULT_MAX_DEPTH_FM, 1)

    # Use the highest scale reading as max depth
    max_depth = max(scale_readings)
    frac = pixel_y / sounder_height
    return round(frac * max_depth, 1)


def _find_bottom(img, pixels, w: int, h: int) -> Optional[dict]:
    """Find the strongest horizontal return (bottom line).

    Scans each column bottom-up for the brightest pixel, which indicates
    the bottom return. Uses the blue palette: strong returns are warm-colored
    (yellow/orange/red), weak returns are cool (blue/cyan).

    Returns dict with pixel_y, type, hardness_score, roughness, confidence.
    """
    bottom_candidates = []
    for x in range(0, w - 30):  # skip depth scale strip
        brightest_y = 0
        brightest_val = 0
        for y in range(h - 1, 0, -5):  # scan bottom-up
            r, g, b = pixels[x, y]
            val = r + g + b
            if val > brightest_val:
                brightest_val = val
                brightest_y = y
        bottom_candidates.append(brightest_y)

    if not bottom_candidates:
        return None

    # Median position (robust to outliers)
    bottom_candidates.sort()
    median_y = bottom_candidates[len(bottom_candidates) // 2]
    stddev = (sum((y - median_y) ** 2 for y in bottom_candidates) / len(bottom_candidates)) ** 0.5

    # Classify bottom type by return color
    x = w // 2
    band_start = max(0, median_y - 20)
    colors_above = [pixels[x, min(y, h - 1)] for y in range(band_start, median_y)]
    if not colors_above:
        return None

    avg_r = sum(c[0] for c in colors_above) / len(colors_above)
    avg_g = sum(c[1] for c in colors_above) / len(colors_above)
    avg_b = sum(c[2] for c in colors_above) / len(colors_above)

    # Blue palette tuning:
    # - Red/orange dominant (>200 r, >100 g) = very hard return
    # - Green/yellow dominant (>150 g, >r) = medium
    # - Blue/cyan (b > r, b > 100) = soft/muddy
    # - All channels low (<80) = very soft / deep silt
    max_channel = max(avg_r, avg_g, avg_b)
    if avg_r > 200 and avg_g > 100:
        btype = "hard"
    elif avg_g > avg_r and avg_g > 150:
        btype = "medium"
    elif avg_b > avg_r and avg_b > 100:
        btype = "soft_mud"
    elif max_channel < 80:
        btype = "very_soft"
    else:
        btype = "mixed"

    return {
        "pixel_y": median_y,
        "type": btype,
        "hardness_score": round(max_channel / 255, 2),
        "roughness": round(stddev, 1),
        "confidence": "high" if stddev < 15 else "medium" if stddev < 30 else "low",
    }


def _find_fish_returns(img, pixels, w: int, h: int, bottom: Optional[dict] = None) -> list:
    """Detect returns above the bottom band (fish, bait, debris).

    Uses the blue palette thresholds:
    - Excludes the bottom return band (strongest signal)
    - Counts returns with RGB total > RGB_THRESHOLD_FISH
    - Groups and summarizes by density and depth range

    Returns a dict with count, density, avg_intensity, depth_range,
    and distribution, or empty list if nothing significant found.
    """
    bottom_y = bottom["pixel_y"] if bottom else h
    exclusion = max(0, bottom_y - BOTTOM_EXCLUSION_PX)

    returns = []
    step = 3  # sample every 3rd pixel for speed
    for y in range(0, exclusion, step):
        for x in range(0, w - 30, step):  # skip depth scale
            try:
                r, g, b = pixels[x, y]
                total = r + g + b
                if total > RGB_THRESHOLD_FISH:
                    returns.append({
                        "x": x, "y": y,
                        "intensity": round(total / 3),
                        "depth_frac": round(y / h, 3),
                    })
            except IndexError:
                continue

    if len(returns) < 5:
        return []

    returns.sort(key=lambda a: a["y"])
    intensities = [r["intensity"] for r in returns]
    depth_fracs = [r["depth_frac"] for r in returns]

    # Determine distribution
    if len(returns) < 30:
        dist = "scattered"
    elif len(returns) < 100:
        dist = "moderate"
    elif len(returns) < 300:
        dist = "dense"
    else:
        dist = "very_dense"

    return {
        "count": len(returns),
        "density_per_100kpx": round(len(returns) / (w * h) * 100000, 2),
        "avg_intensity": round(sum(intensities) / len(intensities), 1),
        "depth_range": [round(min(depth_fracs), 2), round(max(depth_fracs), 2)],
        "distribution": dist,
    }


def _find_thermoclines(img, pixels, w: int, h: int) -> list:
    """Detect horizontal bands of uniform color (temperature layers).

    Scans for rows where color is consistent across the width and
    significantly different from the dark background. Returns list
    of detected layers or empty list.
    """
    bands = []
    for y in range(0, h, 5):
        colors = [pixels[x, y] for x in range(0, w - 30, 10) if x < w and y < h]
        if not colors:
            continue
        avg_r = sum(c[0] for c in colors) / len(colors)
        avg_g = sum(c[1] for c in colors) / len(colors)
        avg_b = sum(c[2] for c in colors) / len(colors)
        variance = sum(
            (c[0] - avg_r) ** 2 + (c[1] - avg_g) ** 2 + (c[2] - avg_b) ** 2
            for c in colors
        ) / len(colors)

        # Detect: low variance (uniform color) + above background brightness
        if variance < 500 and (avg_r + avg_g + avg_b) > RGB_THRESHOLD_BACKGROUND:
            bands.append({
                "y": y,
                "depth_frac": round(y / h, 3),
                "avg_color": f"rgb({int(avg_r)},{int(avg_g)},{int(avg_b)})",
                "variance": round(variance),
            })

    if len(bands) < 3:
        return []

    # Group adjacent bands
    return {
        "layer_count": len(bands),
        "layers": bands[:8],
    }


def _signal_profile(img, pixels, w: int, h: int) -> dict:
    """Overall signal characteristics — avg color, palette dominance."""
    total_r = total_g = total_b = count = 0
    for y in range(0, h, 10):
        for x in range(0, w, 10):
            try:
                r, g, b = pixels[x, y]
                total_r += r; total_g += g; total_b += b
                count += 1
            except IndexError:
                continue

    if count == 0:
        return {}

    avg_r, avg_g, avg_b = total_r / count, total_g / count, total_b / count

    # Determine which color channel dominates the returns
    if avg_r > avg_g and avg_r > avg_b:
        dominance = "red"       # strong returns dominating
    elif avg_g > avg_b:
        dominance = "green"     # medium returns
    else:
        dominance = "blue"      # background/weak returns

    return {
        "avg_color": f"rgb({int(avg_r)},{int(avg_g)},{int(avg_b)})",
        "signal_strength": round((avg_r + avg_g + avg_b) / 3 / 255, 3),
        "palette_dominance": dominance,
    }


# ══════════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════════

def cli():
    """CLI entry point: analyze a sounder crop and print JSON."""
    if len(sys.argv) < 2:
        print("Usage: python sounder_analyzer.py <sounder_crop.png>")
        return
    result = analyze_sounder(Path(sys.argv[1]))
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    cli()
