# TZ Pro Agent — Hardware Setup & Wiring

**Physical installation guide. Print for the boatyard.**

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            F/V EILEEN — WHEELHOUSE                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌──────────────┐     USB          ┌──────────────────────────────────┐   │
│   │  u-blox GPS  │──────────────────▶│  LAPTOP (Windows 11)             │   │
│   │  NEO-M8N     │   (COM6 @ 4800)  │  ┌────────────────────────────┐  │   │
│   │  (antenna    │                   │  │ NMEA Bridge (Python)       │  │   │
│   │   on mast)   │                   │  │ - Opens COM6 SHARED MODE   │  │   │
│   └──────────────┘                   │  │ - TCP :6006 → Agent        │  │   │
│                                      │  │ - TCP :6007 → TZ Pro       │  │   │
│                                      │  └────────────────────────────┘  │   │
│                                      │  ┌────────────────────────────┐  │   │
│                                      │  │ TZ Pro Agent (Python)      │  │   │
│                                      │  │ - Captures DISPLAY6        │  │   │
│                                      │  │ - 30s sounder crops        │  │   │
│                                      │  │ - Analyzes + logs          │  │   │
│                                      │  │ - Queries bathymetry       │  │   │
│                                      │  └────────────────────────────┘  │   │
│                                      │  ┌────────────────────────────┐  │   │
│                                      │  │ Hermit Crab Dashboard      │  │   │
│                                      │  │ - http://localhost:8654    │  │   │
│                                      │  │ - NMEA position, ActiveTrack│  │   │
│                                      │  └────────────────────────────┘  │   │
│                                      └──────────────────────────────────┘   │
│                                                                             │
│   ┌────────────────────────────────────────────────────────────────────┐   │
│   │  FURUNO TZ PRO (Chartplotter + Sounder)                            │   │
│   │  ┌────────────────────┐  ┌────────────────────┐                   │   │
│   │  │  CHART DISPLAY     │  │  SOUNDER DISPLAY   │ ◀── CAPTURED      │   │
│   │  │  (Navionics/C-Map) │  │  (50/200 kHz)      │     (DISPLAY6)   │   │
│   │  └────────────────────┘  └────────────────────┘                   │   │
│   │         │                         │                                 │   │
│   │         │  NMEA Input:            │                                 │   │
│   │         │  TCP localhost:6007     │                                 │   │
│   │         └─────────────────────────┘                                 │   │
│   └────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Hardware Bill of Materials

### Required (Already on Most Boats)
| Item | Spec | Eileen's Setup | Notes |
|------|------|----------------|-------|
| **GPS Receiver** | NMEA 0183 output, 4800 baud | u-blox NEO-M8N | Antenna on mast, cable to wheelhouse |
| **Chartplotter/Sounder** | Furuno TZ Pro (TimeZero) | TZ Pro dual-band 50/200 kHz | Must support TCP NMEA input |
| **Dedicated Monitor** | 1920×1080, DisplayPort/HDMI | DISPLAY6 (6th monitor) | TZ Pro runs fullscreen on this |
| **Laptop/PC** | Win 10/11, 8+ GB RAM | AMD Ryzen AI 9 HX 370, 32 GB, RTX 4050 | Wheelhouse mounted, always on |

### Required (Add If Missing)
| Item | Part | Cost | Where |
|------|------|------|-------|
| **USB-Serial Adapter** | FTDI FT232RL or Prolific PL2303 | $15-25 | Amazon, marine electronics |
| **USB Cable** | USB-A to USB-B (or USB-C) | $5 | 6 ft for GPS to laptop |
| **Monitor Cable** | DisplayPort or HDMI | $10 | Match your GPU/monitor |

### Optional (Future Phases)
| Item | Purpose | Phase |
|------|---------|-------|
| **Deck Camera** | IP or USB, rail-mounted | 8 |
| **Starlink** | Upload data at sea | All |
| **Second GPU** | Florence-2 inference | 5 |

---

## Wiring Diagram — NMEA Bridge (Critical)

### The Problem
**TZ Pro opens COM6 in EXCLUSIVE MODE by default.** Nothing else can read the GPS.
**Our bridge opens COM6 in SHARED MODE (`FILE_SHARE_READ | FILE_SHARE_WRITE`).**

### Physical Connections

```
GPS ANTENNA (mast)
      │
      │  RG-58 / RG-213 coax
      ▼
┌─────────────────┐
│  u-blox NEO-M8N │  ← NMEA 0183 OUT (TX/RX/GND)
│  (black box)    │
�────────┬────────┘
         │
         │  3-wire: TX, RX, GND  (or USB direct if u-blox USB version)
         ▼
┌─────────────────┐
│  USB-Serial     │  ← Appears as COM6 (or COM3, COM4...)
│  Adapter        │
│  (FTDI/Prolific)│
�────────┬────────┘
         │  USB
         ▼
┌─────────────────────────────────────────────────────────────┐
│                    LAPTOP (Windows)                         │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  nmea_bridge.py                                     │   │
│  │  - Opens COM6 with SHARED MODE flags                │   │
│  │  - Reads NMEA sentences                             │   │
│  │  - Broadcasts to TCP :6006 (Agent)                  │   │
│  │  - Broadcasts to TCP :6007 (TZ Pro)                 │   │
│  └─────────────────────────────────────────────────────┘   │
│                    │                    │                   │
│                    ▼                    ▼                   │
│           ┌───────────────┐    ┌───────────────┐          │
│           │  Agent        │    │  TZ Pro       │          │
│           │  (localhost   │    │  (Settings →  │          │
│           │   :6006)      │    │   Network →   │          │
│           │               │    │   NMEA Input  │          │
│           │  capture.py   │    │   TCP :6007)  │          │
│           │  dashboard    │    │               │          │
│           │  :8654        │    │  Position OK  │          │
│           └───────────────┘    └───────────────┘          │
└─────────────────────────────────────────────────────────────┘
```

### NMEA 0183 Wiring (If Not USB Direct)

| GPS Pin | Signal | USB-Serial Pin | Notes |
|---------|--------|----------------|-------|
| TX (Out) | NMEA TX | RX (In) | Cross: GPS TX → Adapter RX |
| RX (In) | NMEA RX | TX (Out) | Cross: GPS RX → Adapter TX |
| GND | Ground | GND | Common ground essential |
| VCC | 12V/5V | — | Power from boat 12V (fused) |

**Typical u-blox NEO-M8N harness:**
- Red = VCC (12V fused)
- Black = GND
- Yellow = TX (NMEA Out)
- Green = RX (NMEA In) — often unused for receive-only

---

## TZ Pro Network Configuration

### Enable TCP NMEA Input

1. **TZ Pro Home** → **Settings** (gear icon)
2. **Network** → **NMEA Input**
3. **Add Connection:**
   - Type: **TCP Client**
   - Host: **localhost** (or 127.0.0.1)
   - Port: **6007**
   - Format: **NMEA 0183**
4. **Enable** the connection
5. **Apply** → TZ Pro should show "GPS OK" within 5 seconds

### Verify It Works
- TZ Pro chart centers on your position
- SOG/COG match dashboard at `http://localhost:8654`
- No "No GPS" warning

---

## Display Capture Setup

### Identify Your TZ Pro Display Number

1. **Right-click desktop** → **Display settings**
2. Note which number corresponds to the monitor running TZ Pro fullscreen
3. On Eileen: **Display 6** (6th monitor detected)

### Configure in `config.py`

```python
# Display capture
DISPLAY_NUMBER = 6              # Your TZ Pro monitor number

# Sounder crop region (pixels) — MUST BE CALIBRATED
# Format: (left, top, width, height) on the FULL display
SOUNDER_CROP = (1450, 120, 370, 900)  # Eileen's values for 1920×1080
```

### Calibrate the Crop Region

```powershell
# 1. Run test capture
python capture.py --oneshot

# 2. Open the full screenshot created in captures/v3/.../
#    (e.g., 2026-07-19_5547.123N_13141.567W/0830_full.png)

# 3. In Paint/Photos, find the sounder water column:
#    - Left edge pixel (from display left)
#    - Top edge pixel (from display top)
#    - Width of water column
#    - Height of water column

# 4. Update SOUNDER_CROP = (left, top, width, height)

# 5. Re-test until crop shows ONLY the water column
#    (no menus, no scale numbers on left/right, no chart tab)
```

### Display Requirements
- **TZ Pro must be fullscreen** on target display (F11 or View → Fullscreen)
- **Windows scaling = 100%** (Settings → Display → Scale 100%)
  - 125%/150% breaks pixel coordinates
- **No screensaver / sleep** on that display
- **Sounder range fixed at 60 fm** (matching `SOUNDER_RANGE_FM` in config)

---

## Power & Mounting

### Laptop Power
- **Dedicated 12V→120V inverter** (pure sine wave, 300W+)
- OR **12V DC-DC laptop charger** (match your laptop's barrel jack)
- **UPS / battery backup** recommended (15 min runtime for graceful shutdown)

### GPS Power
- **Fused 12V** from distribution panel (2A fuse)
- **Switch at helm** to power cycle GPS if needed

### Monitor Power
- **Same circuit as laptop** (inverter or shore power)
- **Brightness 100%** for consistent palette

---

## Network (Optional but Recommended)

### At Dock / Starlink
```
Laptop WiFi → Starlink / Marina WiFi → Internet
    │
    ├─→ GitHub (updates)
    ├─→ NOAA (bathymetry downloads — first run only)
    └─→ Backup (OneDrive / external NAS)
```

### At Sea (Offline)
- **Everything runs 100% offline** after initial setup
- No internet required for capture, analysis, queries
- Data syncs when connection restored

---

## Parts List with Sources (Eileen's Exact Build)

| Item | Part Number | Source | Price | Notes |
|------|-------------|--------|-------|-------|
| Laptop | ASUS ROG Zephyrus G16 (GA605) | Best Buy / ASUS | ~$1,500 | Ryzen AI 9 HX 370, RTX 4050, 32 GB |
| GPS | u-blox NEO-M8N (USB) | Amazon / u-blox | ~$40 | USB version = no serial adapter needed |
| USB-Serial | FTDI USB-RS232-WE-1800-BT | DigiKey / Mouser | ~$25 | Industrial grade, locked cable |
| Monitor | Dell U2422H 24" 1080p | Dell / Amazon | ~$200 | DisplayPort, low blue light |
| Mount | RAM Mounts RAM-D-111 | RAM Mount / West Marine | ~$80 | Laptop tray, shock mount |
| Inverter | Samlex 300W Pure Sine | Samlex / Amazon | ~$150 | Hardwire to 12V panel |
| Fuse Block | Blue Sea 5025 6-circuit | Blue Sea / West Marine | ~$40 | GPS, laptop, monitor, spare |
| Wire | Ancor 14 AWG Marine | Ancor / West Marine | ~$30 | Red/black pairs |
| Connectors | Ancor heat-shrink butt | Ancor / West Marine | ~$20 | Waterproof |

**Total (if buying all new):** ~$2,400

**Most boats already have:** GPS, TZ Pro, monitor, 12V power → **~$500 incremental**

---

## Installation Checklist

### At the Dock (Before Sea Trial)

- [ ] Laptop mounted securely (RAM mount, shock isolation)
- [ ] GPS antenna on mast, cable routed to wheelhouse
- [ ] USB-Serial adapter connected, COM port identified
- [ ] TZ Pro on dedicated monitor, fullscreen, 100% scaling
- [ ] NMEA bridge running, TZ Pro getting position from localhost:6007
- [ ] `config.py` updated: COM port, display number, paths
- [ ] Sounder crop calibrated (test capture shows only water column)
- [ ] Bathymetric grid built (`python bathy_contours.py`)
- [ ] Test capture works (`python capture.py --oneshot`)
- [ ] Dashboard accessible at `http://localhost:8654`
- [ ] Task Scheduler created for auto-start at boot
- [ ] Reboot test: PC off → on → dashboard green within 2 min

### Sea Trial

- [ ] Underway: GPS position stable on TZ Pro and dashboard
- [ ] Sounder captures every 30 sec (check `captures/v3/`)
- [ ] Depth readings match TZ Pro display (±1 fm)
- [ ] Anomalies logging (check `bathymetry/anomalies.db`)
- [ ] No errors in `capture_tray.log` after 1 hour
- [ ] Query works: `python contour_query.py <lat> <lon>`

---

## Maintenance

### Monthly
- [ ] Check disk space (`captures/` grows ~15 GB/month)
- [ ] Clean old PNGs (keep last 7 days)
- [ ] Verify GPS cable connections (salt corrosion)
- [ ] Check laptop fan/vents (dust)

### Quarterly
- [ ] Recalibrate sounder crop (monitor may shift)
- [ ] Update bathymetric grid for new areas
- [ ] Pull latest code: `git pull` in both repos
- [ ] Test backup restore

### Annually (Haul Out)
- [ ] GPS antenna inspection (mast)
- [ ] All cable runs inspection
- [ ] Laptop SSD health check
- [ ] Full data backup to shore

---

## Troubleshooting Hardware Issues

| Symptom | Likely Hardware Cause | Fix |
|---------|----------------------|-----|
| Intermittent GPS | Corroded USB-Serial connector | Dielectric grease, re-seat |
| TZ Pro loses GPS randomly | USB power management | Disable USB selective suspend in Device Manager |
| Captures shifted | Monitor moved / resolution changed | Recalibrate `SOUNDER_CROP` |
| Laptop overheats | Vent blocked / heavy GPU | Clean fans, reduce capture rate |
| Bridge won't start | COM port changed after reboot | Use USB-Serial with fixed COM (FTDI EEPROM) or udev rule |
| No sounder data | TZ Pro not fullscreen / wrong monitor | F11, check Display Settings |

---

*Wire it once. Fish with it forever.*
*F/V EILEEN • Ketchikan • CoCapn*