# TZ Pro Agent — Complete Installation Guide

**For fishermen who want to wire their own boat. No developer experience required.**

---

## Before You Start: What You Need

### Hardware (Most boats already have these)
| Item | Spec | Notes |
|------|------|-------|
| **Windows laptop/PC** | Win 10/11, 8 GB RAM minimum, 32 GB recommended | Dedicated wheelhouse PC ideal |
| **GPS with NMEA 0183 output** | u-blox NEO-M8N or any NMEA 0183 source | COM port or USB-Serial adapter |
| **Furuno TZ Pro** | Dual-band 50/200 kHz | Your primary sounder/chartplotter |
| **Dedicated monitor for TZ Pro** | 1920×1080 (DISPLAY6 on Eileen) | Agent captures THIS specific display |
| **USB-Serial adapter** | FTDI or Prolific chipset | For GPS → laptop if no COM port |
| **Internet** | For initial setup only (downloads) | Starlink/dock WiFi works |

### Software (All free)
| Tool | Version | Installer |
|------|---------|-----------|
| **Python** | 3.10+ | python.org/downloads |
| **Git** | Latest | git-scm.com |
| **Tesseract OCR** | 5.x | github.com/UB-Mannheim/tesseract/wiki |
| **PowerShell** | 5.1+ | Built into Windows |

---

## Step 1: Install Python & Git

### 1.1 Install Python
1. Go to **python.org/downloads**
2. Download **Python 3.11+** (64-bit)
3. Run installer — **CHECK "Add Python to PATH"** ⚠️ Critical
4. Verify: Open PowerShell → `python --version` → should show 3.11.x

### 1.2 Install Git
1. Go to **git-scm.com/download/win**
2. Run installer, defaults are fine
3. Verify: `git --version`

### 1.3 Install Tesseract OCR
1. Go to **github.com/UB-Mannheim/tesseract/wiki**
2. Download latest `tesseract-ocr-w64-setup-5.x.x.exe`
3. Run installer — default location `C:\Program Files\Tesseract-OCR\`
4. **Add to PATH**: Windows → "Environment Variables" → System Path → Add `C:\Program Files\Tesseract-OCR\`
5. Verify: `tesseract --version` → should show 5.x.x

---

## Step 2: Clone the Repositories

```powershell
# Pick a folder (e.g., C:\Projects or D:\BoatSystems)
cd C:\
mkdir BoatSystems
cd BoatSystems

# Main agent
git clone https://github.com/SuperInstance/tzpro-agent.git

# NMEA bridge & dashboard (hermit-crab)
git clone https://github.com/SuperInstance/hermit-crab.git
```

You should now have:
```
C:\BoatSystems\
├── tzpro-agent\
└── hermit-crab\
```

---

## Step 3: Install Python Dependencies

```powershell
cd C:\BoatSystems\tzpro-agent
pip install pillow numpy
```

That's it for core dependencies. (Future phases may need `torch`, `opencv-python`, `ultralytics` — install when needed.)

---

## Step 4: Configure Your Hardware

### 4.1 Find Your GPS COM Port
1. Plug in USB-Serial adapter (GPS connected)
2. Device Manager → Ports (COM & LPT) → note the COM number (e.g., `COM6`)
3. Note baud rate — usually **4800** for NMEA 0183

### 4.2 Identify TZ Pro Display Number
1. Right-click desktop → Display settings
2. Note which monitor number TZ Pro runs on (e.g., "Display 6")
3. This becomes `DISPLAY_NUMBER` in config

### 4.3 Edit config.py
```powershell
cd C:\BoatSystems\tzpro-agent
notepad config.py
```

**Change these settings to match YOUR boat:**
```python
# GPS / NMEA
NMEA_PORT = "COM6"           # Your GPS COM port
NMEA_BAUD = 4800             # Usually 4800

# Display capture
DISPLAY_NUMBER = 6           # Your TZ Pro monitor number
SOUNDER_CROP = (x, y, w, h)  # Region of sounder panel — see below

# Paths (use YOUR drive letter)
DATA_ROOT = Path(r"D:\BoatData")  # Where logs/screenshots go
CAPTURE_DIR = DATA_ROOT / "captures"
MEMORY_DIR = DATA_ROOT / "memory"
BATHY_DIR = DATA_ROOT / "bathymetry"

# Sounder range (must match TZ Pro setting)
SOUNDER_RANGE_FM = 60        # If you run 120 fm range, change this
```

### 4.4 Calibrate the Sounder Crop Region
The agent needs to know exactly where the sounder panel sits on your TZ Pro display.

1. Run a test capture:
   ```powershell
   python capture.py --oneshot
   ```
2. Check `captures/v3/` — you'll see a full screenshot + cropped sounder
3. Open the full screenshot in Paint/Photos
4. Note the pixel coordinates of the sounder water column:
   - Left edge, top edge, width, height
4. Update `SOUNDER_CROP = (left, top, width, height)` in `config.py`
5. Re-test until the crop captures JUST the water column (no menus, no scale numbers on sides)

**Eileen's crop (reference):** `SOUNDER_CROP = (1450, 120, 370, 900)` on 1920×1080 DISPLAY6

---

## Step 5: Run the NMEA Bridge (Critical!)

The bridge shares ONE GPS with BOTH TZ Pro AND the agent.

```powershell
cd C:\BoatSystems\hermit-crab\nmea-bridge
python nmea_bridge.py --port COM6 --baud 4800
```

**Leave this running.** You'll see:
```
NMEA Bridge started on COM6 @ 4800 baud
Broadcasting: TCP :6006 (hermitd) + :6007 (TZ Pro)
Shared mode: FILE_SHARE_READ | FILE_SHARE_WRITE
Waiting for NMEA sentences...
>>> $GPGGA,123456.00,5547.1234,N,13141.5678,W,1,08,1.2,12.3,M,...
>>> $GPRMC,123456.00,A,5547.1234,N,13141.5678,W,5.2,245.1,190726,,,A*72
```

### Configure TZ Pro to Use the Bridge
1. Open TZ Pro → Settings → Network → NMEA Input
2. Add TCP connection: **localhost:6007**
3. Enable it — TZ Pro now gets position from the bridge (not COM6 directly)

**Why this matters:** Without shared mode, TZ Pro locks COM6 exclusively and the agent gets nothing. The bridge solves this.

---

## Step 6: Build the Bathymetric Grid (One Time, ~10 Minutes)

```powershell
cd C:\BoatSystems\tzpro-agent
python bathy_contours.py
```

This:
- Downloads/processes 10.5 GB NOAA soundings (first run only)
- Builds 153 MB numpy grid at 0.001° resolution (~100m)
- Extracts 9 contour layers (5, 10, 20, 30, 48, 60, 80, 100, 150 fm)
- Saves to `bathymetry/contours/` and `bathymetry/contours/elevation_grid.npy`

**Only needs doing once per region.** Current grid covers SE Alaska (54-59°N, 130-138°W).

To expand region: edit `bathy_contours.py` → `ROI_LAT_MIN`, `ROI_LAT_MAX`, `ROI_LON_MIN`, `ROI_LON_MAX`

---

## Step 7: Test the Full Pipeline

```powershell
cd C:\BoatSystems\tzpro-agent
python capture.py --oneshot
```

**Success looks like:**
```
[2026-07-19 08:30:15] Capturing DISPLAY6...
[2026-07-19 08:30:16] Cropping sounder region (370x900)...
[2026-07-19 08:30:16] Analyzing sounder...
[2026-07-19 08:30:18] Bottom: 57.2 fm, soft_mud, confidence=high
[2026-07-19 08:30:18] Fish returns: 234 (mid-water 20-40 fm)
[2026-07-19 08:30:18] Thermoclines: 26.1, 35.2 fm
[2026-07-19 08:30:18] Chart depth: 67.3 fm, delta=-10.1 fm → ANOMALY LOGGED
[2026-07-19 08:30:18] Saved: captures/v3/2026-07-19_5547.123N_13141.567W/0830_...
```

Check outputs:
- `captures/v3/[date]_.../` — PNG + JSON + markdown
- `memory/observations/YYYY-MM-DD.jsonl` — structured log
- `bathymetry/anomalies.db` — chart discrepancies

---

## Step 8: Start the Background Daemon

```powershell
python capture.py
```

**It runs forever:**
- Every 30 seconds: sounder crop + analysis + log
- Every 4 minutes: full chart screenshot + analysis
- Ctrl+C to stop gracefully

**Verify it's working:**
- Dashboard: `http://localhost:8654` → should show green lights, current position
- Logs: `tail -f capture_tray.log` (or open in Notepad++)
- New files appearing in `captures/v3/` every 30 seconds

---

## Step 9: Auto-Start at Boot (Windows Task Scheduler)

### 9.1 Create the Startup Script
Create `C:\BoatSystems\start_tzpro_agent.bat`:
```bat
@echo off
cd /d C:\BoatSystems\hermit-crab\nmea-bridge
start "NMEA Bridge" python nmea_bridge.py --port COM6 --baud 4800

timeout /t 5

cd /d C:\BoatSystems\tzpro-agent
start "TZ Pro Agent" python capture.py
```

### 9.2 Create Scheduled Task
1. Open **Task Scheduler** (Windows search → "Task Scheduler")
2. Right side → **Create Basic Task**
3. Name: `TZ Pro Agent Auto-Start`
4. Trigger: **When I log on** (or "At startup" for headless)
5. Action: **Start a program**
   - Program: `C:\BoatSystems\start_tzpro_agent.bat`
   - Start in: `C:\BoatSystems`
6. Finish → **Properties** → **General** tab:
   - ✅ Run whether user is logged on or not
   - ✅ Run with highest privileges
7. OK → enter your Windows password

### 9.3 Test It
1. Reboot the PC
2. Wait 2 minutes
3. Check dashboard: `http://localhost:8654` — should be green
4. Check `captures/v3/` — new folders appearing

---

## Step 10: Verify Everything Works (Sea Trial)

### At the Dock
- [ ] NMEA bridge running, showing NMEA sentences
- [ ] TZ Pro getting position from bridge (localhost:6007)
- [ ] Dashboard green, showing your dock position
- [ ] `python capture.py --oneshot` produces valid analysis

### Underway
- [ ] Sounder captures every 30 sec (check `captures/v3/`)
- [ ] Position updates on dashboard match TZ Pro
- [ ] Anomalies logging (check `bathymetry/anomalies.db`)
- [ ] No errors in `capture_tray.log`

### First Haul
- [ ] Run `python agent.py --brief` after haul — shows summary
- [ ] Export anomalies: `python anomaly_logger.py --export-csv --min-delta 1.0`
- [ ] Open `bathymetry/qgis_corrections.csv` in Excel/QGIS

---

## Common Configuration Tweaks

### Change Capture Interval
Edit `config.py`:
```python
SOUNDER_INTERVAL_SEC = 30      # Sounder crop every N seconds
FULL_FRAME_INTERVAL_SEC = 240  # Full screenshot every N seconds
```

### Adjust Sensitivity (More/Fewer Fish Detections)
Edit `config.py`:
```python
FISH_THRESHOLD = 180           # RGB total > this = fish return (default 180)
MIN_BLOB_AREA = 50             # Minimum pixels for a "blob"
BOTTOM_THRESHOLD = 200         # RGB total for bottom detection
```

### Add New Species Signatures
Edit `catch_patterns.py` → `SPECIES_SIGNATURES` dict:
```python
"YOUR_SPECIES": {
    "lf_hf_ratio_min": 1.5,
    "lf_hf_ratio_max": 3.0,
    "depth_range_fm": (20, 40),
    "intensity_range": (80, 200),
    "texture": "dense_cloud"
}
```

---

## Updating the Agent

```powershell
cd C:\BoatSystems\tzpro-agent
git pull origin master

cd C:\BoatSystems\hermit-crab
git pull origin memory-system
```

Then restart the daemon (Task Scheduler will restart at next boot, or manual restart).

---

## Moving to a New Boat

1. Copy `C:\BoatSystems` to new boat's PC
2. Update `config.py` for new GPS COM port, display number, crop region
3. Re-run `python bathy_contours.py` for new region (or copy `bathymetry/` folder)
4. Update TZ Pro NMEA input to new bridge IP (if different PC)
5. Test with `--oneshot`
6. Set up Task Scheduler on new PC

---

## Directory Structure After Install

```
C:\BoatSystems\
├── tzpro-agent\
│   ├── capture.py              ← RUN THIS (daemon)
│   ├── config.py               ← YOUR SETTINGS
│   ├── sounder_analyzer.py
│   ├── contour_query.py
│   ├── anomaly_logger.py
│   ├── agent.py                ← Ask questions
│   ├── bathy_contours.py       ← Run ONCE per region
│   ├── captures\v3\            ← PNG screenshots (growing)
│   ├── memory\                 ← YOUR DATA (never git)
│   │   ├── observations\       ← Daily JSONL logs
│   │   └── daily\              ← Markdown summaries
│   └── bathymetry\             ← Chart data (160 MB)
│       ├── contours\           ← 9 GeoJSON layers
│       ├── anomalies.db        ← SQLite: reality vs chart
│       └── qgis_corrections.csv ← Load into QGIS
│
└── hermit-crab\
    └── nmea-bridge\
        └── nmea_bridge.py      ← RUN THIS FIRST (bridge)
```

---

## When Things Go Wrong

| Problem | Solution |
|---------|----------|
| `python` not found | Reinstall Python with "Add to PATH" checked |
| `ImportError: PIL` | `pip install pillow` |
| `Tesseract not found` | Add `C:\Program Files\Tesseract-OCR\` to System PATH |
| "Permission denied" on folders | Run PowerShell as Admin once; or fix folder permissions |
| TZ Pro shows "No GPS" | Bridge not running OR TZ Pro not pointed to localhost:6007 |
| Captures all black | Wrong DISPLAY_NUMBER or crop region |
| Anomalies all huge | Sounder range mismatch (config vs TZ Pro setting) |
| Two capture.py processes | Task Scheduler + manual start = duplicate; kill both, restart one |

---

## Support

- **GitHub Issues:** github.com/SuperInstance/tzpro-agent/issues
- **Hermit-crab (NMEA/dashboard):** github.com/SuperInstance/hermit-crab
- **Captain's founding log:** `hermit-crab/FISHINGLOG_FOUNDING.md`

---

*Part of the CoCapn ecosystem — wire it yourself, make it yours.*
*F/V EILEEN, Ketchikan Alaska*