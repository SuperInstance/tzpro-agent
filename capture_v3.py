#!/usr/bin/env python3
"""capture_v3.py — Echogram capture daemon.

Captures DISPLAY6 (1920x1080 @ X=1920) every 10 minutes on the hour boundary.
Saves full frame + human-readable markdown + A2A-native JSON.

Organized by day in folders named:  {YYYY-MM-DD}_{start_lat}_{start_lon}
  e.g.  2026-07-17_5547N_13142W

Filename format: {HHMM}_{DDMM.mmm}N_{DDDMM.mmm}W.ext
  HHMM = local AKDT time, seconds=0 assumed
  DDMM.mmm = latitude, DDDMM.mmm = longitude
"""

from __future__ import annotations

import json
import logging
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Tuple

# ── Config ─────────────────────────────────────────────────────────
DISPLAY_OFFSET_X = 1920
DISPLAY_OFFSET_Y = 0
DISPLAY_WIDTH = 1920
DISPLAY_HEIGHT = 1080
DEPTH_MAX_FM = 60
PX_PER_FM = DISPLAY_HEIGHT / DEPTH_MAX_FM
CAPTURE_INTERVAL_MIN = 10
SHIP_LOG_URL = "https://ship-log-search.casey-digennaro.workers.dev/api/log"
SHIP_LOG_TIMEOUT_S = 5

NMEA_HOST = "127.0.0.1"
NMEA_PORT = 6006
NMEA_TIMEOUT_S = 5

LOCAL_TZ = timezone(timedelta(hours=-8))

WORKSPACE = Path(__file__).parent.resolve()
CAPTURES_DIR = WORKSPACE / "captures" / "v3"
SCREENSHOT_PS1 = WORKSPACE / "screenshot_v3.ps1"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("capture_v3")

# ── State ──────────────────────────────────────────────────────────
_current_day_dir: Optional[Path] = None
_day_first_pos: Optional[Tuple[str, str]] = None  # (lat_str, lon_str)


def ensure_script():
    if SCREENSHOT_PS1.exists():
        return
    script = r"""param([string]$OutDir, [string]$Filename)
$path = Join-Path $OutDir $Filename
Add-Type -AssemblyName System.Drawing
$bmp = New-Object System.Drawing.Bitmap(1920, 1080)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$size = New-Object System.Drawing.Size(1920, 1080)
$g.CopyFromScreen(1920, 0, 0, 0, $size)
$g.Dispose()
$bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
Write-Output $path
"""
    SCREENSHOT_PS1.write_text(script.lstrip(), encoding="utf-8")
    log.info("Created %s", SCREENSHOT_PS1)


def parse_nmea_latlon(nmea_str: str) -> Optional[float]:
    nmea_str = nmea_str.strip()
    if not nmea_str:
        return None
    dot_pos = nmea_str.find(".")
    if dot_pos < 3:
        return None
    deg_digits = dot_pos - 2
    deg = int(nmea_str[:deg_digits])
    minutes_str = nmea_str[deg_digits:]
    minutes = float(minutes_str)
    return deg + minutes / 60.0


def dd_to_ddmm(dd: float) -> str:
    deg = int(abs(dd))
    minutes = (abs(dd) - deg) * 60
    return f"{deg:02d}{minutes:06.3f}"


def fetch_position() -> Optional[Tuple[float, float, Optional[float], Optional[float]]]:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(NMEA_TIMEOUT_S)
        s.connect((NMEA_HOST, NMEA_PORT))
        data = b""
        t0 = time.time()
        while time.time() - t0 < NMEA_TIMEOUT_S - 1:
            try:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
                if len(data) > 2000:
                    break
            except socket.timeout:
                break
        s.close()

        lat = lon = sog = cog = None
        for line in data.decode(errors="replace").split("\r\n"):
            if line.startswith("$GPGGA"):
                parts = line.split(",")
                if len(parts) >= 10 and parts[2] and parts[4]:
                    lat_dd = parse_nmea_latlon(parts[2])
                    lon_dd = parse_nmea_latlon(parts[4])
                    if lat_dd and lon_dd:
                        if parts[3] == "S": lat_dd = -lat_dd
                        if parts[5] == "W": lon_dd = -lon_dd
                        lat, lon = lat_dd, lon_dd
            elif line.startswith("$GPRMC"):
                parts = line.split(",")
                if len(parts) >= 9:
                    if parts[7]: sog = float(parts[7])
                    if parts[8]: cog = float(parts[8])
        if lat is not None and lon is not None:
            return (lat, lon, sog, cog)
    except Exception as e:
        log.warning("NMEA read failed: %s", e)
    return None


def get_day_dir(now: datetime, lat_str: str, lon_str: str) -> Path:
    """Return the daily capture directory, creating or updating on first use."""
    global _current_day_dir, _day_first_pos
    date_str = now.strftime("%Y-%m-%d")

    # On first capture of a new day, store starting position
    if _day_first_pos is None:
        _day_first_pos = (lat_str, lon_str)
        parts = date_str.split("-")
        day_folder = f"{date_str}_{lat_str}N_{lon_str}W"
        _current_day_dir = CAPTURES_DIR / day_folder
        log.info("New day folder: %s", _current_day_dir)

    _current_day_dir.mkdir(parents=True, exist_ok=True)
    return _current_day_dir


def capture_frame() -> Optional[Path]:
    """Capture second monitor. Returns path to saved PNG or None."""
    global _day_first_pos, _current_day_dir

    ensure_script()
    now = datetime.now(LOCAL_TZ)
    hhmm = now.strftime("%H%M")

    pos = fetch_position()
    lat_str, lon_str = "0000.000", "00000.000"
    lat_val = lon_val = sog_val = cog_val = None

    if pos:
        lat_val, lon_val, sog_val, cog_val = pos
        lat_str = dd_to_ddmm(lat_val)
        lon_str = dd_to_ddmm(lon_val)

    # Build day folder from first position of the day
    if _day_first_pos is None:
        _day_first_pos = (lat_str, lon_str)
        day_folder = f"{now.strftime('%Y-%m-%d')}_{lat_str}N_{lon_str}W"
        _current_day_dir = CAPTURES_DIR / day_folder
        log.info("Day folder: %s", _current_day_dir)
    _current_day_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{hhmm}_{lat_str}N_{lon_str}W.png"
    filepath = _current_day_dir / filename

    try:
        result = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass",
             "-File", str(SCREENSHOT_PS1),
             "-OutDir", str(_current_day_dir),
             "-Filename", filename],
            capture_output=True, text=True, timeout=30,
        )
        out = result.stdout.strip()
        if not out or not Path(out).exists():
            log.warning("No valid file produced")
            return None

        saved = Path(out)

        # Write JSON metadata (A2A twin)
        capture_id = saved.stem
        meta = {
            "capture_id": capture_id,
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "ts_local": now.isoformat(),
            "ts_local_hhmm": hhmm,
            "frame_file": filename,
            "position": {
                "lat_dd": lat_val, "lon_dd": lon_val,
                "lat_ddmm": lat_str, "lon_ddmm": lon_str,
                "sog_kts": sog_val, "cog_deg": cog_val,
            },
            "display": {
                "offset_x": DISPLAY_OFFSET_X, "offset_y": DISPLAY_OFFSET_Y,
                "width": DISPLAY_WIDTH, "height": DISPLAY_HEIGHT,
                "depth_max_fm": DEPTH_MAX_FM, "px_per_fm": PX_PER_FM,
            },
            "analysis": {"schema_version": 1, "heuristic": None, "caption": None, "vocabulary": None},
            "edges": {"neighbors_time": [], "neighbors_space": []},
        }
        # Atomic write: write to .tmp first, then rename — prevents readers
# from seeing a half-written file if the process crashes mid-write.
_json_path = saved.with_suffix(".json")
_json_tmp = _json_path.with_suffix(".json.tmp")
_json_tmp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
_json_tmp.replace(_json_path)

        # Write markdown (human twin)
        md_lines = [
            f"# Echogram Capture  {capture_id}",
            "",
            f"**Date:** {now.strftime('%B %d, %Y')}  **Time:** {hhmm[:2]}:{hhmm[2:]} AKDT",
            "",
            "## Vessel",
            f"- Position: {lat_str}N  {lon_str}W  (DDMM.mmm)",
            f"- SOG {sog_val:.2f} kn" + (f"  COG {cog_val:.0f}°" if cog_val else ""),
            "",
            "## Display",
            f"- Monitor: DISPLAY6 (1920x1080 @ X={DISPLAY_OFFSET_X})",
            f"- Mode: Dual-band sounder, fixed {DEPTH_MAX_FM} fm range",
            f"- Scale: {PX_PER_FM:.1f} px/fathom",
            "",
            "## Water Column (0-60 fm)",
            "Surface:     0-5 fm   — clutter zone",
            "Upper:      5-20 fm   — bait, pelagics",
            "Mid:       20-40 fm   — target depth zone (chum)",
            "Lower:     40-55 fm   — near-deep",
            "Floor:     55-60 fm   — display limit",
            "",
            "## Analysis",
            "*Raw capture — no analysis yet.*",
            "",
            "---",
            f"*capture_v3.py at {now.strftime('%H:%M:%S AKDT')}*",
        ]
        # Atomic write for markdown
_md_path = saved.with_suffix(".md")
_md_tmp = _md_path.with_suffix(".md.tmp")
_md_tmp.write_text("\n".join(md_lines), encoding="utf-8")
_md_tmp.replace(_md_path)

        ship_log_ingest(saved, now, meta)

        log.info("Captured: %s  Pos: %sN %sW  SOG: %s",
                 filename, lat_str, lon_str, sog_val or "?")
        return saved

    except Exception as e:
        log.warning("Capture error: %s", e)
    return None


def ship_log_ingest(saved: Path, now: datetime, meta: dict) -> None:
    """POST capture summary to Ship Log Search. Fire-and-forget."""
    md_path = saved.with_suffix(".md")
    if not md_path.exists():
        return

    try:
        md_text = md_path.read_text(encoding="utf-8")
        # Build a concise plain-text summary from the markdown
        # Strip markdown headings/formatting for better embeddings
        lines = [l for l in md_text.splitlines() if not l.startswith("---")]
        summary = " ".join(
            l.strip(" *#") for l in lines
            if l.strip() and not l.startswith("*capture_v3.py")
        )

        pos = meta["position"]
        payload = {
            "text": summary,
            "category": "observation",
            "subcategory": "echogram_capture",
            "timestamp": meta["ts_utc"],
            "lat": pos["lat_dd"],
            "lon": pos["lon_dd"],
            "location_name": f"{pos['lat_ddmm']}N/{pos['lon_ddmm']}W",
            "id": f"echogram_{meta['capture_id']}",
            "metadata": {
                "capture_id": meta["capture_id"],
                "depth_max_fm": meta["display"]["depth_max_fm"],
                "sog_kts": pos["sog_kts"],
                "day_folder": saved.parent.name,
                "category": "observation",
                "subcategory": "echogram_capture",
            },
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            SHIP_LOG_URL,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=SHIP_LOG_TIMEOUT_S)
        log.info("Ingested to Ship Log Search: %s", meta["capture_id"])
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        log.warning("Ship Log Search ingest failed (non-blocking): %s", e)


def wait_for_next_boundary() -> float:
    now = datetime.now(LOCAL_TZ)
    block_min = (now.minute // CAPTURE_INTERVAL_MIN) * CAPTURE_INTERVAL_MIN
    block = now.replace(minute=block_min, second=0, microsecond=0)
    next_b = block + timedelta(minutes=CAPTURE_INTERVAL_MIN)
    wait = (next_b - now).total_seconds()
    if wait < 1:
        wait += CAPTURE_INTERVAL_MIN * 60
        next_b += timedelta(minutes=CAPTURE_INTERVAL_MIN)
    log.info("Next at %s (%ds)", next_b.strftime("%H:%M AKDT"), int(wait))
    return wait


def run_once():
    log.info("=== Capture ===")
    t0 = time.time()
    path = capture_frame()
    elapsed = time.time() - t0
    if path:
        log.info("Done in %.1fs — %s", elapsed, path.name)
    else:
        log.warning("Capture FAILED (%.1fs)", elapsed)
    return path


def run_forever():
    log.info("=" * 50)
    log.info("capture_v3 starting")
    log.info("Display: %dx%d @ X=%d", DISPLAY_WIDTH, DISPLAY_HEIGHT, DISPLAY_OFFSET_X)
    log.info("Cadence: every %d min on boundary", CAPTURE_INTERVAL_MIN)
    log.info("Depth: %d fm (%.1f px/fm)", DEPTH_MAX_FM, PX_PER_FM)
    log.info("Archive: %s", CAPTURES_DIR)
    log.info("=" * 50)

    while True:
        wait = wait_for_next_boundary()
        if wait > 0:
            time.sleep(wait)
        run_once()


if __name__ == "__main__":
    if "--oneshot" in sys.argv:
        run_once()
    else:
        run_forever()
