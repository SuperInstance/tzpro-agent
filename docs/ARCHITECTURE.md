# TZ Pro Agent — Technical Architecture

**Deep dive for developers, integrators, and the curious. Fishermen: you don't need this.**

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           TZ PRO AGENT ARCHITECTURE                             │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  EXTERNAL SYSTEMS                    INTERNAL PIPELINE                          │
│  ┌──────────────────┐                ┌──────────────────────────────────────┐  │
│  │ u-blox GPS       │──NMEA 0183───▶│ NMEA Bridge (shared mode)              │  │
│  │ COM6 @ 4800 baud │                │ - FILE_SHARE_READ|WRITE                │  │
│  └──────────────────┘                │ - TCP :6006 → hermitd                  │  │
│                                      │ - TCP :6007 → TZ Pro                   │  │
│  ┌──────────────────┐                └──────────────┬────────────────────────┘  │
│  │ Furuno TZ Pro    │                               │                           │
│  │ DISPLAY6         │                               ▼                           │
│  │ 1920×1080        │                ┌──────────────────────────────────────┐  │
│  └────────┬─────────┘                │ Capture Daemon (capture.py)          │  │
│           │ GDI+ screenshot          │ - 30s: sounder crop (370×900)        │  │
│           ▼                          │ - 4min: full frame (1920×1080)       │  │
│  ┌──────────────────┐                │ - screenshot.ps1 (PowerShell GDI+)   │  │
│  │ Sounder Analyzer │                │ - _log_and_analyze() per frame       │  │
│  │ (sounder_        │                └──────────────┬────────────────────────┘  │
│  │  _analyzer.py)   │                               │                           │
│  └────────┬─────────┘                               ▼                           │
│           │                     ┌──────────────────────────────────────────┐    │
│           │ OpenCV                  │ _log_and_analyze()                    │    │
│           │ processing              │                                        │    │
│           ▼                         │ ┌─────────────────┐ ┌───────────────┐ │    │
│  ┌──────────────────┐              │ │ sounder_analyzer│ │ contour_query │ │    │
│  │ Bathymetric Grid │              │ │ .py             │ │ .py           │ │    │
│  │ (numpy float32,  │              │ │ - Palette detect│ │ - 0.001° grid │ │    │
│  │  5000×8000,      │              │ │ - Background sub│ │ - get_depth_fm│ │    │
│  │  153 MB)         │              │ │ - Bottom detect │ │ - get_gear_   │ │    │
│  └────────┬─────────┘              │ │ - Depth OCR     │ │   clearance   │ │    │
│           │                        │ │ - Fish returns  │ │ - get_contour_│ │    │
│           │                        │ │ - Thermoclines  │ │   bands       │ │    │
│           │                        │ │ - Bottom type   │ └───────┬───────┘ │    │
│           │                        │ └────────┬────────┘         │        │    │
│           │                        │          │                │        │    │
│           │                        │          ▼                ▼        │    │
│           │                        │ ┌─────────────────────────────────┐ │    │
│           │                        │ │ anomaly_logger.py               │ │    │
│           │                        │ │ - delta = sounder_fm - chart_fm │ │    │
│           │                        │ │ - SQLite INSERT                 │ │    │
│           │                        │ │ - QGIS CSV/GeoJSON export      │ │    │
│           │                        │ └─────────────────────────────────┘ │    │
│           │                        └────────────────────────────────────┘    │
│           ▼                                                                   │
│  ┌──────────────────┐                                                         │
│  │ Data Stores      │                                                         │
│  │ - memory/obs/    │  JSONL daily logs (append-only, permanent)             │
│  │ - captures/v3/   │  PNG + JSON + MD per capture                            │
│  │ - bathymetry/    │  anomalies.db, contours/, elevation_grid.npy           │
│  └──────────────────┘                                                         │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Core Modules

### 1. NMEA Bridge (`hermit-crab/nmea-bridge/nmea_bridge.py`)

**Purpose:** Share single GPS (COM6) with multiple consumers via TCP.

**Key Implementation Details:**
```python
# Shared mode flags — critical for coexistence with TZ Pro
handle = CreateFileA(
    port, GENERIC_READ | GENERIC_WRITE,
    FILE_SHARE_READ | FILE_SHARE_WRITE,  # <-- THIS IS THE FIX
    None, OPEN_EXISTING, 0, None
)

# Dual-port broadcast
server_6006 = socket.bind(('0.0.0.0', 6006))  # hermitd, agent
server_6007 = socket.bind(('0.0.0.0', 6007))  # TZ Pro

# INVALID_HANDLE bug fix (Python 3.13 64-bit)
CreateFileA.restype = ctypes.c_void_p  # Not c_int!
```

**Protocol:** Raw NMEA 0183 sentences (`$GPGGA`, `$GPRMC`, etc.) newline-delimited.

---

### 2. Capture Daemon (`capture.py`, `capture_v3.py`)

**Dual-Cadence Loop:**
```python
SOUNDER_INTERVAL_SEC = 30      # Sounder crop only
FULL_FRAME_INTERVAL_SEC = 240  # Full screenshot + analysis
```

**Capture Flow:**
```
capture.py (main loop)
    │
    ├─▶ screenshot.ps1 (PowerShell GDI+)
    │     CaptureSpecificDisplay(display_num) → Bitmap → PNG bytes
    │
    ├─▶ PIL crop (SOUNDER_CROP region)
    │
    ├─▶ sounder_analyzer.analyze_sounder(cropped_image)
    │
    ├─▶ contour_query.get_depth_fm(lat, lon)  # from NMEA bridge
    │
    ├─▶ anomaly_logger.log_anomaly(...)  # if |delta| > threshold
    │
    ├─▶ Save to captures/v3/{date}_{lat}_{lon}/
    │     {time}_{lat}_{lon}.png      # Cropped sounder
    │     {time}_{lat}_{lon}.json     # Full analysis
    │     {time}_{lat}_{lon}.md       # Human summary
    │
    └─▶ Append to memory/observations/YYYY-MM-DD.jsonl
```

**Output Formats:**
- **PNG:** Cropped sounder (370×900) or full frame (1920×1080)
- **JSON:** Complete analysis + metadata (see Data Formats)
- **Markdown:** Human-readable summary with key metrics

---

### 3. Sounder Analyzer (`sounder_analyzer.py`)

**Processing Pipeline:**
```python
def analyze_sounder(image: Image) -> SounderAnalysis:
    # 1. Convert to numpy array (RGB)
    arr = np.array(image)  # (H, W, 3)
    
    # 2. Palette detection (confirms display mode)
    palette = detect_palette(arr)
    
    # 3. Background subtraction (remove dark blue noise)
    signal = subtract_background(arr, palette.background_range)
    
    # 4. Bottom detection (strongest horizontal band)
    bottom_y, bottom_fm, confidence = find_bottom(signal, depth_scale)
    
    # 5. Depth scale OCR (Tesseract)
    depth_scale = ocr_depth_scale(arr)  # Reads numbers on left edge
    
    # 6. Fish returns (pixels above threshold in water column)
    fish_blobs = detect_fish_returns(signal[:bottom_y], FISH_THRESHOLD)
    
    # 7. Thermoclines (horizontal bands above bottom)
    thermoclines = detect_thermoclines(signal[:bottom_y])
    
    # 8. Bottom type classification
    bottom_type = classify_bottom(signal[bottom_y:bottom_y+window])
    
    # 9. Vocabulary prediction (species heuristic)
    vocabulary = predict_species(fish_blobs, thermoclines, bottom_type)
    
    return SounderAnalysis(...)
```

**Key Heuristics:**
```python
# Palette (TZ Pro blue→red)
BACKGROUND_RANGE = (0, 100)      # Dark navy
WEAK_RANGE = (130, 180)          # Cyan — plankton, soft mud
MEDIUM_RANGE = (180, 250)        # Yellow-green — fish, thermoclines
STRONG_RANGE = (250, 765)        # Orange-red — hard bottom, dense schools

# Thresholds
FISH_THRESHOLD = 180             # RGB sum > this = target
MIN_BLOB_AREA = 50               # Minimum pixels for a blob
BOTTOM_THRESHOLD = 200           # Bottom detection sensitivity
```

---

### 4. Bathymetric Grid (`bathy_contours.py`, `contour_query.py`)

**Grid Specifications:**
```
Region:          54.0°N to 59.0°N, 130.0°W to 138.0°W (SE Alaska)
Resolution:      0.001° ≈ 100m at 55°N
Dimensions:      5,000 × 8,000 cells
Data type:       float32 (4 bytes/cell)
Memory:          153 MB (memory-mapped)
Source:          NOAA 71326.xyz (237M soundings, 10.5 GB)
Contour layers:  9 (5, 10, 20, 30, 48, 60, 80, 100, 150 fm)
Algorithm:       Marching squares on interpolated grid
```

**Query Performance:**
```python
# First load: ~200ms (memory-maps 153 MB npy)
# Subsequent:  <1 µs (direct array index)

def get_depth_fm(lat: float, lon: float) -> float:
    row = int((LAT_MAX - lat) / RESOLUTION)
    col = int((lon - LON_MIN) / RESOLUTION)
    return GRID[row, col] * METERS_TO_FATHOMS
```

**Contour Extraction (GeoJSON):**
```python
# Marching squares at each depth level
for depth_fm in [5, 10, 20, 30, 48, 60, 80, 100, 150]:
    contours = measure.find_contours(grid, depth_fm * FM_TO_METERS)
    geojson = contours_to_geojson(contours, depth_fm)
    save(f"contours_{depth_fm}fm.geojson")
```

---

### 5. Anomaly Logger (`anomaly_logger.py`)

**Database Schema:**
```sql
CREATE TABLE bathymetry_anomalies (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,          -- ISO 8601 UTC
    lat          REAL NOT NULL,
    lon          REAL NOT NULL,
    sog          REAL,                   -- Speed over ground (kts)
    sounder_fm   REAL NOT NULL,          -- Sounder reading
    contour_fm   REAL,                   -- Charted depth
    delta_fm     REAL,                   -- sounder - contour
    source       TEXT DEFAULT 'capture', -- capture|manual|import
    cruise       TEXT,                   -- Optional cruise ID
    created_at   TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_anomalies_position ON bathymetry_anomalies(lat, lon);
CREATE INDEX idx_anomalies_time ON bathymetry_anomalies(ts);
CREATE INDEX idx_anomalies_delta ON bathymetry_anomalies(delta_fm);
```

**Export Formats:**
- **CSV:** `Longitude, Latitude, Depth` (QGIS-ready)
- **GeoJSON:** FeatureCollection with delta_fm properties
- **Stats:** Count, mean |delta|, max/min, by region

---

## Data Formats

### Observation JSONL (`memory/observations/YYYY-MM-DD.jsonl`)
```json
{
  "ts": "2026-07-18T16:00:00+00:00",
  "sounder": "tzpro_20260718_080000_sounder.png",
  "position": {"lat": 55.78853, "lon": -131.69630},
  "vessel": {"sog": 1.59, "cog": 209},
  "sounder_analysis": {
    "depth_fm": 57.2,
    "pixel_y": 599,
    "bottom_type": "soft_mud",
    "confidence": "high",
    "fish_returns": {
      "count": 557,
      "density_per_100kpx": 1674.3,
      "avg_intensity": 91.2,
      "max_intensity": 255,
      "depth_range_fm": [20.0, 40.0],
      "distribution": "dense_midwater",
      "largest_blob": {
        "depth_fm": 31.9,
        "area_px": 279403,
        "intensity": 121.9,
        "centroid_px": [185, 342]
      }
    },
    "thermoclines_fm": [16.1, 26.1, 35.2],
    "signal_profile": {
      "avg_color": "rgb(13,34,54)",
      "signal_strength": 0.134,
      "palette_dominance": "blue"
    },
    "vocabulary": "chum"
  },
  "chart_comparison": {
    "charted_fm": 67.3,
    "delta_fm": -10.1,
    "anomaly_logged": true
  }
}
```

### Capture JSON (`captures/v3/.../*.json`)
```json
{
  "capture": {
    "ts": "2026-07-18T16:00:00+00:00",
    "display": 6,
    "crop": {"left": 1450, "top": 120, "width": 370, "height": 900},
    "full_frame": "0800_full.png",
    "sounder_crop": "0800_sounder.png"
  },
  "nmea": {
    "lat": 55.78853,
    "lon": -131.69630,
    "sog": 1.59,
    "cog": 209,
    "timestamp": "2026-07-18T16:00:00.123Z"
  },
  "analysis": { ...same as observation.sounder_analysis... },
  "chart": { ...same as observation.chart_comparison... }
}
```

---

## Configuration (`config.py`)

```python
# === GPS / NMEA ===
NMEA_PORT = "COM6"
NMEA_BAUD = 4800
NMEA_BRIDGE_HOST = "localhost"
NMEA_BRIDGE_PORT_HERMITD = 6006
NMEA_BRIDGE_PORT_TZPRO = 6007

# === Display Capture ===
DISPLAY_NUMBER = 6
SOUNDER_CROP = (1450, 120, 370, 900)  # (left, top, width, height)
FULL_FRAME_CROP = None  # None = full display

# === Capture Cadence ===
SOUNDER_INTERVAL_SEC = 30
FULL_FRAME_INTERVAL_SEC = 240

# === Sounder Settings ===
SOUNDER_RANGE_FM = 60          # Must match TZ Pro range setting
TRANSDUCER_OFFSET_FM = 0.0     # Keel to transducer

# === Analysis Thresholds ===
FISH_THRESHOLD = 180
MIN_BLOB_AREA = 50
BOTTOM_THRESHOLD = 200
THERMOCLINE_MIN_INTENSITY = 140
THERMOCLINE_MIN_WIDTH = 5

# === Palette (TZ Pro blue→red) ===
PALETTE_RANGES = {
    'background': (0, 100),
    'weak': (130, 180),
    'medium': (180, 250),
    'strong': (250, 765),
}

# === Bathymetry ===
BATHY_GRID_PATH = Path("bathymetry/contours/elevation_grid.npy")
ANOMALY_THRESHOLD_FM = 1.0     # Log if |delta| > this

# === Paths ===
DATA_ROOT = Path("D:/BoatData")
CAPTURE_DIR = DATA_ROOT / "captures"
MEMORY_DIR = DATA_ROOT / "memory"
BATHY_DIR = DATA_ROOT / "bathymetry"

# === Tesseract ===
TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# === Timezone ===
TIMEZONE = "America/Anchorage"
```

---

## Deployment Architecture

### Processes (Production)

| Process | Command | Restart Policy | Ports |
|---------|---------|----------------|-------|
| **NMEA Bridge** | `python nmea_bridge.py --port COM6 --baud 4800` | Always (Task Scheduler) | 6006, 6007 |
| **Capture Daemon** | `python capture.py` | Always (Task Scheduler) | — |
| **Hermitd Dashboard** | `python hermitd.py` | Always (Task Scheduler) | 8654 |
| **Docker MCP** | `docker run ... mcp/playwright` | Always (Docker restart policy) | 3100 |

### Windows Task Scheduler Setup
```xml
<!-- Trigger: At log on -->
<!-- Action: powershell.exe -Command "cd C:\BoatSystems\hermit-crab\nmea-bridge; Start-Process python nmea_bridge.py --port COM6 --baud 4800" -->
<!-- Action: powershell.exe -Command "cd C:\BoatSystems\tzpro-agent; Start-Process python capture.py" -->
<!-- Action: powershell.exe -Command "cd C:\BoatSystems\hermit-crab; Start-Process python hermitd.py" -->
```

### Directory Structure (Runtime)
```
tzpro-agent/
├── capture.py              # Main daemon
├── capture_v3.py           # V3 capture (PNG+JSON+MD)
├── capture_tray.py         # System tray UI
├── sounder_analyzer.py     # OpenCV analysis
├── screenshot.py / .ps1    # GDI+ capture
├── config.py               # All settings
├── contour_query.py        # Fast depth lookup
├── bathy_contours.py       # Grid builder (run once)
├── bathy_preprocess.py     # NOAA scan (run once)
├── anomaly_logger.py       # SQLite + exports
├── agent.py                # NL query interface
├── catch_link.py           # Catch ↔ sounder correlation
├── catch_patterns.py       # Species signatures
├── memory/                 # GITIGNORED — YOUR DATA
│   ├── observations/       # Daily JSONL (permanent)
│   ├── daily/              # Markdown summaries
│   └── index/              # Search index
├── bathymetry/             # GITIGNORED — CHART DATA
│   ├── contours/           # 9 GeoJSON layers
│   ├── anomalies.db        # SQLite
│   ├── elevation_grid.npy  # 153 MB float32 grid
│   └── qgis_corrections.csv
├── captures/v3/            # Growing PNG archive
│   └── YYYY-MM-DD_.../     # Per-capture folders
├── docs/                   # Documentation
│   ├── ARCHITECTURE.md     # This file
│   ├── QUICK_REFERENCE.md
│   ├── INSTALLATION.md
│   ├── DAILY_WORKFLOW.md
│   ├── QUERY_EXAMPLES.md
│   ├── TROUBLESHOOTING.md
│   └── HARDWARE_SETUP.md
└── README.md               # Fisherman's manual
```

---

## Extending the System

### Adding New Species Signatures
```python
# catch_patterns.py
SPECIES_SIGNATURES = {
    "NEW_SPECIES": {
        "lf_hf_ratio_range": (1.5, 3.0),
        "depth_range_fm": (20, 40),
        "intensity_range": (80, 200),
        "blob_texture": "dense_cloud",
        "thermocline_association": True,
        "bottom_association": "soft_mud",
    }
}
```

### Adding New Analysis Modules
```python
# New file: my_analyzer.py
from sounder_analyzer import SounderAnalysis

def analyze_my_thing(analysis: SounderAnalysis) -> MyResult:
    # Access: analysis.fish_returns, analysis.thermoclines_fm, etc.
    ...

# In capture.py _log_and_analyze():
from my_analyzer import analyze_my_thing
my_result = analyze_my_thing(sounder_analysis)
```

### Custom Export Formats
```python
# In anomaly_logger.py or new module
def export_geopackage(anomalies, path):
    import geopandas as gpd
    gdf = gpd.GeoDataFrame(anomalies, geometry=gpd.points_from_xy(anomalies.lon, anomalies.lat))
    gdf.to_file(path, driver="GPKG")
```

---

## Performance Characteristics

| Operation | Latency | Throughput |
|-----------|---------|------------|
| Screen capture (GDI+) | ~800 ms | 1.2/sec max |
| Sounder crop (PIL) | ~5 ms | — |
| OpenCV analysis | ~1.2 s | 0.8/sec |
| Bathymetry query | < 1 µs | 1M+/sec |
| Anomaly log (SQLite) | ~2 ms | 500/sec |
| JSONL append | ~1 ms | 1000/sec |
| **Full 30-sec cycle** | **~2.1 s** | **Sustainable** |

**Bottlenecks:**
1. GDI+ screenshot (Windows limitation) — cannot go faster than ~1/sec
2. Tesseract OCR (~400 ms) — disable if not needed: `ENABLE_OCR = False`
3. OpenCV morphology on 370×900 — optimized with vectorized ops

---

## Future Phases (Architecture Evolution)

### Phase 4: ZeroClaw Agent Loop
```
capture.py → message queue → ZeroClaw Agent → alerts / NL queries / actions
                    │
                    ├─▶ Alert engine (anomaly > threshold, new species)
                    ├─▶ NL interface (agent.py enhanced)
                    └─▶ Action triggers (mark waypoint, log catch, notify)
```

### Phase 5: Florence-2 Vision Model
```
sounder_crop → Florence-2 (RTX 4050) → structured echogram reading
                    │
                    ├─▶ Bottom depth (pixel → fm calibration)
                    ├─▶ Fish count/species/size (trained)
                    ├─▶ Thermoclines (explicit detection)
                    └─▶ Confidence scores
```

### Phase 6: DAW Dashboard
```
Web UI (React/MapLibre) at localhost:8655
├─▶ Timeline scrubber (replay day)
├─▶ Map with anomaly layer
├─▶ Sounder filmstrip
├─▶ Species filter
└─▶ NL query box
```

### Phase 7: Catch Correlation
```
catch_log.csv + sounder_observations → labeled dataset
                    │
                    ├─▶ (LF_patch, HF_patch, species, size, depth_fm)
                    └─▶ Retrain analyzer / Florence-2
```

### Phase 8: Deck Camera → Sounder Correlation
```
deck_camera (hail/hook) → timestamp match → sounder frame → depth estimate
                    │
                    ├─▶ Hook counter (CV)
                    ├─▶ Fish detector/classifier per hook
                    ├─▶ Size estimation (reference markers)
                    └─▶ Training loop (camera labels ↔ sounder truth)
```

---

## Invariants (Architectural Principles)

1. **Single responsibility per copilot** — capture.py only captures; analyzer only analyzes
2. **Append-only data** — JSONL logs never modified; anomalies only INSERT
3. **Offline-first** — no cloud dependency for core loop
4. **Human-readable + machine-readable** — every artifact has both .md and .json
5. **Configuration over code** — thresholds, paths, crop regions in config.py
6. **Calibration is data** — palette, crop, offsets stored, not hardcoded
7. **The chart is alive** — every pass updates bathymetry_anomalies
8. **Fail loud, recover fast** — log errors, watchdog restarts, no silent failures
9. **Repo is the seed** — hardware changes, models change, code persists

---

*Technical spec for the machine. The fisherman reads the manual.*
*F/V EILEEN • CoCapn*