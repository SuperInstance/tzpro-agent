# TZ Pro Agent — Troubleshooting Guide

**When things go wrong. Start here.**

---

## Quick Diagnostic Flowchart

```
SYMPTOM
    │
    ├─► TZ Pro shows "No GPS" ──► Section A: NMEA Bridge Issues
    │
    ├─► Dashboard red / no captures ──► Section B: Capture Daemon Issues
    │
    ├─► Depth readings wrong ──► Section C: Analyzer/Calibration Issues
    │
    ├─► Chart queries return None ──► Section D: Bathymetry Grid Issues
    │
    ├─► Anomalies all huge ──► Section E: Configuration Mismatch
    │
    └─► Errors in logs ──► Section F: Error Messages Decoded
```

---

## Section A: NMEA Bridge Issues

### A1: TZ Pro Shows "No GPS" / "No Position"

**Symptoms:**
- TZ Pro chart shows "No GPS" or last known position frozen
- Dashboard at localhost:8654 shows no position or stale position
- NMEA bridge console shows no NMEA sentences scrolling

**Causes & Fixes:**

| Cause | Check | Fix |
|-------|-------|-----|
| Bridge not running | Task Manager → `nmea_bridge.py` | `cd hermit-crab\nmea-bridge && python nmea_bridge.py --port COM6 --baud 4800` |
| Wrong COM port | Device Manager → Ports | Update `--port COMx` in bridge command |
| Wrong baud rate | GPS specs (usually 4800) | Update `--baud 4800` (or 9600/38400) |
| GPS not sending | Bridge console shows nothing | Check GPS power, wiring, USB-Serial adapter |
| TZ Pro not using bridge | TZ Pro Settings → Network → NMEA Input | Add TCP: `localhost:6007`, enable it |
| Exclusive mode lock | Task Manager → two processes on COM6 | **Use ONLY our bridge** — it uses shared mode. Kill any other COM6 readers. |

**Verify Bridge Works:**
```powershell
# In bridge console, you should see scrolling:
>>> $GPGGA,123456.00,5547.1234,N,13141.5678,W,1,08,1.2,12.3,M,...
>>> $GPRMC,123456.00,A,5547.1234,N,13141.5678,W,5.2,245.1,190726,,,A*72
```

### A2: Bridge Starts But Crashes / "Access Denied"

**Error:** `PermissionError: [Errno 13] Access is denied` or `OSError: [WinError 5]`

**Cause:** COM port in use by another process, or permission issue.

**Fix:**
1. Task Manager → Details → find anything using COM6 (TZ Pro, other GPS software, `mode` command)
2. Kill those processes
3. Restart bridge as Administrator (right-click PowerShell → Run as Admin)
4. If persistent: Reboot PC, start bridge FIRST before TZ Pro

### A3: Bridge Running But No Data on :6006/:6007

**Test:**
```powershell
# Test TCP port 6006 (hermitd)
python -c "import socket; s=socket.socket(); s.connect(('localhost',6006)); print(s.recv(1024))"

# Test TCP port 6007 (TZ Pro)
python -c "import socket; s=socket.socket(); s.connect(('localhost',6007)); print(s.recv(1024))"
```

**If timeout/connection refused:** Bridge not broadcasting. Check bridge console for errors.

---

## Section B: Capture Daemon Issues

### B1: Dashboard Red / "Capture Daemon Not Running"

**Check:**
```powershell
# Is capture.py running?
tasklist | findstr capture.py

# Check logs
type capture_tray.log
```

**Common Errors in Log:**

| Error | Cause | Fix |
|-------|-------|-----|
| `ModuleNotFoundError: PIL` | Missing Pillow | `pip install pillow` |
| `ModuleNotFoundError: numpy` | Missing numpy | `pip install numpy` |
| `Tesseract not found` | OCR not in PATH | Add `C:\Program Files\Tesseract-OCR\` to System PATH |
| `Display 6 not found` | Wrong DISPLAY_NUMBER | Check Display Settings → monitor number |
| `Crop region out of bounds` | Wrong SOUNDER_CROP | Recalibrate crop (see Installation) |
| `Permission denied: captures\...` | Folder permissions | Run PowerShell as Admin once; or `icacls captures /grant Everyone:F` |

### B2: Captures All Black / Empty / Wrong Region

**Symptoms:**
- PNG files created but all black or show desktop
- Sounder crop shows menus, not water column

**Fixes:**
1. **Wrong display:** Edit `config.py` → `DISPLAY_NUMBER` (check Windows Display Settings)
2. **Wrong crop:** Edit `config.py` → `SOUNDER_CROP = (left, top, width, height)`
3. **TZ Pro not fullscreen:** TZ Pro must be maximized on target display
4. **Display scaling:** Windows Display Scaling > 100% breaks coordinates → Set to 100%

**Recalibrate Crop:**
```powershell
python capture.py --oneshot
# Check captures/v3/latest/ — open full screenshot in Paint
# Note sounder water column coordinates → update SOUNDER_CROP
```

### B3: Two capture.py Processes Running

**Symptoms:** Double captures, dual logs, resource contention

**Cause:** Task Scheduler started one + you manually started another

**Fix:**
```powershell
taskkill /f /im python.exe /fi "windowtitle eq *capture.py*"
# Then restart ONE:
python capture.py
```

**Prevent:** Disable manual start. Rely on Task Scheduler only.

### B4: Daemon Stops Silently / No New Captures

**Check:**
```powershell
# Last log entries
Get-Content capture_tray.log -Tail 50

# Disk space
df -h  # or check in Explorer

# Memory
# Task Manager → python.exe → Memory > 2 GB? Possible leak.
```

**Common Causes:**
- Disk full → `capture_tray.log` shows `OSError: [Errno 28] No space left on device`
- GPU OOM (if using Florence-2) → restart daemon
- Unhandled exception → check `capture_tray.log` for traceback

---

## Section C: Analyzer/Calibration Issues

### C1: Depth Readings Consistently Wrong

**Symptoms:** Sounder shows 50 fm, analyzer reports 30 fm (or vice versa)

| Cause | Check | Fix |
|-------|-------|-----|
| Sounder range mismatch | TZ Pro range setting vs `config.py` | Both must match (default 60 fm). If TZ Pro on 120 fm, set `SOUNDER_RANGE_FM = 120` |
| Depth scale OCR failing | `tesseract` not installed or wrong path | Verify `tesseract --version` works; check `TESSERACT_PATH` in config |
| Palette detection failed | New monitor / different TZ Pro theme | Recalibrate palette (see below) |
| Bottom detection threshold wrong | Bottom type changed (hard→soft) | Adjust `BOTTOM_THRESHOLD` in config |

### C2: Palette Detection Failed (New Monitor / Settings Changed)

**Symptoms:** "Palette dominance: unknown" or all fish counts zero

**Fix — Recalibrate Palette:**
1. Run `python capture.py --oneshot`
2. Open the cropped sounder PNG in Paint
3. Sample RGB values:
   - Background (dark water): should be ~rgb(13, 31, 54)
   - Weak returns: 130-180 total
   - Medium: 180-250 total
   - Strong: 250+ total
4. Edit `config.py` → `PALETTE_RANGES`:
```python
PALETTE_RANGES = {
    'background': (0, 100),
    'weak': (130, 180),
    'medium': (180, 250),
    'strong': (250, 765),
}
```

### C3: Fish Counts Way Too High / Low

**Too high (noise counted as fish):**
- Increase `FISH_THRESHOLD` (default 180) → try 200, 220
- Increase `MIN_BLOB_AREA` (default 50) → try 100

**Too low (missing real fish):**
- Decrease `FISH_THRESHOLD` → try 160, 140
- Decrease `MIN_BLOB_AREA` → try 20

### C4: Thermoclines Not Detected / False Positives

**Adjust in `config.py`:**
```python
THERMOCLINE_MIN_INTENSITY = 140    # Minimum return for thermocline
THERMOCLINE_MIN_WIDTH = 5          # Minimum vertical pixels
THERMOCLINE_MAX_COUNT = 15         # Max per frame
```

### C5: Bottom Type Always "Unknown" / Wrong

**Check:** `BOTTOM_TEXTURE_WINDOW` and `BOTTOM_INTENSITY_THRESHOLDS` in `config.py`

**Bottom type logic (simplified):**
```
return_intensity > 250 + smooth texture → HARD
return_intensity 180-250 + moderate texture → MEDIUM
return_intensity 130-180 + rough texture → SOFT
return_intensity < 130 → MUD
```

---

## Section D: Bathymetry Grid Issues

### D1: `contour_query.py` Returns `None` / "Outside ROI"

**Cause:** Position outside the built grid region (default: 54-59°N, 130-138°W)

**Fix — Expand Grid:**
```powershell
# Edit bathy_contours.py
ROI_LAT_MIN = 52.0   # Was 54.0
ROI_LAT_MAX = 60.0   # Was 59.0
ROI_LON_MIN = -135.0 # Was -138.0
ROI_LON_MAX = -125.0 # Was -130.0

# Rebuild (takes longer, more disk)
python bathy_contours.py
```

### D2: "No module named 'contour_query'" / Import Errors

**Cause:** Not in tzpro-agent directory, or Python path issue

**Fix:**
```powershell
cd C:\BoatSystems\tzpro-agent
python contour_query.py 55.78 -131.69
```

### D3: Grid Rebuild Takes Forever / Fails

**First run downloads 10.5 GB NOAA data.** Subsequent runs use cache.

**If fails:**
- Check disk space (need ~20 GB temp + 160 MB final)
- Check internet (downloads from NOAA)
- Resume: `bathy_contours.py` checkpoints automatically — just re-run

### D4: Charted Depth Clearly Wrong (Known Good Spot)

**Could be:**
- Grid resolution too coarse (0.001° ≈ 100m) — spot between grid cells
- NOAA data error at that location
- Tide correction not applied (soundings are MLLW)

**Workaround:** Use `get_gear_clearance` which interpolates, or average multiple nearby queries.

---

## Section E: Configuration Mismatch

### E1: All Anomalies Show Huge Deltas (10+ fm Everywhere)

**Cause:** `SOUNDER_RANGE_FM` in config ≠ TZ Pro range setting

**Fix:**
1. Check TZ Pro → Sounder → Range (e.g., "60 fm", "120 fm", "200 fm")
2. Edit `config.py` → `SOUNDER_RANGE_FM = 60` (or whatever TZ Pro shows)
3. Restart capture daemon

### E2: Anomalies Show Chart Deeper Everywhere (Negative Deltas)

**Cause:** Sounder reading transducer depth (below keel), chart is water depth

**Fix:** Add transducer offset in `config.py`:
```python
TRANSDUCER_OFFSET_FM = 2.5  # Keel to transducer in fathoms
```
Then `charted_depth - (sounder_depth + offset)` = true delta.

### E3: Timezone Issues / Timestamps Wrong

**Fix:** `config.py` → `TIMEZONE = 'America/Anchorage'` (or your IANA zone)

All timestamps stored as UTC in JSONL, displayed in local time.

---

## Section F: Error Messages Decoded

### F1: `FileNotFoundError: [Errno 2] No such file: 'bathymetry/contours/elevation_grid.npy'`

**Meaning:** Bathymetric grid not built yet.

**Fix:** `python bathy_contours.py`

### F2: `PermissionError: [Errno 13] Permission denied: 'captures\v3\...'`

**Meaning:** Windows file permissions.

**Fix:**
```powershell
# Run once as Admin:
icacls "C:\BoatSystems\tzpro-agent\captures" /grant Everyone:(OI)(CI)F /T
icacls "C:\BoatSystems\tzpro-agent\memory" /grant Everyone:(OI)(CI)F /T
icacls "C:\BoatSystems\tzpro-agent\bathymetry" /grant Everyone:(OI)(CI)F /T
```

### F3: `sqlite3.OperationalError: database is locked`

**Meaning:** Two processes writing to anomalies.db

**Fix:** Ensure only ONE `capture.py` running. Kill duplicates.

### F4: `cv2.error: OpenCV(4.x) ...` (if using OpenCV)

**Meaning:** OpenCV version mismatch or missing.

**Fix:** `pip install opencv-python` (or `opencv-python-headless`)

### F5: `ModuleNotFoundError: No module named 'torch'` / 'ultralytics'

**Meaning:** Future phase dependencies not installed.

**Fix:** `pip install torch ultralytics` (when you reach Phase 5+)

### F6: `tesseract: command not found` / `TesseractNotFoundError`

**Meaning:** Tesseract not in PATH.

**Fix:** Add `C:\Program Files\Tesseract-OCR\` to System Environment Variables → Path

### F7: `OSError: [WinError 10048] Only one usage of each socket address`

**Meaning:** Port 6006 or 6007 already in use.

**Fix:**
```powershell
netstat -ano | findstr :600
# Kill the PID shown
taskkill /f /pid <PID>
```

---

## Section G: Performance Issues

### G1: Capture Daemon Using 100% CPU

**Check:** `config.py` intervals too aggressive?
```python
SOUNDER_INTERVAL_SEC = 30    # Don't go below 10
FULL_FRAME_INTERVAL_SEC = 240
```

**Fix:** Increase intervals. 30 sec is plenty for longline.

### G2: GPU Memory Full (RTX 4050 6 GB)

**If using Florence-2 (Phase 5):**
- Reduce batch size in analyzer
- Use `torch.cuda.empty_cache()` periodically
- Or run CPU-only: `device = 'cpu'` in model load

### G3: Disk Filling Up Fast

**Captures folder grows ~500 MB/day.**

**Fixes:**
- Auto-cleanup old captures (add to `capture.py`):
```python
# Keep only last 7 days of PNGs
import glob, os, time
for f in glob.glob('captures/v3/**/*.png', recursive=True):
    if time.time() - os.path.getmtime(f) > 7*86400:
        os.remove(f)
```
- Move `captures/` to larger drive (edit `CAPTURE_DIR` in config)
- Compress old daily folders: `compact /c captures\v3\2026-07-*`

### G4: Analyzer Slow (>5 seconds per frame)

**Profile:**
```powershell
python -m cProfile -o profile.stats capture.py --oneshot
# Then analyze: python -c "import pstats; p=pstats.Stats('profile.stats'); p.sort_stats('time').print_stats(20)"
```

**Common bottlenecks:**
- Tesseract OCR (disable if not needed: `ENABLE_OCR = False`)
- Large crop region (reduce `SOUNDER_CROP` height)
- Debug logging enabled (set `LOG_LEVEL = 'WARNING'`)

---

## Section H: Recovery Procedures

### H1: Complete Reset (Nuclear Option)

```powershell
# 1. Kill everything
taskkill /f /im python.exe

# 2. Backup your data
robocopy C:\BoatSystems\tzpro-agent\memory E:\Backup\memory /MIR
robocopy C:\BoatSystems\tzpro-agent\bathymetry E:\Backup\bathymetry /MIR

# 3. Re-clone fresh
cd C:\BoatSystems
rmdir /s tzpro-agent
git clone https://github.com/SuperInstance/tzpro-agent.git

# 4. Reinstall deps
cd tzpro-agent
pip install pillow numpy

# 5. Reconfigure
notepad config.py  # Your settings

# 6. Rebuild grid
python bathy_contours.py

# 7. Test
python capture.py --oneshot

# 8. Restart bridge + daemon
```

### H2: Restore from Backup (Lost Data)

```powershell
# If memory/ or bathymetry/ corrupted:
robocopy E:\Backup\memory C:\BoatSystems\tzpro-agent\memory /MIR
robocopy E:\Backup\bathymetry C:\BoatSystems\tzpro-agent\bathymetry /MIR
```

### H3: Rollback Code (Bad Update)

```powershell
cd C:\BoatSystems\tzpro-agent
git log --oneline -10
git checkout <good-commit-hash>
# Or: git revert <bad-commit-hash>
```

---

## Section I: Getting Help

### Before Asking, Collect:
1. **Symptom description** (what, when, how often)
2. **Last 50 lines of `capture_tray.log`**
3. **Output of `python agent.py --brief`**
4. **Your `config.py` (sanitize any passwords)**
4. **Windows version, Python version (`python --version`)**

### Where to Ask:
- **GitHub Issues:** github.com/SuperInstance/tzpro-agent/issues
- **Captain (Casey):** Signal / voice — for mission-critical blocks
- **Hermit-crab issues:** github.com/SuperInstance/hermit-crab (NMEA bridge, dashboard)

---

## Emergency Contacts

| Issue | Who | How |
|-------|-----|-----|
| **No GPS at sea** | Captain | Immediate — safety issue |
| **Daemon crashed, haul in 10 min** | Restart bridge + `python capture.py` | Quick fix |
| **Chart errors dangerous** | Export anomalies → QGIS → update chartplotter | Before next set |
| **Weird readings, not sure** | `python agent.py "explain this reading"` | Agent helps diagnose |

---

*Troubleshooting is just fishing for bugs. Same patience. Same method.*
*F/V EILEEN • CoCapn*