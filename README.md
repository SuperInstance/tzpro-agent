# tzpro-agent — First Sensor Node of the CoCapn Ecosystem

**Eyes on the TZ Pro display. Watches the sounder, reads the bottom, learns the grounds, compares every reading against the chart.**

![Status](https://img.shields.io/badge/status-founding--day-blue)
![Platform](https://img.shields.io/badge/platform-Windows%2011-lightgrey)
![GPU](https://img.shields.io/badge/GPU-RTX%204050-success)
![Repo](https://img.shields.io/badge/CoCapn-tzpro--agent-ff6b35)

Built and first-tested on **F/V EILEEN**, Ketchikan Alaska — July 15, 2026.
Part of the [CoCapn](https://CoCapn.com) ecosystem.

---

## Table of Contents

- [What This Is](#what-this-is)
- [The Hierarchy](#the-hierarchy)
- [The Founding Story](#the-founding-story)
- [Architecture Overview](#architecture-overview)
- [Pipeline Detail](#pipeline-detail)
  - [Phase 1: Capture](#phase-1-capture--analysis)
  - [Phase 2: Contour Extraction](#phase-2-bathymetric-contour-extraction)
  - [Phase 3: Anomaly Detection](#phase-3-anomaly-detection)
- [Contour Query Engine](#contour-query-engine)
- [The Fleet (Multi-Model Strategy)](#the-fleet-multi-model-strategy)
- [NMEA Infrastructure](#nmea-infrastructure)
- [Sounder Palette](#sounder-palette)
- [Files](#files)
- [Deployment Guide](#deployment-guide)
- [Quick Start](#quick-start)
- [Data Format](#data-format)
- [Phase Status](#phase-status)
- [Philosophical Anchors](#philosophical-anchors)
- [Long-term Vision](#long-term-vision)
- [Repositories](#repositories)

---

## What This Is

TZ Pro (TimeZero) is the primary navigation software on F/V EILEEN. It renders electronic charts, overlays bathymetry, displays AIS targets, and — most importantly — shows a real-time **sounder/fishfinder feed** from the vessel's transducer.

The TZ Pro display contains a lot of information. Most of it — lat, lon, SOG, COG, time — is already available as structured data from the NMEA 0183 bridge. **The one thing on that screen that can't be extracted any other way is the sounder.**

The sounder shows:
- **Bottom depth** — what's below the keel right now
- **Bottom hardness** — hard/medium/mud/silt from return intensity
- **Fish returns** — arches, density, depth range, distribution
- **Thermoclines** — temperature layers in the water column
- **Bottom shape** — transitions between bottom types

This agent captures the sounder panel every 30 seconds, analyzes it with OpenCV, pairs it with the vessel's NMEA position and speed, compares the reading against a high-resolution bathymetric contour layer, and logs every discrepancy.

**Why this matters:** Over a fishing season, the system accumulates a time-stamped, location-stamped record of every pass over your grounds. That record is the foundation for:
- Knowing where the bottom actually is (vs where the chart says it is)
- Correlating catch with bottom type, depth, and tidal stage
- Spotting changes between seasons — scoured bottoms, silted-in contours, new structure
- Answering "what did this spot look like last July?" with actual data, not memory

**The broader vision:** This is the first field sensor node of a platform that lets any fisherman wire their own boat with off-the-shelf hardware and open-source code. The culture is "wire it yourself, make it yours." The installer is just a human-agent-in-the-loop — pushing buttons the agent tells them to push, reading back numbers it asks for.

---

## The Hierarchy

```
Captain (Picard) — Casey DiGennaro
  Mission: produce product, stay safe, keep crew comfortable
  Sets the goals. Strategic. Runs the boat.

  └── Riker (Operations Officer) — the main agent
      Mission: maintain the machine, integrate new systems, keep vision
      Sees the whole system. Delegates to copilots.
      Spots when two copilots are fighting each other.
      Talks to the Captain as a colleague, not a tool.

      └── tzpro-agent (this repo) — Tactical Copilot
          Blinders-on. Watches the sounder. Nothing else.
          Doesn't know about the fuel tank, the autopilot, or the crew schedule.
          Doesn't need to.

      └── Future copilots (planned):
          ├── Autopilot Copilot — watches rudder/compass/course, learns to steer gentler
          ├── Engine Room Copilot — temps, fuel, RPM, vibration
          └── Catch Log Copilot — species, counts, position rigged
```

**Key distinction:** A copilot is a racehorse with blinders. It does one thing perfectly and never looks up. Riker is not a copilot. Riker is closer to the Captain than to the crew. Riker decides which copilots to deploy, connects new sensors, rewires the architecture, and sees the whole boat as a machine with cogs that need to mesh.

---

## The Founding Story

On July 15, 2026, at 07:16 AKDT, the Captain of F/V EILEEN sent two words to his AI agent: **"keep moving."** 

The NMEA bridge was down. Docker wasn't routing. The TZ Pro display was showing position from a dead fix. The previous night's session had left a trail of broken tools.

Over the next seven hours, the agent (codename: Riker) rebuilt the NMEA bridge in shared mode to fix an `INVALID_HANDLE` bug, fixed the Docker MCP gateway, proved out a sounder capture pipeline, extracted the first structured observation from the TZ Pro display at 10:59 AKDT, and — with the Captain — defined the architecture of a new kind of fishing intelligence platform.

The founding document (see `FISHINGLOG_FOUNDING.md` in the hermit-crab repo) records the full transcript. The philosophy is captured in seven writings by the Captain himself — "The Hundred Hooks," "The Person You Forgot Was There," "Charts Not Maps," "Ebb and Flow," "Cognitive Photosynthesis," and "The Reflection You Mistook for Depth."

This repo is the first artifact of that founding session. The sensor node that proved the pipeline works.

---

## Architecture Overview

```
                         ┌──────────────────────────────────────┐
                         │         NMEA 0183 (COM6)             │
                         │         u-blox GPS @ 4800 baud      │
                         └──────────────┬───────────────────────┘
                                        │
                         ┌──────────────▼───────────────────────┐
                         │         nmea_bridge.py                │
                         │  (shared-mode, FILE_SHARE_READ|WRITE) │
                         │  TCP :6006 (hermitd) + :6007 (TZ Pro)│
                         └────┬──────────────┬──────────────────┘
                              │              │
                     ┌────────▼───┐  ┌───────▼────────┐
                     │ hermitd    │  │ TZ Pro / Nobel │
                     │ :8654      │  │ :6007 input    │
                     │ dashboard  │  │ chart display  │
                     └─────┬──────┘  │ DISPLAY6       │
                           │         │ 1920×1080      │
                           │         └───────┬────────┘
                           │                 │
                           │     ┌───────────▼────────────┐
                           │     │    screenshot.ps1       │
                           │     │    PowerShell GDI+ cap  │
                           │     └───────────┬────────────┘
                           │                 │
                           │     ┌───────────▼────────────┐
                           │     │    capture.py           │
                           │     │    30s / 4min loop     │
                           │     │    crop + analyze + log│
                           │     └───────────┬────────────┘
                           │                 │
               ┌───────────┴─────────────────▼─────────────────────┐
               │                 _log_and_analyze()                 │
               │                                                    │
               │    ┌──────────────────┐    ┌──────────────────┐   │
               │    │ sounder_analyzer │    │  contour_query   │   │
               │    │ .py              │    │  .py             │   │
               │    │ OpenCV pixel     │    │  numpy grid      │   │
               │    │ analysis         │    │  0.001° res      │   │
               │    └────────┬─────────┘    └────────┬─────────┘   │
               │             │                       │             │
               │             ▼                       ▼             │
               │    ┌──────────────────┐    ┌──────────────────┐   │
               │    │ Real sounder     │    │ Charted depth    │   │
               │    │ depth (53.2 fm)  │    │ (67.3 fm)        │   │
               │    └────────┬─────────┘    └────────┬─────────┘   │
               │             │                       │             │
               │             ▼                       ▼             │
               │    ┌────────────────────────────────────────────┐ │
               │    │         anomaly_logger.py                   │ │
               │    │         SQLite: delta_fm = -14.1           │ │
               │    │         QGIS export → map correction       │ │
               │    └────────────────────────────────────────────┘ │
               └────────────────────────────────────────────────────┘
```

## Pipeline Detail

### Phase 1: Capture & Analysis

The capture daemon (`capture.py`) runs a dual-cadence loop:

| Mode | Interval | Output | Purpose |
|------|----------|--------|---------|
| **Sounder crop** (370×900) | 30 seconds | JSON analysis + anomaly log | Live bottom/fish reading |
| **Full frame** (1920×1080) | 4 minutes | Screenshot + analysis | Permanent filmstrip record |
| **On-demand** `--oneshot` | Captain asks | Full JSON to stdout | Answer questions |

The sounder analyzer (`sounder_analyzer.py`) processes the cropped panel:

1. **Palette detection** — identifies the blue→cyan→yellow→orange→red fishfinder palette
2. **Background subtraction** — filters dark blue noise (avg RGB ~107 total)
3. **Bottom detection** — finds the strongest horizontal return band, traces its contour
4. **Depth calibration** — reads the depth scale numbers via Tesseract OCR
5. **Fish return analysis** — counts pixels above threshold (180+ RGB total), computes density and depth range
6. **Bottom type classification** — return intensity and texture → hard/medium/soft/mud
7. **Thermocline detection** — horizontal bands of elevated return above the bottom

### Phase 2: Bathymetric Contour Extraction

The bathymetric preprocessing pipeline transforms raw survey data into agent-readable contours:

**Step 1 — File scan** (`bathy_preprocess.py`):
- Source: `71326.xyz` — 10.5 GB, 236,817,591 soundings, CSV format (long, lat, elevation)
- Coverage: from Lake Superior (-94.7, 47.4) to Southeast Alaska (-133.7, 56.3), with global coverage
- Grid: 0.1° cells for initial occupancy indexing
- Stats: 7,923 occupied grid cells, depth range -1,646m to +120m
- Key density bands (points within ±2.5m of target depth):
  - 5 fm: 2.8M points | 48 fm: 7.2M points | 150 fm: 541K points

**Step 2 — Grid building + contour extraction** (`bathy_contours.py`):
- Region of interest: 54-59°N, 130-138°W (Southeast Alaska)
- Grid: 5,000 × 8,000 cells at 0.001° (~100m), float32, 153 MB
- 125,627,033 points in ROI → 1,872,930 non-empty cells (4.7% fill)
- Marching squares algorithm extracts polylines at 9 depth intervals
- Grid cache: `bathymetry/contours/elevation_grid.npy` — checkpoint-resumable

**Output: 9 contour layers as GeoJSON FeatureCollections:**

| File | Depth | Polylines | Vertices | Size |
|------|-------|-----------|----------|------|
| `contours_5fm.geojson` | 5 fm (anchor safe) | 170 | 2,360 | 0.1 MB |
| `contours_10fm.geojson` | 10 fm | 404 | 7,077 | 0.3 MB |
| `contours_20fm.geojson` | 20 fm | 755 | 17,685 | 0.6 MB |
| `contours_30fm.geojson` | 30 fm | 1,151 | 28,319 | 1.0 MB |
| `contours_48fm.geojson` | **48 fm (gear drag)** | **1,081** | **32,440** | **1.1 MB** |
| `contours_60fm.geojson` | 60 fm | 979 | 29,900 | 1.0 MB |
| `contours_80fm.geojson` | 80 fm | — | — | 0.7 MB |
| `contours_100fm.geojson` | 100 fm | 472 | 14,164 | 0.5 MB |
| `contours_150fm.geojson` | 150 fm | 231 | 6,576 | 0.2 MB |

Total pipeline time: ~10 minutes (Phase 1: ~2,176s for 237M lines, Phase 2: ~597s for 9 depth intervals).

### Phase 3: Anomaly Detection

The anomaly logger (`anomaly_logger.py`) runs on every capture cycle:

1. **Capture** → sounder reads bottom depth at current lat/lon
2. **Query** → `contour_query.get_depth_fm(lat, lon)` returns charted depth from the numpy grid
3. **Compare** → delta = sounder_fm - contour_fm
4. **Log** → INSERT into SQLite `bathymetry_anomalies` table
5. **Export** → QGIS-ready CSV + GeoJSON for map correction

**Database schema:**

```sql
CREATE TABLE bathymetry_anomalies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    lat         REAL NOT NULL,
    lon         REAL NOT NULL,
    sog         REAL,
    sounder_fm  REAL NOT NULL,
    contour_fm  REAL,
    delta_fm    REAL,
    source      TEXT DEFAULT 'capture',
    cruise      TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);
```

**Sample anomaly (Ketchikan harbor, first test):**

```json
{
  "lat": 55.78595,
  "lon": -131.527017,
  "sounder_fm": 53.2,
  "contour_fm": 67.3,
  "delta_fm": -14.1,
  "source": "capture"
}
```

A -14.1 fm delta means the sounder reads 14 fathoms shallower than the chart says. This is the kind of discrepancy the system surfaces — either the depth scale calibration is off, or the bottom has changed since the survey. Over time, patterns in these deltas become bathymetric corrections.

---

## Contour Query Engine

The contour query module (`contour_query.py`) provides fast depth lookups from the numpy grid:

```python
from contour_query import get_depth_fm, get_gear_clearance

# Query any lat/lon within the ROI
depth = get_depth_fm(55.3422, -131.6433)        # 67.3 fm

# Get gear clearance relative to 48 fm contour
gear = get_gear_clearance(55.7859, -131.527)    # 19.3 fm clearance

# Find which contour bands cross near a position
bands = get_contour_bands(55.3422, -131.6433)
# → {10: ..., 20: ..., 30: ..., 48: ..., 60: ...}
```

The grid is cached in memory on first load (lazy initialization). Subsequent queries are O(1) — index into a numpy float32 array.

**Hardware:** The 153 MB float32 grid (5,000 × 8,000 cells at 0.001° resolution) stays memory-mapped when inactive and loads into RAM on first query. Lookup takes < 1 µs.

---

## The Fleet (Multi-Model Strategy)

This system doesn't use a single AI model. The Captain runs a **fleet**:

| Model | When to Use |
|-------|-------------|
| **Seed 2.0 Mini** | Creative brainstorming, wild ideas, flow state writing |
| **Hermes 3 405B** | Big thinking, synthesis, philosophy, long-form writing |
| **Nemotron 3 Ultra** | Heavy reasoning, reverse-actualization, engineering analysis |
| **DeepSeek V4 Pro** | Premium smarts, architecture, product design, production code |
| **DeepSeek V4 Flash** | Default — fast, capable, day-to-day operations |
| **Claude Sonnet** | Code, nuanced understanding, alternative perspective |
| **Kimi K2.5** | Code, reasoning, specialized decomposition |
| **qwen3:4b (local)** | Fast local inference on Ollama, no GPU needed |

**Captain's insight on model selection:** Maximum cognitive activation ≠ correctness. Hermes lights up 93% of its machinery and gets the wrong answer while Seed activates 5% and gets it right. Activation is metabolic rate, not signal. Route based on what the problem needs, not which model looks most impressive doing it.

---

## NMEA Infrastructure

The vessel's NMEA architecture is a carefully designed multi-consumer setup:

```
u-blox GPS (COM6 @ 4800 baud)
    │
    ▼
nmea_bridge.py (shared-mode COM6)
    │
    ├── TCP :6006  →  hermitd (dashboard, ActiveTrack)
    └── TCP :6007  →  TZ Pro (navigation position input)
```

**Critical design decisions:**
- **Shared mode** — the bridge opens COM6 with `FILE_SHARE_READ | FILE_SHARE_WRITE`. Without this, TZ Pro can't read the GPS (pyserial defaults to exclusive mode).
- **Dual-port broadcast** — the bridge serves both :6006 and :6007 from one COM6 read. This avoids virtual COM port drivers and lets any number of consumers connect.
- **INVALID_HANDLE bug fix** — `ctypes.c_void_p(-1).value` returns unsigned 64-bit MAX on Python 3.13. Fixed by setting `CreateFileA.restype = ctypes.c_void_p`. Both `nmea_bridge.py` and `hermitd.py` were affected.

---

## Sounder Palette

Confirmed by the Captain through comparison with the live display:

```
Background:  dark navy blue      rgb(13, 31, 54)    ~98 total RGB
Weak returns: soft mud, plankton 130-180 total RGB  (cyan)
Medium:      fish, thermoclines  180-250 total RGB  (yellow-green)
Strong:      hard bottom, dense  250+ total RGB     (orange-red)
             schools
```

The key insight: in a blue palette, the background IS blue. Fish and bottom returns are warmer-colored (green/yellow/orange). Pure brightness thresholding catches too much noise. The analyzer uses channel-ratio heuristics tuned specifically for this palette on this display.

Tesseract 5.4.0 is used for depth scale number OCR (AVX2/FMA/SSE4.1 support confirmed).

---

## Files

### Core Pipeline

| File | Purpose |
|------|---------|
| `capture.py` | Background daemon — dual-cadence capture loop (30s / 4min) |
| `sounder_analyzer.py` | OpenCV pixel analysis — palette, bottom, fish, thermoclines, depth |
| `screenshot.py` | Screen capture via PowerShell + PIL region crops |
| `screenshot.ps1` | PowerShell GDI+ script for DISPLAY6 capture |
| `config.py` | Shared constants — crop regions, thresholds, palette, paths |
| `logger.py` | Structured daily logging to JSONL + markdown summaries |
| `agent.py` | On-demand interface — Captain asks about the chart |

### Bathymetric Pipeline (Phases 2-3)

| File | Purpose |
|------|---------|
| `bathy_preprocess.py` | Scan + index 237M soundings, build occupancy grid |
| `bathy_contours.py` | Grid building + marching squares contour extraction |
| `contour_query.py` | Fast depth lookup by lat/lon from numpy grid |
| `anomaly_logger.py` | SQLite anomaly DB, QGIS/GeoJSON export, stats |

### Architecture Documents

| File | Purpose |
|------|---------|
| `v2_architecture.md` | Full v2 sensor pipeline architecture |
| `zeroclaw_architecture.md` | ZeroClaw agent integration design (61 KB, 9 sections) |
| `workshop_plan.md` | 3-session iterative build plan |
| `ARCHITECTURE_REVIEW.md` | Architecture review notes |
| `v2_architecture_nemotron.md` | Nemotron's engineering analysis |

---

## Deployment Guide

### Requirements

- **OS:** Windows 11 (tested on F/V EILEEN)
- **CPU:** Any x86-64 (tested on AMD Ryzen AI 9 HX 370)
- **GPU:** Optional — RTX 4050 6GB for Florence-2 inference (planned)
- **RAM:** 8 GB minimum, 32 GB recommended
- **Storage:** 500 MB for code + 160 MB for contour grid + growing observation log
- **Python:** 3.10+
- **Tesseract:** 5.x (for depth scale OCR)
- **NMEA:** COM port or TCP bridge providing lat/lon/SOG

### Setup

```powershell
# Clone
git clone https://github.com/SuperInstance/tzpro-agent.git
cd tzpro-agent

# Install Python dependencies
pip install pillow numpy

# Install Tesseract (if not present)
# Download from https://github.com/UB-Mannheim/tesseract/wiki

# Run the NMEA bridge (from hermit-crab repo)
python nmea-bridge/nmea_bridge.py --port COM6 --baud 4800

# Run a test capture
python capture.py --oneshot

# Build the contour grid (10 min, required for anomaly detection)
python bathy_contours.py

# Start the background daemon
python capture.py
```

---

## Quick Start

```bash
# One-shot capture + analysis + anomaly check
python capture.py --oneshot

# Look up charted depth at any position
python contour_query.py 55.3422 -131.6433
# → Ketchikan harbor: 67.3 fm

# Check anomaly database
python anomaly_logger.py --stats
# → Total: 2, avg magnitude: 7.31 fm

# Export all anomalies > 1 fm delta as QGIS-ready CSV
python anomaly_logger.py --export-csv --min-delta 1.0

# Export as GeoJSON for ZeroClaw
python anomaly_logger.py --export-geojson

# Run full contour extraction (10 min, one-time setup)
python bathy_contours.py

# Check charted depth vs gear depth at any position
python -c "from contour_query import get_gear_clearance; print(get_gear_clearance(55.7859, -131.527, 48))"
# → {'charted_fm': 67.3, 'gear_fm': 48.0, 'clearance_fm': 19.3, 'status': 'clear', ...}

# On-demand agent
python agent.py --brief

# Background daemon (Ctrl+C to stop)
python capture.py
```

---

## Data Format

### Observation Log (`memory/observations/YYYY-MM-DD.jsonl`)

```json
{
  "ts": "2026-07-15T18:59:40+00:00",
  "sounder": "tzpro_20260715_105941_sounder.png",
  "position": {"lat": 55.785, "lon": -131.527},
  "vessel": {"sog": 1.6, "cog": 265},
  "sounder_analysis": {
    "depth_fm": 53.2,
    "pixel_y": 599,
    "bottom_type": "soft_mud",
    "confidence": "low",
    "fish_returns": {
      "count": 3656,
      "density_per_100kpx": 1097.9,
      "avg_intensity": 133.2,
      "depth_range": [0.0, 0.63],
      "distribution": "very_dense"
    },
    "thermoclines": [],
    "signal_profile": {
      "avg_color": "rgb(13,34,54)",
      "signal_strength": 0.134,
      "palette_dominance": "blue"
    }
  }
}
```

### Anomaly Database (`bathymetry/anomalies.db`)

```sql
SELECT ts, lat, lon, sounder_fm, contour_fm, delta_fm, sog
FROM bathymetry_anomalies
WHERE abs(delta_fm) > 2.0
ORDER BY abs(delta_fm) DESC;
```

### QGIS Export (`bathymetry/qgis_corrections.csv`)

```csv
Longitude, Latitude, Depth
-131.527, 55.786, -97.3
```

### GeoJSON Export (`bathymetry/anomalies.geojson`)

```json
{
  "type": "FeatureCollection",
  "features": [{
    "type": "Feature",
    "geometry": {
      "type": "Point",
      "coordinates": [-131.527, 55.786]
    },
    "properties": {
      "delta_fm": -14.1,
      "ts": "2026-07-15T22:26:28+00:00",
      "sounder_fm": 53.2,
      "contour_fm": 67.3
    }
  }]
}
```

---

## Phase Status

| Phase | Description | Status | Date |
|-------|-------------|--------|------|
| **Phase 1** | Sounder capture + analysis pipeline | ✅ Complete | 2026-07-15 |
| **Phase 2** | Bathymetric contour extraction (9 layers) | ✅ Complete | 2026-07-15 |
| **Phase 3** | Anomaly logger — real vs charted depth | ✅ Complete | 2026-07-15 |
| **Phase 4** | ZeroClaw agent loop — alert engine + NL queries | 🔧 In design | — |
| **Phase 5** | Florence-2 VL model on sounder images (GPU) | 📋 Planned | — |
| **Phase 6** | DAW dashboard — web-based replay + query | 📋 Planned | — |
| **Phase 7** | Catch correlation — catches ↔ bottom type | 📋 Planned | — |

---

## Philosophical Anchors

This project is guided by seven writings from the Captain. They define what gets built and why:

1. **The Hundred Hooks** — Every hook is a measurement. The pattern across all hooks = the intelligence. The chart is not the song. The song is what happens when you pull the hooks.

2. **The Person You Forgot Was There** — The monitor engineer. The depth sounder that made itself unnecessary. The highest form of any tool: it disappears.

3. **Charts Not Maps** — A map is static. A chart is alive, updated by every pass. FishingLog.ai is a chart. It's never finished.

4. **Ebb and Flow** — Compute has tides. Don't fight them. Surf them. GPU contention is not a bug — it's the ebb and flow.

5. **Cognitive Photosynthesis** — The system is not a collection of parts but an orchestrated whole. Each model, each sensor, each pipeline contributes to a system that is more than the sum.

6. **The Reflection You Mistook for Depth** — Maximum cognitive activation ≠ correctness. Route to the right model for the job, not the one that looks most impressive doing it.

7. **Turbo Nemotron** — The invariant concept lives in the repo. The repo is permanent memory. Narrow scope, conservation budget, sandboxed not because weak — because focused.

**The invariants (things that must never change):**

1. **Open source.** Everything. Hardware guides, wiring templates, agent configs.
2. **Captain is customer zero.** Everything that works for him works for the fleet.
3. **The sounder is the only thing worth reading off the screen.** Lat/lon/SOG/COG come from NMEA.
4. **Copilots wear blinders.** One task, perfect focus. They don't know they're part of a larger system.
5. **The tool must disappear.** Every feature must pass the ignorability test.
6. **The repo is the seed.** Hardware changes. Models change. The repo persists.
7. **Don't fight the tide.** GPU contention is not a bug. Alternate. Fall back. Surf.
8. **Charts, not maps.** Alive, updated by every pass. Never finished.
9. **Keep pushing.** Perfect is the enemy of deployed.

---

## Long-term Vision

**The recursion:**
The next generation of this agent should be able to deploy itself onto any boat. Interview the captain. Figure out what hardware exists. Search the internet for what's missing. Write the wiring guide. Train the copilots. Improve season over season.

**The scale:**
50 boats in one bay. One industry. If it works for one fisherman, it works for all of them. From Ketchikan, you can build a career installing systems without leaving your dock. But that's not the goal. The goal is to build something that installs itself.

**The data:**
Every fishing day is a data contribution to next season. Every pattern spotted is a proof point. Every conversation with the Captain is a product design session. Over time, the system learns to read this water the way the Captain learned to read it — by watching, season after season, until the pattern is so familiar that the dashboard becomes invisible and the conversation between Captain and boat is direct, unmediated.

---

## Repositories

| Repo | URL | Branch | Contents |
|------|-----|--------|----------|
| **tzpro-agent** | [SuperInstance/tzpro-agent](https://github.com/SuperInstance/tzpro-agent) | master | This repo — first sensor node |
| **hermit-crab** | [SuperInstance/hermit-crab](https://github.com/SuperInstance/hermit-crab) | memory-system | NMEA bridge, dashboard, ActiveTrack, founding documents |

---

*Part of the CoCapn ecosystem — [CoCapn.com](https://CoCapn.com) / [ActiveLedger.ai](https://ActiveLedger.ai) / [FishingLog.ai](https://FishingLog.ai)*
*Riker, Operations Officer, F/V EILEEN, Ketchikan Alaska*
