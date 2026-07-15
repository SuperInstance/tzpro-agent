#!/usr/bin/env python3
"""screenshot.py — Common screen capture utilities for tzpro-agent.

Handles PowerShell-based capture of DISPLAY6 (second monitor) and
PIL-based region crops. Shared between the background daemon (capture.py)
and the on-demand agent (agent.py).
"""

from __future__ import annotations
import logging, subprocess
from pathlib import Path
from typing import Optional

from config import (
    CAPTURES_DIR,
    DISPLAY_OFFSET_X,
    DISPLAY_WIDTH,
    DISPLAY_HEIGHT,
    SCREENSHOT_PS1,
    SOUNDER_CROP,
)

log = logging.getLogger("tzpro.screenshot")


def ensure_script() -> Path:
    """Write the PowerShell capture script if missing."""
    if SCREENSHOT_PS1.exists():
        return SCREENSHOT_PS1

    script = r'''param([string]$OutDir)
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$path = Join-Path $OutDir "frame_$ts.png"
Add-Type -AssemblyName System.Drawing
$bmp = New-Object System.Drawing.Bitmap(1920, 1080)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen(1920, 0, 0, 0, (1920, 1080))
$g.Dispose()
$bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
Write-Output $path
'''
    SCREENSHOT_PS1.write_text(script.lstrip(), encoding="utf-8")
    log.info("Created %s", SCREENSHOT_PS1)
    return SCREENSHOT_PS1


def capture_full() -> Optional[Path]:
    """Capture full 1920×1080 of DISPLAY6. Returns path or None."""
    ensure_script()
    CAPTURES_DIR.mkdir(parents=True, exist_ok=True)

    try:
        result = subprocess.run(
            [
                "powershell",
                "-ExecutionPolicy", "Bypass",
                "-File", str(SCREENSHOT_PS1),
                "-OutDir", str(CAPTURES_DIR),
            ],
            capture_output=True, text=True, timeout=15,
        )
        out = result.stdout.strip()
        if out and Path(out).exists():
            return Path(out)
        log.warning("Capture failed: stdout=%s stderr=%s", result.stdout[:100], result.stderr[:100])
    except subprocess.TimeoutExpired:
        log.warning("Capture timed out after 15s")
    except Exception as e:
        log.warning("Capture error: %s", e)

    return None


def crop_region(full_path: Path, region: tuple = SOUNDER_CROP) -> Optional[Path]:
    """Crop a region from a full frame and save as {stem}_{tag}.png.

    Args:
        full_path: Path to the full frame.
        region: (x1, y1, x2, y2) crop coordinates.

    Returns:
        Path to the cropped image, or None on failure.
    """
    try:
        from PIL import Image
        x1, y1, x2, y2 = region
        img = Image.open(full_path)
        crop = img.crop((x1, y1, x2, y2))
        tag = "sounder"
        crop_path = full_path.with_name(f"{full_path.stem}_{tag}.png")
        crop.save(crop_path)
        return crop_path
    except ImportError:
        log.warning("PIL not installed — can't crop")
    except Exception as e:
        log.warning("Crop error: %s", e)
    return None


def capture_sounder() -> Optional[Path]:
    """Convenience: capture full frame and crop sounder in one call.
    Deletes the full frame to save disk — only keeps the sounder crop.
    Returns path to sounder crop or None."""
    full = capture_full()
    if not full:
        return None
    sounder = crop_region(full)
    # Clean up full frame
    if sounder and full.exists():
        full.unlink()
    return sounder
