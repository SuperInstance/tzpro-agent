# ZeroClaw — TzPro-Agent Integration Architecture

**Document Version:** 1.0  
**Date:** 2026-07-15  
**Author:** Systems Architecture  
**Platform:** F/V EILEEN — Windows 11, RTX 4050 6GB, dual monitors  
**Ecosystem:** CoCapn.com / ActiveLedger.ai / FishingLog.ai  

---

## Table of Contents

1. [Overview & Philosophy](#1-overview--philosophy)
2. [Two Deployment Modes](#2-two-deployment-modes)
3. [Sensor Pipeline](#3-sensor-pipeline)
4. [ZeroClaw Agent Loop](#4-zeroclaw-agent-loop)
5. [Contour Cache](#5-contour-cache)
6. [Filtered Mode — Riker Integration](#6-filtered-mode--riker-integration)
7. [Data Flow Diagrams](#7-data-flow-diagrams)
8. [Operational States & Failure Modes](#8-operational-states--failure-modes)
9. [Implementation Roadmap](#9-implementation-roadmap)

---

## 1. Overview & Philosophy

### What ZeroClaw Is

ZeroClaw is a specialized spatial-temporal reasoning agent that lives between the raw sensor pipeline (tzpro-agent's capture + analysis daemons) and the human-facing interface (Riker, the OpenClaw main agent). It answers the question: *"Where should the boat be right now, given everything we know?"*

ZeroClaw consumes two categories of input:

| Category | Source | Nature |
|----------|--------|--------|
| **Live observations** | tzpro-agent sounder pipeline (every 30s) | Depth, bottom type, fish returns, position, SOG |
| **Reference knowledge** | Bathymetric contour cache, seasonal patterns, historical catch data | Persistent, slower-changing |

It answers natural-language queries like:

- *"What's the bottom doing ahead of us?"*
- *"Show me the 20-fathom ledge we crossed last Tuesday."*
- *"Are we on top of the halibut from July 14th?"*
- *"Where's the edge of the drop-off from this morning?"*

### Philosophy

ZeroClaw follows the Turbo-Shell pattern: narrow scope, perfect focus. Its territory is the relationship between *where we are now*, *what the bottom looks like*, and *what that means*. It does not capture screens. It does not analyze pixels. It does not talk to the Captain. It answers Riker's questions about position, depth, and pattern.

The invariant concept: **Read observations, query the contour cache, maintain spatial memory, answer queries about the intersection of position and depth.**

---

## 2. Two Deployment Modes

### Mode A: Standalone (Direct Agent)

```
┌──────────────────────────────────────────────────────┐
│                   TZ Pro Display                     │
│                   (DISPLAY6)                         │
└──────────────────┬───────────────────────────────────┘
                   │
    ┌──────────────┼──────────────┐
    │              │              │
    ▼              ▼              ▼
┌────────┐  ┌────────────┐  ┌──────────┐
│capture │  │ sounder_   │  │screenshot│
│  .py   │  │ analyzer.py│  │  .ps1    │
└───┬────┘  └─────┬──────┘  └──────────┘
    │             │
    │   ┌─────────┘
    ▼   ▼
┌──────────────┐      ┌──────────────┐
│  logger.py   │◄─────│  hermitd     │
│  daily JSONL │      │  NMEA :8654  │
└──────┬───────┘      └──────────────┘
       │
       ▼
┌──────────────────────────────────────┐
│           ZeroClaw Agent             │
│  ┌────────────────────────────────┐  │
│  │  • Read observations (JSONL)   │  │
│  │  • Query contour cache         │  │
│  │  • Maintain spatial memory     │  │
│  │  • Answer NL queries           │  │
│  └────────────────────────────────┘  │
│                                      │
│  Direct output → stdout / Telegram   │
└──────────────────────────────────────┘
```

**Standalone mode** runs when ZeroClaw is the active agent on the boat, talking directly to the Captain or another human operator. In this mode:

1. ZeroClaw reads from the tzpro-agent memory directory (`tzpro-agent/memory/observations/YYYY-MM-DD.jsonl`)
2. ZeroClaw has direct access to the contour cache (local filesystem)
3. ZeroClaw emits responses directly to the communication channel (console, Telegram, or a simple HTTP endpoint)
4. No filtering, no intermediate agent — ZeroClaw is the front line

**Use case:** Solo operator without Riker. One-boat setup. Captain runs `zeroclaw query "where's the edge"` from the wheelhouse.

### Mode B: Filtered Through Riker (Recommended Production Mode)

```
┌──────────────────────────────────────────────────────┐
│                   TZ Pro Display                     │
│                   (DISPLAY6)                         │
└──────────────────┬───────────────────────────────────┘
                   │
    ┌──────────────┼──────────────┐
    │              │              │
    ▼              ▼              ▼
┌────────┐  ┌────────────┐  ┌──────────┐
│capture │  │ sounder_   │  │screenshot│
│  .py   │  │ analyzer.py│  │  .ps1    │
└───┬────┘  └─────┬──────┘  └──────────┘
    │             │
    │   ┌─────────┘
    ▼   ▼
┌──────────────┐      ┌──────────────┐
│  logger.py   │◄─────│  hermitd     │
│  daily JSONL │      │  NMEA :8654  │
└──────┬───────┘      └──────────────┘
       │
       ▼
┌──────────────────────────────────────┐
│        Shared Directory              │
│   tzpro-agent/shared/zeroclaw/       │
│  ┌────────────────────────────────┐  │
│  │  observations.jsonl (latest)   │  │
│  │  position.json     (live)      │  │
│  │  contour_cache/    (queries)   │  │
│  │  alerts.txt         (events)   │  │
│  │  zeroclaw_out.txt  (replies)   │  │
│  │  zeroclaw_in.txt   (requests)  │  │
│  └────────────────────────────────┘  │
└──────┬───────────────┬───────────────┘
       │               │
       ▼               ▼
┌──────────────┐  ┌───────────────────┐
│  ZeroClaw    │  │  Riker (OpenClaw) │
│  (reader +   │  │  (reader +        │
│   writer)    │  │   filter + relay) │
└──────────────┘  └────────┬──────────┘
                           │
                           ▼
                    ┌──────────────┐
                    │  Telegram /  │
                    │  Captain     │
                    └──────────────┘
```

**Filtered mode** is the production deployment. In this mode:

1. ZeroClaw and Riker communicate through a shared directory (`tzpro-agent/shared/zeroclaw/`)
2. ZeroClaw writes observations, analyses, and replies to the shared directory
3. Riker reads from the shared directory, applies filtering rules, and relays to the Captain
4. ZeroClaw never talks to the Captain directly — Riker is the sole interface to the human
5. Riker can suppress, prioritize, augment, or redirect ZeroClaw's output

**The shared directory protocol:**

| File | Direction | Content | Update Cadence |
|------|-----------|---------|---------------|
| `observations.jsonl` | tzpro-agent → ZeroClaw | Last N observations (stream) | Every 30s (sounder) |
| `position.json` | tzpro-agent → ZeroClaw | Current NMEA state {lat, lon, sog, cog} | Every 10s |
| `zeroclaw_in.txt` | Riker → ZeroClaw | NL queries from Captain | On demand |
| `zeroclaw_out.txt` | ZeroClaw → Riker | Structured replies | On query completion |
| `alerts.txt` | ZeroClaw → Riker | Proactive alerts (edge, depth, pattern) | When triggered |
| `contour_cache/` | Both (read) | Vector tile contour data | Pre-computed, on-disk |

---

## 3. Sensor Pipeline

The sensor pipeline is the foundation. Everything ZeroClaw knows originates here. Three components work in sequence:

### 3.1 `screenshot.ps1` — Raw Frame Capture

```powershell
# capture_monitor2.ps1 — Capture DISPLAY6 (TZ Pro feed)
# DISPLAY6 = 1920x1080 at X=1920, Y=0

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

$x = 1920; $y = 0; $width = 1920; $height = 1080

$bitmap = New-Object System.Drawing.Bitmap($width, $height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($x, $y, 0, 0, $bitmap.Size)
$graphics.Dispose()
$bitmap.Save($fullPath, [System.Drawing.Imaging.ImageFormat]::Png)
$bitmap.Dispose()
```

**Key details:**
- Uses `System.Drawing.Graphics.CopyFromScreen` — native Windows GDI+, no dependencies
- Captures the second monitor at physical pixel offset X=1920
- Output: 1920×1080 PNG, ~1-3 MB per frame
- Called by `screenshot.py` as a subprocess via `subprocess.run()`
- Timeout: 15 seconds. Failure logs a warning, does not crash the loop.

### 3.2 `capture.py` — Dual-Cadence Capture Daemon

```
   ┌──────────────────────────────────────────────────────┐
   │                  capture.py loop                     │
   │                                                      │
   │   sleep(5) ◄──────────────────────────────┐          │
   │      │                                     │          │
   │      ▼                                     │          │
   │   read_nmea()  ─── hermitd :8654/vessel    │          │
   │      │                                     │          │
   │      ├── [time - last_full >= 240s?]       │          │
   │      │      ├── YES → capture_full()       │          │
   │      │      │         └── crop_region()    │          │
   │      │      │             └── _log_and_analyze() ──┘ │
   │      │      │                                         │
   │      │      └── NO  → [time - last_sounder >= 30s?]   │
   │      │                   ├── YES → capture_sounder()   │
   │      │                   │         └── _log_and_analyze() ──┘
   │      │                   └── NO  → sleep(5) ──┘
   │                                                      │
   └──────────────────────────────────────────────────────┘
```

**Dual cadence explained:**

| Event | Interval | What Happens | Disk Impact |
|-------|----------|-------------|-------------|
| **Sounder crop** | 30 seconds | Full frame captured → sounder cropped (370×900) → full frame deleted → crop saved | ~100 KB/crop |
| **Full frame** | 4 minutes | Full frame captured → sounder cropped → both saved | ~3 MB/frame |
| **Analysis** | Every capture | `sounder_analyzer.py` runs on the crop → depth, bottom type, fish returns extracted → logged to JSONL | ~500 bytes JSONL |

**Sounder crop region** (from `config.py`):
```python
SOUNDER_CROP = (1540, 100, 1910, 1000)  # (x1, y1, x2, y2) on 1920×1080
```
This isolates the TZ Pro sounder/fishfinder panel from the full display. The region is 370px wide × 900px tall, starting below the top data bars and ending above the bottom control bar.

**NMEA integration:**
```python
NMEA_VESSEL_URL = "http://127.0.0.1:8654/vessel"  # hermitd endpoint
```
Every capture is paired with live lat/lon/SOG/COG from the NMEA bridge. If the bridge is unreachable, the capture proceeds without position — no data loss.

### 3.3 `sounder_analyzer.py` — Image-to-Data Pipeline

The sounder analyzer takes a 370×900 RGB PNG and returns a structured dict. It uses two analysis paths:

#### Path A: OpenCV-style Pixel Analysis (Current, Production)

```
┌──────────────┐     ┌──────────────────┐     ┌────────────────┐
│ Sounder PNG  │────▶│ 1. OCR Depth     │────▶│ depth_scale[]  │
│ 370×900 RGB  │     │    Scale (right) │     │ [0,20,40,60]   │
└──────────────┘     └──────────────────┘     └────────────────┘
       │                                              │
       ▼                                              ▼
┌──────────────────┐     ┌──────────────────┐    calibration
│ 2. Column Scan   │────▶│ bottom_pixel_y   │──────────────┐
│    bottom-up     │     │ median over cols │              │
│    per column    │     └────────┬─────────┘              │
└──────────────────┘              │                        │
       │                          ▼                        │
       ▼                   ┌──────────────┐                │
┌──────────────────┐       │ bottom_depth │◄───────────────┘
│ 3. Bottom        │       │   _fm         │
│    Classification │       │               │
│  • avg color      │       │ bottom_type   │
│  • stddev         │       │ confidence    │
│  • roughness      │       └──────────────┘
└──────────────────┘
       │
       ▼
┌──────────────────┐
│ 4. Fish Returns  │
│    above bottom  │
│  • count         │
│  • density       │
│  • depth range   │
│  • distribution  │
└──────────────────┘
```

**Palette calibration (confirmed by Captain):**
```
Background:     rgb(14, 29, 52)   — very dark navy, avg RGB total ≈ 107
Weak returns:   blue→cyan          — 130-180 total RGB (soft mud, plankton)
Medium returns: yellow→green       — 180-250 total RGB (fish schools, thermoclines)
Strong returns: orange→red         — 250+ total RGB (hard bottom, dense schools)
```

**Key thresholds from `config.py`:**
```python
RGB_THRESHOLD_BACKGROUND = 107   # ignore below this
RGB_THRESHOLD_FISH       = 180   # fish/thermocline threshold
RGB_THRESHOLD_STRONG     = 250   # hard bottom threshold
BOTTOM_EXCLUSION_PX      = 30    # exclude bottom band from fish detection
```

**Bottom classification logic:**
```python
if avg_r > 200 and avg_g > 100:   → "hard"
elif avg_g > avg_r and avg_g > 150: → "medium"
elif avg_b > avg_r and avg_b > 100: → "soft_mud"
elif max(avg_r, avg_g, avg_b) < 80: → "very_soft"
else:                              → "mixed"
```

**Depth calibration:** OCR reads the depth scale numbers from the right ~20px strip of the sounder panel using Tesseract. If OCR fails or returns empty, the pipeline falls back to proportional estimation using `DEFAULT_MAX_DEPTH_FM = 80`.

#### Path B: Florence-2 VL Analysis (Planned, Vision Pipeline)

An alternative analysis path using `microsoft/Florence-2-base` (232M params, ~500 MB VRAM in FP16). The vision model is loaded by `vision.py` and provides two prompt tracks:

| Track | Cadence | Prompt | Output |
|-------|---------|--------|--------|
| **Chart state** | 4 minutes | `<CAPTION>Describe the navigation chart display: position, course overlay, waypoints, alarms, and vessel track.` | Natural language chart description |
| **Sounder analysis** | 30 seconds | `<OD>What is in this fishfinder image? Describe: bottom depth, bottom type, fish or schools, thermoclines.` | Structured extraction |

**GPU scheduling constraint:** Florence-2 and Ollama share 6GB VRAM on the RTX 4050. They cannot coexist. The 30-second cadence time-multiplexes: Florence-2 analyzes the screen (2-3s inference), then releases VRAM. Ollama serves companion queries in the remaining time.

#### Analyzer Output Schema

Every capture produces this structured observation:

```json
{
  "ts": "2026-07-15T18:59:40+00:00",
  "sounder": "frame_20260715_105940_sounder.png",
  "position": {
    "lat": 55.785,
    "lon": -131.527
  },
  "vessel": {
    "sog": 1.6,
    "cog": 265
  },
  "sounder_analysis": {
    "depth_fm": 22.5,
    "pixel_y": 301,
    "bottom_type": "hard",
    "confidence": "high",
    "fish": {
      "count": 45,
      "density_per_100kpx": 13.5,
      "avg_intensity": 195.2,
      "depth_range": [0.15, 0.42],
      "distribution": "moderate"
    },
    "thermoclines": {
      "layer_count": 2,
      "layers": [...]
    },
    "profile": {
      "avg_color": "rgb(22,48,71)",
      "signal_strength": 0.18,
      "palette_dominance": "blue"
    }
  }
}
```

### 3.4 `logger.py` — Structured Daily Logging

```
┌──────────────┐     ┌──────────────────────────────┐
│ log_observ-  │────▶│ memory/observations/          │
│ ation(obs)   │     │   2026-07-15.jsonl            │
└──────────────┘     └──────────────────────────────┘
       │
       ▼
┌──────────────┐     ┌──────────────────────────────┐
│ summarize_   │────▶│ Today's summary:              │
│ day()        │     │ depth_range, bottom_types,    │
└──────────────┘     │ fish_detected_count           │
                     └──────────────────────────────┘
```

The observations directory is ZeroClaw's primary data source. Each file is JSONL (one JSON object per line), growing continuously throughout the day. Typical size: ~500 KB/day.

---

## 4. ZeroClaw Agent Loop

### 4.1 Core Loop

```
┌─────────────────────────────────────────────────────────────┐
│                    ZeroClaw Agent Loop                      │
│                  (runs every 30 seconds)                    │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 1. READ OBSERVATIONS                                │   │
│  │    • Check today's JSONL for new entries             │   │
│  │    • Read last N observations (default N=10)         │   │
│  │    • Compute deltas: depth change, position drift    │   │
│  └────────────────────┬────────────────────────────────┘   │
│                       │                                     │
│                       ▼                                     │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 2. UPDATE SPATIAL MEMORY                            │   │
│  │    • Append current position to track log            │   │
│  │    • Record depth-at-position in spatial index       │   │
│  │    • Compute track stats: heading, drift speed,      │   │
│  │      total distance, time since last turn             │   │
│  └────────────────────┬────────────────────────────────┘   │
│                       │                                     │
│                       ▼                                     │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 3. QUERY CONTOUR CACHE                              │   │
│  │    • Lookup depth contours at current lat/lon        │   │
│  │    • Compute ahead: what contours intersect our      │   │
│  │      projected track at current COG?                  │   │
│  │    • Cache results for future lookups                 │   │
│  └────────────────────┬────────────────────────────────┘   │
│                       │                                     │
│                       ▼                                     │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 4. DETECT PATTERNS                                  │   │
│  │    • Edge approaching? (depth change > threshold)     │   │
│  │    • On known ground? (match to historical spots)     │   │
│  │    • Fish pattern match? (compare to catch library)   │   │
│  │    • Drifting off? (SOG < 0.3kn for > 5min)          │   │
│  └────────────────────┬────────────────────────────────┘   │
│                       │                                     │
│                       ▼                                     │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 5. GENERATE ALERTS                                  │   │
│  │    • If pattern detected → write alerts.txt          │   │
│  │    • Severity: info / watch / warn / critical         │   │
│  │    • Example: "20fm edge 0.3nm ahead at 330°T"       │   │
│  └────────────────────┬────────────────────────────────┘   │
│                       │                                     │
│                       ▼                                     │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 6. CHECK FOR QUERIES                                │   │
│  │    • Read zeroclaw_in.txt for pending NL queries     │   │
│  │    • If found → process, write zeroclaw_out.txt      │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│   After loop: sleep until next sounder capture (~30s)       │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 Spatial-Temporal Memory

ZeroClaw maintains a rolling spatial memory that grows throughout the fishing trip and persists to disk:

```python
# Conceptual structure — not a file, but the in-memory model

spatial_memory = {
    "trip_start": "2026-07-15T06:00:00Z",
    "last_position": {"lat": 55.785, "lon": -131.527},
    "track": [
        {"ts": "...", "lat": ..., "lon": ..., "depth_fm": ..., "sog": ..., "cog": ...},
        # ... grows continuously during trip
    ],
    "passes": [
        {
            "start": {"lat": ..., "lon": ..., "ts": "..."},
            "end":   {"lat": ..., "lon": ..., "ts": "..."},
            "direction": 330,        # average COG
            "avg_depth": 45.2,       # fathoms
            "bottom_type": "hard",
            "fish_detected": True,
            "fish_density": "moderate",
            "contour_crossings": ["30fm", "48fm", "60fm"],
        },
        # ... one per directional pass
    ],
    "depth_samples": {
        # Keyed by grid cell (~0.001° resolution, same as contour cache)
        (55.785, -131.527): {"depth_fm": 22.5, "bottom_type": "hard", "ts": "..."},
        (55.786, -131.528): {"depth_fm": 25.1, "bottom_type": "hard", "ts": "..."},
        # ... one per 30s observation
    },
    "edge_crossings": [
        {"from_fm": 48, "to_fm": 22, "lat": ..., "lon": ..., "ts": "...", "direction": "shoreward"},
        # ... recorded when depth crosses a contour interval
    ],
    "drift_segments": [
        {"start_ts": "...", "end_ts": "...", "duration_min": 12, "max_drift_kn": 0.2},
        # ... drift periods (SOG < 0.3kn for > 5 min)
    ],
}
```

**Memory persistence:** Spatial memory is written to `tzpro-agent/memory/spatial/YYYY-MM-DD.json` at trip end and checkpointed every 10 minutes during operation.

**Query examples that spatial memory answers:**

| Query | Data Path | Answer |
|-------|-----------|--------|
| "Where were we at noon?" | `track[]` by timestamp | Lat/lon, depth, SOG at 12:00 |
| "How deep were we this morning?" | `depth_samples[]` time-range | Average/mode depth, 06:00-12:00 |
| "Did we fish this spot today?" | `track[]` proximity search | Yes/No + timestamps |
| "What direction were we dragging?" | `passes[]` by time-range | Average COG per pass |
| "How many edges did we cross?" | `edge_crossings[]` count | Integer count per time-range |

### 4.3 Contour Cache Queries

ZeroClaw queries the contour cache (see Section 5) for several standard lookups:

```python
# Standard contour cache queries

def query_at_position(lat, lon):
    """What contours exist at this position?"""
    # Returns: dict of depth_fm → {distance_m, bearing, crossing_type}
    return contour_cache.lookup(lat, lon)

def query_ahead(lat, lon, cog, distance_nm=1.0):
    """What contours will we cross in the next N nautical miles?"""
    projected = project_track(lat, lon, cog, distance_nm)
    return contour_cache.intersect(projected)

def query_nearby(lat, lon, radius_nm=0.5):
    """All contours within radius of position."""
    return contour_cache.radius_search(lat, lon, radius_nm)

def query_between_depth(lat, lon, min_fm, max_fm):
    """Are we between two contour depths?"""
    return contour_cache.depth_band(lat, lon, min_fm, max_fm)

def query_along_track(track_points, buffer_nm=0.1):
    """All contours crossed by a sequence of track points."""
    return contour_cache.track_profile(track_points, buffer_nm)
```

### 4.4 Alert Generation

Alerts are generated when patterns cross thresholds. Written to `alerts.txt` for Riker to read and relay.

```python
alert_config = {
    "edge_approaching": {
        "thresholds": {
            "depth_change_fm": 10,      # significant depth change
            "lookahead_nm": 1.0,         # look this far ahead
            "lookahead_min": 5,          # minutes ahead at current SOG
        },
        "severity": "watch",
        "format": "{depth_fm}fm {direction} edge {distance_nm}nm ahead at {bearing}°T",
    },
    "on_known_ground": {
        "thresholds": {
            "match_radius_nm": 0.1,     # how close to historical spot
            "min_match_confidence": 0.7,
        },
        "severity": "info",
        "format": "On {ground_name}: fished here {last_date}, {catch_summary}",
    },
    "pattern_match": {
        "thresholds": {
            "min_match_confidence": 0.75,
            "lookback_frames": 20,       # compare last 20 sounder frames
        },
        "severity": "info",
        "format": "{pct}% match to {catch_description} at {depth_fm}fm on {date}",
    },
    "drifting": {
        "thresholds": {
            "sog_max_kn": 0.3,
            "duration_min": 5,
        },
        "severity": "info",
        "format": "Drifting {duration_min}min at {sog}kn",
    },
    "depth_alarm": {
        "thresholds": {
            "min_depth_fm": 5,           # too shallow
            "max_depth_fm": None,         # optional max
        },
        "severity": "critical",
        "format": "DEPTH ALARM: {depth_fm}fm — shoaling!",
    },
}
```

**Alert lifecycle:**
1. ZeroClaw detects pattern → writes alert to `alerts.txt`
2. Riker reads `alerts.txt` on its own polling loop
3. Riker applies priority filtering (see Section 6.3)
4. Riker relays to Captain (or suppresses)
5. Alert is marked as "seen" by Riker
6. ZeroClaw clears stale alerts (older than 1 hour)

### 4.5 Natural Language Query Processing

When `zeroclaw_in.txt` contains a query, ZeroClaw processes it:

```
┌──────────────┐     ┌──────────────────┐     ┌──────────────┐
│ NL Query     │────▶│ Intent Parser    │────▶│ Data Lookup  │
│ "where's     │     │                  │     │              │
│  the edge?"  │     │ edge_location    │     │ query_ahead()│
└──────────────┘     └──────────────────┘     └──────┬───────┘
                                                     │
┌──────────────┐     ┌──────────────────┐            │
│ NL Response  │◄────│ Response Builder │◄───────────┘
│ "20fm ledge  │     │                  │
│  0.3nm ahead │     │ format + context │
│  at 330°T"   │     └──────────────────┘
└──────────────┘
```

**Intent map:**

| Query Pattern | Intent | Data Source | Response Example |
|---------------|--------|-------------|-----------------|
| "where's the edge" / "what's ahead" | `edge_location` | contour cache + track projection | "20fm edge 0.3nm ahead at 330°T. Depth goes from 48fm to 22fm over about 200 yards." |
| "what bottom" / "bottom type" / "what's under us" | `bottom_check` | latest observation | "Hard bottom at 45fm. Medium confidence. Moderate fish returns at 15-25fm." |
| "where were we at [time]" | `position_lookup` | spatial memory track | "At 10:32 we were at 55.785°N, -131.527°W, SOG 1.2kn, depth 42fm." |
| "did we fish here" / "were we here [date]" | `visit_check` | spatial memory + pass history | "Yes, we dragged this area on July 12 from 14:20 to 15:45. Average depth 44fm." |
| "show me [contour]" / "where's the [X]fm" | `contour_lookup` | contour cache | "The 48fm contour runs roughly east-west about 0.5nm north of us. Crosses our current track in about 12 minutes." |
| "how deep were we [time]" | `depth_history` | spatial memory depth_samples | "Between 08:00 and 10:00 we ranged from 35-52fm, mostly hard bottom." |
| "what did this look like [date]" | `historical_query` | contour cache + daily logs | "On July 10 at this position the sounder showed 48fm hard bottom with scattered fish returns." |

---

## 5. Contour Cache

### 5.1 Overview

The contour cache is a pre-computed spatial index of bathymetric contour lines extracted from NOAA survey data. It answers the question *"what depth contours exist at or near a given lat/lon?"* without touching the 10 GB raw XYZ file.

**Data source:** NOAA survey 71326 — Southeast Alaska, 237M sounding points, ~10 GB XYZ format.  
**Region:** 54°N–59°N, 130°W–138°W.  
**Grid resolution:** 0.001° (≈100m at these latitudes).  
**Contour intervals:** 5, 10, 20, 30, 48, 60, 80, 100, 150 fathoms.

### 5.2 Hot/Warm/Cold Hierarchy

The contour cache uses a three-tier storage strategy to balance speed, memory, and disk:

```
┌─────────────────────────────────────────────────────────────────┐
│                    CONTOUR CACHE HIERARCHY                      │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ HOT CACHE (in-memory, Python dict)                      │   │
│  │                                                         │   │
│  │  • Grid cells within ±0.5nm of current position         │   │
│  │  • All contour intervals for those cells                │   │
│  │  • Pre-loaded on position change > 0.1nm               │   │
│  │  • Size: ~100-200 cells × 9 intervals = ~50 KB         │   │
│  │  • Query time: < 1 µs (dict lookup)                    │   │
│  │  • Invalidated: on position change > hot_radius        │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                  │
│                              ▼ (cache miss)                     │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ WARM CACHE (memory-mapped numpy, ~160 MB)               │   │
│  │                                                         │   │
│  │  • Full elevation grid at 0.001° (5000 × 8000 float32)  │   │
│  │  • Memory-mapped from disk — only accessed pages in RAM │   │
│  │  • Stores min-elevation per grid cell                   │   │
│  │  • Query time: ~10-50 µs (numpy array access)           │   │
│  │  • Source: tzpro-agent/bathymetry/contours/             │   │
│  │             elevation_grid.npy                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                  │
│                              ▼ (grid cell lookup)               │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ COLD CACHE (on-disk GeoJSON, ~100 MB total)             │   │
│  │                                                         │   │
│  │  • One file per contour interval:                        │   │
│  │    contours_{5,10,20,30,48,60,80,100,150}fm.geojson     │   │
│  │  • Each file: FeatureCollection of LineString polylines  │   │
│  │  • Query: spatial index (R-tree) on file open            │   │
│  │  • Query time: ~1-10 ms (R-tree + polyline intersect)    │   │
│  │  • Source: generated by bathy_contours.py (marching      │   │
│  │    squares + polyline joining)                           │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 5.3 Vector Tile Format

The contour cache does NOT use actual vector tiles (MVT). Instead, it uses a simplified spatial lookup structure optimized for our specific query patterns (point lookup and line-segment intersection):

```python
# Contour cache file format per depth interval
# Stored as: contours_{depth_fm}fm_rtree.pkl

contour_rtree = {
    "metadata": {
        "depth_fm": 20,
        "depth_m": 36.576,
        "region": "54.0-59.0N, 130.0-138.0W",
        "grid_resolution_deg": 0.001,
        "polyline_count": 8423,
        "total_vertices": 1247561,
        "generated": "2026-07-15T12:00:00Z",
    },
    "rtree": RTreeIndex,           # spatial index of polyline bounding boxes
    "polylines": [
        # Each polyline is a list of (lon, lat) tuples
        [(-131.523, 55.785), (-131.524, 55.786), ...],
        [(-130.891, 56.123), (-130.892, 56.124), ...],
        # ... 8423 polylines for this depth
    ],
    "polyline_metadata": [
        {"id": 0, "length_km": 12.3, "bbox": [lon_min, lat_min, lon_max, lat_max]},
        {"id": 1, "length_km": 0.8,  "bbox": [...]},
        # ... one per polyline
    ],
}
```

**Why not MVT?** Mapbox Vector Tiles are optimized for map rendering at multiple zoom levels. Our queries are point-and-line intersections for navigation, not tile rendering. The R-tree + polyline approach is simpler, faster for our use case, and doesn't require a tile server.

### 5.4 On-Demand Query by Lat/Lon/Depth

```python
class ContourCache:
    """Spatial query interface for bathymetric contours."""
    
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.hot = {}           # {(i,j): {depth_fm: [polylines]}}
        self.warm_grid = None   # np.memmap of elevation grid
        self.rtrees = {}        # {depth_fm: rtree.Index}
        self.polylines = {}     # {depth_fm: [polylines]}
        self.hot_radius_cells = 5  # ±5 cells ≈ ±0.005° ≈ ±500m
    
    def lookup(self, lat: float, lon: float) -> dict:
        """Return all contours at or near a position.
        
        Returns: {
            "position": {"lat": lat, "lon": lon},
            "cell_elevation_m": -82.3,    # from warm cache grid
            "nearest_contours": {
                20: {"distance_m": 150, "bearing": 45, "closest_point": (lat, lon)},
                30: {"distance_m": 420, "bearing": 180, "closest_point": (lat, lon)},
            },
            "enclosing_band": (20, 30),   # position is between 20fm and 30fm contours
        }
        """
        i, j = latlon_to_ij(lat, lon)
        
        # 1. Check hot cache
        hot_key = (i, j)
        if hot_key in self.hot:
            return self._lookup_from_hot(lat, lon, hot_key)
        
        # 2. Warm cache: get cell elevation
        if self.warm_grid is not None:
            cell_elevation = self.warm_grid[i, j]
            depth_fm = abs(cell_elevation) / 1.8288  # meters to fathoms
            # Find enclosing contour band
            band = self._find_enclosing_band(depth_fm)
            
            # 3. Populate hot cache from cold
            self._load_hot_cache(i, j)
            
            # 4. Cold cache: spatial distance query
            return self._distance_query(lat, lon, band)
        
        return {"error": "no data at this position"}
    
    def intersect(self, track_line: list[tuple]) -> list:
        """Find all contour crossings along a projected track.
        
        Args:
            track_line: [(lat, lon), (lat, lon), ...] — projected track points
        
        Returns:
            [{depth_fm: int, crossing_point: (lat, lon), distance_along_nm: float,
              from_fm: int, to_fm: int}, ...]
        """
        crossings = []
        for depth_fm, rtree in self.rtrees.items():
            hits = rtree.intersection(track_bbox(track_line))
            for poly_idx in hits:
                intersection = line_intersect(track_line, self.polylines[depth_fm][poly_idx])
                if intersection:
                    crossings.append({
                        "depth_fm": depth_fm,
                        "crossing_point": intersection["point"],
                        "distance_along_nm": intersection["distance"],
                    })
        return sorted(crossings, key=lambda c: c["distance_along_nm"])
    
    def radius_search(self, lat: float, lon: float, radius_nm: float) -> dict:
        """All contour polylines within radius of position."""
        pass  # Use R-tree range query
    
    def depth_band(self, lat: float, lon: float, min_fm: int, max_fm: int) -> list:
        """Return contours between two depths at a position."""
        pass
    
    def track_profile(self, track_points: list, buffer_nm: float) -> list:
        """All contour crossings along an actual track."""
        pass
```

### 5.5 Cache Pre-warming Strategy

On ZeroClaw startup, the contour cache pre-warms based on current position:

```python
def prewarm_contour_cache(current_lat, current_lon):
    """Load contour data for the area around the boat's current position."""
    
    # 1. Load elevation grid (warm tier) — memory-mapped, no read cost yet
    grid_path = CACHE_DIR / "elevation_grid.npy"
    if grid_path.exists():
        contour_cache.warm_grid = np.load(grid_path, mmap_mode='r')
    
    # 2. Load R-trees for all depth intervals (cold tier) — on demand
    #    Only the index structures are loaded, not the polyline data
    
    # 3. Populate hot cache for current position
    i, j = latlon_to_ij(current_lat, current_lon)
    contour_cache._load_hot_cache(i, j)
    
    # 4. Pre-fetch ahead: load hot cache for projected track
    #    Based on current COG and SOG, load cells 1nm ahead
    ahead_i, ahead_j = project_position(current_lat, current_lon, cog, 1.0)
    contour_cache._load_hot_cache(ahead_i, ahead_j)
```

---

## 6. Filtered Mode — Riker Integration

### 6.1 Shared Directory Protocol

```
tzpro-agent/shared/zeroclaw/
├── observations.jsonl        # Last N observations (rolling)
├── position.json             # Current NMEA state
├── zeroclaw_in.txt           # NL queries from Captain (via Riker)
├── zeroclaw_out.txt          # Structured replies from ZeroClaw
├── alerts.txt                # Proactive alerts from ZeroClaw
├── contour_cache/            # Read-only, shared with tzpro-agent
│   ├── elevation_grid.npy
│   ├── contours_5fm_rtree.pkl
│   ├── contours_10fm_rtree.pkl
│   └── ...
├── state.json                # ZeroClaw operational state
└── .lock                     # File lock for concurrent access
```

### 6.2 File Formats

**`observations.jsonl` (tzpro-agent → ZeroClaw):**
```jsonl
{"ts":"2026-07-15T19:00:00Z","sounder":"frame_190000_sounder.png","position":{"lat":55.785,"lon":-131.527},"sounder_analysis":{"depth_fm":22.5,"bottom_type":"hard",...}}
{"ts":"2026-07-15T19:00:30Z","sounder":"frame_190030_sounder.png","position":{"lat":55.786,"lon":-131.528},"sounder_analysis":{"depth_fm":24.1,"bottom_type":"hard",...}}
```

**`position.json` (tzpro-agent → ZeroClaw):**
```json
{
  "ts": "2026-07-15T19:00:15Z",
  "lat": 55.7855,
  "lon": -131.5272,
  "sog": 1.4,
  "cog": 265.0,
  "depth_fm": 22.5,
  "water_temp_c": 8.2
}
```

**`zeroclaw_in.txt` (Riker → ZeroClaw):**
```
# Format: one line per query. Processed FIFO. Cleared after processing.
where's the edge ahead of us
what's the bottom looking like now
did we fish this spot on july 12
```

**`zeroclaw_out.txt` (ZeroClaw → Riker):**
```
# Format: <query_hash>|<response_json>\n
a1b2c3|{"query":"where's the edge ahead of us","response":"20fm edge 0.3nm ahead at 330°T. Depth goes from 48fm to 22fm over about 200 yards.","data":{"contour":"20fm","distance_nm":0.3,"bearing":330,"from_fm":48,"to_fm":22},"confidence":"high"}
d4e5f6|{"query":"what's the bottom looking like now","response":"Hard bottom at 45fm. Moderate fish returns at 15-25fm. No thermoclines visible.","data":{"depth_fm":45,"bottom_type":"hard","fish":{"distribution":"moderate","depth_range":[15,25]}},"confidence":"high"}
```

**`alerts.txt` (ZeroClaw → Riker):**
```
# Format: <timestamp>|<severity>|<alert_type>|<message>\n
2026-07-15T19:02:00Z|watch|edge_approaching|20fm edge 0.3nm ahead at 330°T
2026-07-15T19:05:00Z|info|on_known_ground|On Rock Pile: fished here July 12, 3 halibut 25-40lb
2026-07-15T19:08:00Z|warn|depth_alarm|Depth 8fm and shoaling — 5fm minimum approaching
```

### 6.3 Riker's Filtering Rules

Riker reads `alerts.txt` and applies filtering before presenting to the Captain:

```python
# Conceptual filtering rules — implemented in Riker's agent logic

filter_rules = {
    # Priority suppression
    "snooze": {
        "drifting": "suppress_if_recent(minutes=15)",  # Don't repeat drift alerts
    },
    
    # Severity escalation
    "escalate": {
        "depth_alarm": "always_relay",                   # Critical — never suppress
        "edge_approaching": "relay_unless_snoozed",      # Important but can be muted
        "on_known_ground": "relay_if_first_time(trip)",  # Once per ground per trip
        "pattern_match": "relay_if_confidence_above(0.80)",  # Only high-confidence
        "drifting": "relay_if_duration_above(minutes=10)",   # Only prolonged drifts
    },
    
    # Context awareness
    "context": {
        "time_of_day": "suppress_info_alerts_before(0600)_after(2200)",
        "fishing_active": "deprioritize_bottom_type_when_gear_down",
        "transit_mode": "prioritize_edge_alerts_when_sog_above(5)",
    },
    
    # Augmentation
    "augment": {
        "add_contour_context": True,       # Append nearest contours to every alert
        "add_time_since_last_alert": True, # "Last alert: 12 minutes ago"
        "add_suggested_action": True,      # "Suggested: hold course, edge in 0.3nm"
    },
}
```

**Riker's relay decision matrix:**

| Alert Type | Severity | Riker Action |
|------------|----------|-------------|
| `depth_alarm` (5fm shoaling) | critical | **Always relay immediately.** Push notification if Telegram. |
| `edge_approaching` (0.3nm) | watch | Relay with context ("edge in ~12 minutes at current speed"). |
| `edge_approaching` (2.0nm) | watch | Defer. Mention only if Captain asks. |
| `on_known_ground` | info | Relay once per trip per ground. Suppress repeats. |
| `pattern_match` (90%+) | info | Relay with suggested action. |
| `pattern_match` (75-89%) | info | Log silently to daily summary. Mention if asked. |
| `drifting` (< 5 min) | info | Suppress entirely. |
| `drifting` (> 10 min) | info | Relay once. "You've been drifting 12 minutes at 0.2kn." |

### 6.4 Communication Flow

```
Captain asks:                    Captain:
"Riker, what's                  "Riker, what's
the edge doing?"                the edge doing?"
     │                               ▲
     ▼                               │
┌─────────┐                    ┌─────────┐
│  Riker  │ ──────────────►   │  Riker  │
│ writes  │   zeroclaw_in.txt  │ reads   │
│ query   │                    │ reply   │
└─────────┘                    └─────────┘
     │                               ▲
     ▼                               │
┌──────────────┐              ┌──────────────┐
│  ZeroClaw    │              │  ZeroClaw    │
│ reads query  │──────────────│ writes reply │
│              │  zeroclaw_   │              │
│ processes    │  out.txt     │ formats      │
└──────────────┘              └──────────────┘
     │
     ├── query_ahead(contour_cache)
     ├── compute_distance(bearing)
     └── format_response()
```

**Latency budget (filtered mode):**

| Step | Time |
|------|------|
| Riker writes query to `zeroclaw_in.txt` | < 10 ms |
| ZeroClaw polls and detects query (30s loop or file watch) | 0–30s (polling) or < 100ms (file watch) |
| ZeroClaw processes query | < 500 ms |
| ZeroClaw writes to `zeroclaw_out.txt` | < 10 ms |
| Riker polls and detects reply | 0–5s (Riker's polling interval) |
| Riker formats and relays to Captain | < 500 ms |
| **Total** | **1–36s** (worst-case polling) or **1–3s** (file-watch) |

### 6.5 Locking and Concurrency

```
┌──────────────────────────────────────────────────────┐
│              File Lock Protocol                      │
│                                                      │
│  ┌─────────┐              ┌──────────────┐          │
│  │  Riker  │              │  ZeroClaw    │          │
│  └────┬────┘              └──────┬───────┘          │
│       │                          │                   │
│       │  acquire(.lock, write)   │                   │
│       │─────────────────────────►│                   │
│       │                          │                   │
│       │  write(zeroclaw_in.txt)  │                   │
│       │─────────────────────────►│                   │
│       │                          │                   │
│       │  release(.lock)          │                   │
│       │─────────────────────────►│                   │
│       │                          │                   │
│       │         ...              │                   │
│       │                          │                   │
│       │               acquire(.lock, write)          │
│       │◄─────────────────────────│                   │
│       │                          │                   │
│       │               write(zeroclaw_out.txt)        │
│       │◄─────────────────────────│                   │
│       │                          │                   │
│       │               release(.lock)                 │
│       │◄─────────────────────────│                   │
│       │                          │                   │
└──────────────────────────────────────────────────────┘
```

Lock implementation uses `portalocker` (cross-platform file locking on Windows):

```python
import portalocker

def safe_write(path: Path, content: str):
    """Write to a file with advisory locking."""
    with open(path, 'a' if path.suffix == '.jsonl' else 'w', encoding='utf-8') as f:
        portalocker.lock(f, portalocker.LOCK_EX)
        f.write(content)
        f.flush()
        portalocker.unlock(f)

def safe_read(path: Path) -> str:
    """Read a file with advisory locking."""
    if not path.exists():
        return ""
    with open(path, 'r', encoding='utf-8') as f:
        portalocker.lock(f, portalocker.LOCK_SH)
        content = f.read()
        portalocker.unlock(f)
    return content
```

---

## 7. Data Flow Diagrams

### 7.1 Full System — Filtered Mode

```
                              ┌───────────────────────────┐
                              │     TZ Pro Display        │
                              │     DISPLAY6 (1920×1080)  │
                              └─────────────┬─────────────┘
                                            │
                   ┌────────────────────────┼───────────────────────┐
                   │                        │                       │
                   ▼                        ▼                       │
           ┌──────────────┐        ┌──────────────┐        ┌──────────────┐
           │ screenshot   │        │ capture.py   │        │ hermitd      │
           │ .ps1         │        │ daemon loop  │        │ NMEA :8654   │
           │              │        │ 30s/4min     │        │ lat/lon/sog  │
           └──────┬───────┘        └──────┬───────┘        └──────┬───────┘
                  │                       │                       │
                  │         ┌─────────────┼───────────────────────┘
                  │         │             │
                  ▼         ▼             ▼
           ┌──────────────────────────────────────┐
           │         Sounder Analysis             │
           │  • sounder_analyzer.py (OpenCV)      │
           │  • vision.py (Florence-2 VL, future) │
           │  • Depth, bottom, fish, thermoclines │
           └────────────────┬─────────────────────┘
                            │
                            ▼
           ┌──────────────────────────────────────┐
           │         Structured Logging           │
           │  • logger.py                         │
           │  • memory/observations/YYYY-MM-DD.jsonl│
           │  • memory/daily/YYYY-MM-DD.md         │
           └────────────────┬─────────────────────┘
                            │
              ┌─────────────┼─────────────┐
              │             │             │
              ▼             ▼             ▼
    ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
    │ observations │ │ position.json│ │ contour_cache│
    │ .jsonl       │ │              │ │ /            │
    └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
           │                │                │
           │    ┌───────────┘                │
           │    │                            │
           ▼    ▼                            ▼
    ┌──────────────────────────────────────────────┐
    │           SHARED DIRECTORY                   │
    │    tzpro-agent/shared/zeroclaw/              │
    │                                              │
    │    ┌────────────────────────────────────┐    │
    │    │  observations.jsonl (rolling N)     │    │
    │    │  position.json                      │    │
    │    │  zeroclaw_in.txt                    │    │
    │    │  zeroclaw_out.txt                   │    │
    │    │  alerts.txt                         │    │
    │    │  state.json                         │    │
    │    └────────────────────────────────────┘    │
    └──────────┬───────────────────┬───────────────┘
               │                   │
               ▼                   ▼
    ┌──────────────────┐  ┌──────────────────┐
    │    ZeroClaw      │  │  Riker (OpenClaw)│
    │    Agent Loop    │  │  Main Agent      │
    │                  │  │                  │
    │  ┌────────────┐  │  │  ┌────────────┐  │
    │  │ read obs   │  │  │  │ read       │  │
    │  │ spatial mem│  │  │  │ zeroclaw_  │  │
    │  │ contour q  │  │  │  │ out.txt    │  │
    │  │ detect     │  │  │  │ alerts.txt │  │
    │  │ alerts     │  │  │  │            │  │
    │  │ answer NL  │  │  │  │ apply      │  │
    │  └────────────┘  │  │  │ filters    │  │
    │                  │  │  │            │  │
    │  writes → shared │  │  │ relay →    │  │
    │  reads  ← shared │  │  │ Captain    │  │
    └──────────────────┘  │  └────────────┘  │
                          └────────┬─────────┘
                                   │
                                   ▼
                          ┌──────────────────┐
                          │    Telegram /    │
                          │    Captain       │
                          └──────────────────┘
```

### 7.2 ZeroClaw Internal Data Flow

```
┌──────────────────────────────────────────────────────────────┐
│                    ZeroClaw Internals                        │
│                                                              │
│  ┌────────────┐    ┌────────────┐    ┌────────────┐         │
│  │ Input      │    │ Processing │    │ Output     │         │
│  │ Layer      │    │ Layer      │    │ Layer      │         │
│  └─────┬──────┘    └─────┬──────┘    └─────┬──────┘         │
│        │                 │                 │                 │
│  ┌─────▼──────┐    ┌─────▼──────┐    ┌─────▼──────┐         │
│  │Observations│    │Spatial     │    │zeroclaw_out│         │
│  │JSONL Reader│───►│Memory Mgr  │───►│.txt Writer │         │
│  └────────────┘    └─────┬──────┘    └────────────┘         │
│                          │                                   │
│  ┌────────────┐    ┌─────▼──────┐    ┌────────────┐         │
│  │Position    │    │Contour     │    │alerts.txt  │         │
│  │Reader      │───►│Query Engine│───►│Writer      │         │
│  └────────────┘    └─────┬──────┘    └────────────┘         │
│                          │                                   │
│  ┌────────────┐    ┌─────▼──────┐    ┌────────────┐         │
│  │zeroclaw_in │    │Pattern     │    │state.json  │         │
│  │Reader      │───►│Detector    │───►│Writer      │         │
│  └────────────┘    └─────┬──────┘    └────────────┘         │
│                          │                                   │
│                   ┌─────▼──────┐                             │
│                   │NL Query    │                             │
│                   │Processor   │                             │
│                   └────────────┘                             │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Contour Cache Access                    │   │
│  │  ┌──────────┐   ┌──────────┐   ┌──────────┐        │   │
│  │  │ Hot      │◄──│ Warm     │◄──│ Cold     │        │   │
│  │  │ Dict     │   │ np.mmap  │   │ GeoJSON  │        │   │
│  │  │ ~50 KB   │   │ ~160 MB  │   │ ~100 MB  │        │   │
│  │  │ in-RAM   │   │ mmap'd   │   │ on-disk  │        │   │
│  │  └──────────┘   └──────────┘   └──────────┘        │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

## 8. Operational States & Failure Modes

### 8.1 ZeroClaw State Machine

```
                    ┌─────────────┐
                    │  INIT       │
                    │  (startup)  │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │Pre-warm  │ │Load      │ │Validate  │
        │contour   │ │spatial   │ │shared    │
        │cache     │ │memory    │ │directory │
        └────┬─────┘ └────┬─────┘ └────┬─────┘
             │            │            │
             └────────────┼────────────┘
                          │
                          ▼
                    ┌─────────────┐
                    │  ACTIVE     │◄──────────────┐
                    │  (main loop)│               │
                    └──────┬──────┘               │
                           │                      │
              ┌────────────┼────────────┐         │
              │            │            │         │
              ▼            ▼            ▼         │
        ┌──────────┐ ┌──────────┐ ┌──────────┐   │
        │No new    │ │Query     │ │Alert     │   │
        │obs (30s) │ │pending   │ │triggered │   │
        └────┬─────┘ └────┬─────┘ └────┬─────┘   │
             │            │            │         │
             │            ▼            ▼         │
             │      ┌──────────┐ ┌──────────┐   │
             │      │Process   │ │Write     │   │
             │      │query     │ │alerts.txt│   │
             │      └────┬─────┘ └────┬─────┘   │
             │           │            │         │
             └───────────┼────────────┘         │
                         │                      │
                         └──────────────────────┘
```

### 8.2 Failure Modes and Recovery

| Failure | Detection | Recovery | Impact |
|---------|-----------|----------|--------|
| **Capture daemon down** | No new observations in `observations.jsonl` for > 2× cadence (60s) | ZeroClaw continues with last known position. Alerts machinery suspended. Spatial memory frozen. | Degraded: no new data, but queries on existing data still work |
| **NMEA bridge down** | `position.json` age > 30s | ZeroClaw uses last known position. Marks data as "stale." Alerts that require position (edge, drift) are suppressed. | Degraded: no position-dependent alerts |
| **Contour cache missing** | `elevation_grid.npy` or `contours_*fm_rtree.pkl` not found | ZeroClaw starts without contour awareness. Edge-detection alerts disabled. "Where's the edge" queries return "no contour data available." | Degraded: no spatial contour queries |
| **Shared directory full** | `write()` fails with disk error | Log error to `state.json`. Continue in-memory only. | Degraded: no alerts or replies written to disk |
| **Riker down** | No queries in `zeroclaw_in.txt` for > 30 min | ZeroClaw continues standalone loop. Alerts accumulate in `alerts.txt`. When Riker comes back, it reads the backlog. | Graceful degradation |
| **ZeroClaw crash** | Process exits | Spatial memory checkpointed every 10 min. On restart: reload from `memory/spatial/YYYY-MM-DD.json`, re-read `observations.jsonl`, resume loop. | ~10 min of spatial data loss |
| **GPU contention** | Not ZeroClaw's concern — Florence-2 is in the sensor pipeline | The sensor pipeline falls back to OpenCV. ZeroClaw doesn't know or care which analyzer ran. | None — ZeroClaw is GPU-independent |

### 8.3 Boot Sequence

```
1. Ensure shared directory exists:
   tzpro-agent/shared/zeroclaw/
   tzpro-agent/shared/zeroclaw/contour_cache/

2. Check sensor pipeline is running:
   - hermitd on :8654 (NMEA bridge)
   - capture.py daemon (30s/4min loop)

3. Load contour cache:
   - elevation_grid.npy (memory-mapped)
   - R-tree indices for all depth intervals
   - Pre-warm hot cache at current position

4. Load spatial memory:
   - memory/spatial/YYYY-MM-DD.json (today's trip)
   - If none, start fresh

5. Read recent observations:
   - Last N entries from today's JSONL
   - Seed spatial memory with existing track

6. Enter ACTIVE state:
   - Start 30-second loop
   - Begin polling shared directory
```

---

## 9. Implementation Roadmap

### Phase 1: Foundation (Week 1)

- [ ] Create shared directory structure at `tzpro-agent/shared/zeroclaw/`
- [ ] Implement `observations.jsonl` rolling writer (last 100 entries)
- [ ] Implement `position.json` writer (every 10s from NMEA)
- [ ] Implement file locking (`portalocker`) for all shared files
- [ ] ZeroClaw boot sequence with state machine
- [ ] Basic agent loop: read observations, track spatial memory

### Phase 2: Contour Cache (Week 2)

- [ ] Generate R-tree indices from existing GeoJSON contours
- [ ] Implement `ContourCache` class with hot/warm/cold tiers
- [ ] Implement `lookup()`, `intersect()`, `radius_search()`
- [ ] Implement cache pre-warming at startup
- [ ] Wire contour cache into ZeroClaw agent loop
- [ ] Test: query at known positions, verify against raw XYZ data

### Phase 3: Intelligence (Week 3)

- [ ] Implement pattern detection: edge approaching, on known ground, drifting
- [ ] Implement `alerts.txt` writer with severity levels
- [ ] Implement spatial memory persistence (10-min checkpoint)
- [ ] Implement NL query parser (intent matching)
- [ ] Implement response formatter
- [ ] Implement `zeroclaw_in.txt` / `zeroclaw_out.txt` protocol

### Phase 4: Riker Integration (Week 4)

- [ ] Riker reads `alerts.txt` on polling loop
- [ ] Implement filtering rules (severity, context, suppression)
- [ ] Implement query relay: Captain → `zeroclaw_in.txt` → ZeroClaw → `zeroclaw_out.txt` → Riker → Captain
- [ ] Implement alert lifecycle (seen, cleared, snoozed)
- [ ] Test end-to-end: Captain asks "where's the edge" → Riker routes → ZeroClaw answers → Riker relays

### Phase 5: Polish & Monitoring (Week 5+)

- [ ] Add `state.json` health monitoring
- [ ] Add file-watch mode (reduce polling latency from 30s to < 100ms)
- [ ] Add historical query support ("what did this look like on July 10?")
- [ ] Add catch correlation integration
- [ ] Add Florence-2 VL pipeline toggle
- [ ] Performance profiling: per-query latency budget

---

## Appendices

### A. Directory Layout (Complete)

```
tzpro-agent/
├── agent.py                    # On-demand interface
├── capture.py                  # Background capture daemon
├── sounder_analyzer.py         # OpenCV pixel analysis
├── vision.py                   # Florence-2 VL analysis
├── screenshot.py               # Screen capture utilities
├── screenshot.ps1              # PowerShell GDI capture
├── config.py                   # Shared constants
├── logger.py                   # Daily structured logging
├── deltalog.py                 # Chart delta logger
├── run_daemon.py               # Daemon launcher
├── bathy_contours.py           # Contour extraction (marching squares)
├── bathy_preprocess.py         # XYZ scan and index
├── zeroclaw/
│   ├── zeroclaw_agent.py       # ZeroClaw main agent
│   ├── contour_cache.py        # Hot/warm/cold contour cache
│   ├── spatial_memory.py       # Spatial-temporal memory
│   ├── pattern_detector.py     # Edge, ground, drift detection
│   ├── query_processor.py      # NL query intent parser
│   ├── alert_writer.py         # Alert generation and formatting
│   └── state.py                # State machine and health
├── shared/
│   └── zeroclaw/
│       ├── observations.jsonl  # Rolling observations
│       ├── position.json        # Live NMEA state
│       ├── zeroclaw_in.txt      # NL queries from Riker
│       ├── zeroclaw_out.txt     # Structured replies
│       ├── alerts.txt           # Proactive alerts
│       ├── state.json           # ZeroClaw operational state
│       ├── .lock                # File lock
│       └── contour_cache/       # Shared contour data (symlink/copy)
├── memory/
│   ├── observations/            # Daily JSONL logs
│   ├── daily/                   # Daily markdown summaries
│   ├── spatial/                 # Spatial memory checkpoints
│   └── chart_deltas/            # Chart delta logs
├── bathymetry/
│   ├── contours/                # Generated contour GeoJSON
│   ├── elevation_grid.npy       # 5000×8000 float32 grid
│   └── AK_ENCs_extracted/       # NOAA ENC data
├── captures/                    # Screen captures (rotating)
└── ARCHITECTURE_REVIEW.md       # Architectural review doc
```

### B. Key Dependencies

| Component | Dependency | Version | Purpose |
|-----------|-----------|---------|---------|
| Sensor Pipeline | Python 3.10+ | — | Runtime |
| Screen Capture | PowerShell 5.1+ | — | GDI+ screen capture |
| Image Analysis | Pillow | 10.x+ | Image loading and cropping |
| OCR | pytesseract + Tesseract | 5.x | Depth scale reading |
| VL Model | transformers + torch | latest | Florence-2 inference |
| Contour Cache | numpy | 1.24+ | Grid operations |
| Contour Cache | rtree | 1.x | Spatial indexing |
| File Locking | portalocker | 2.x | Cross-platform file locks |
| NMEA | hermitd | — | Position bridge |

### C. Glossary

| Term | Definition |
|------|-----------|
| **ZeroClaw** | Specialized spatial-temporal reasoning agent between sensor pipeline and Riker |
| **Riker** | OpenClaw main agent — Operations Officer, systems integrator |
| **Turbo-Shell** | Architecture pattern: narrow scope, perfect focus, invariant concept |
| **Contour Cache** | Hot/warm/cold hierarchy of pre-computed bathymetric contour data |
| **Sounder** | Fishfinder/echogram display on the TZ Pro — shows depth, bottom, fish returns |
| **NMEA** | National Marine Electronics Association — standard for marine sensor data |
| **SOG/COG** | Speed Over Ground / Course Over Ground — from GPS |
| **JSONL** | JSON Lines format — one JSON object per line, append-only |
| **Marching Squares** | Algorithm to extract contour lines from a raster grid |
| **R-tree** | Spatial index data structure for fast geometric queries |
| **Shared Directory** | File-based IPC between ZeroClaw and Riker |

---

*Part of the CoCapn ecosystem — CoCapn.com / ActiveLedger.ai / FishingLog.ai*  
*F/V EILEEN, Ketchikan Alaska, July 15, 2026*
