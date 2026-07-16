# tzpro-agent — First Sensor Node of the CoCapn Ecosystem

**Eyes on the TZ Pro display. Watches the sounder, reads the bottom, learns the grounds, compares every reading against the chart.**

Built and first-tested on F/V EILEEN, Ketchikan Alaska, July 15, 2026.

---

## What This Is

The TZ Pro / Nobeltec navigation display shows a lot of information. Most of it — lat, lon, SOG, COG, time — is already available as structured data from the NMEA bridge. The one thing on that screen that can't be extracted any other way is **the sounder**.

This agent captures that feed, analyzes it, pairs it with NMEA position and speed, compares every reading against a high-resolution bathymetric contour layer built from 237 million survey soundings, and logs every anomaly where the real bottom doesn't match the chart.

Over a season, those anomalies become corrections to the base bathymetry. Every pass, every bottom transition, every fish contact — a high-resolution living chart of your grounds.

---

## Pipeline

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐     ┌──────────────────────┐
│  DISPLAY6   │────▶│  capture.py      │────▶│  sounder_       │────▶│  anomaly_logger.py   │
│  (TZ Pro)   │     │  30s / 4min     │     │  analyzer.py    │     │  real vs charted     │
│  1920×1080  │     │  background daemon│    │  (blue palette) │     │  → SQLite + QGIS CSV │
└─────────────┘     └────────┬─────────┘     └─────────────────┘     └──────────────────────┘
                             │
                             ▼
                      ┌─────────────────┐
                      │  contour_query   │
                      │  .py             │
                      │  300K depth/sec │
                      └─────────────────┘
                           │
                      ┌────┴────┐
                      ▼         ▼
            ┌──────────┐  ┌──────────┐
            │ NOAA ENC │  │ XYZ Bathy│
            │ AK chart │  │ 237M pts │
            │ S-57     │  │ survey   │
            └──────────┘  └──────────┘
```

**Bathymetric preprocessing:**

```
bathy_preprocess.py ──→ 237M XYZ points scanned, indexed, filtered to SE Alaska
bathy_contours.py    ──→ 0.001° grid → marching squares → 9 GeoJSON contour layers
                          (5, 10, 20, 30, 48, 60, 80, 100, 150 fm)
```

---

## Phase Status

| Phase | Description | Status |
|-------|-------------|--------|
| **Phase 1** | Index 237M bathymetry soundings, build spatial grid | ✅ Complete |
| **Phase 2** | Extract contour lines at 9 depth intervals | ✅ Complete |
| **Phase 3** | Anomaly logger — real vs charted depth comparison | ✅ Live |
| **Phase 4** | ZeroClaw agent loop — alert engine + NL queries | 🔧 In design |
| **Phase 5** | Florence-2 VL model on sounder images (RTX 4050) | 📋 Planned |

---

## Key Files

| File | Purpose |
|------|---------|
| `capture.py` | Background daemon — dual-cadence capture loop (30s / 4min) |
| `sounder_analyzer.py` | Vision analysis — bottom type, fish returns, thermoclines, depth scale OCR |
| `screenshot.py` | Screen capture via PowerShell + PIL region crops |
| `screenshot.ps1` | PowerShell script for DISPLAY6 capture |
| `agent.py` | On-demand interface — called by Riker when Captain asks about chart |
| `logger.py` | Structured daily logging to JSONL + markdown summaries |
| `config.py` | Shared constants — crop regions, thresholds, palette, paths |
| **`bathy_preprocess.py`** | Scan + index 237M bathymetry soundings |
| **`bathy_contours.py`** | Grid building + marching squares contour extraction |
| **`contour_query.py`** | Fast depth lookup by lat/lon from the grid |
| **`anomaly_logger.py`** | SQLite anomaly DB, QGIS export, stats |
| `vision.py` | Florence-2 based visual language model (planned) |
| `deltalog.py` | Chart delta logger — compare frames, log only changes |
| `run_daemon.py` | Single entry point for all background processes |
| `v2_architecture.md` | Full v2 architecture design document |
| `zeroclaw_architecture.md` | ZeroClaw integration architecture |
| `workshop_plan.md` | Workshop session plan for iterative development |

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

# Export all anomalies > 1 fm delta as QGIS-ready CSV
python anomaly_logger.py --export-csv --min-delta 1.0

# Export as GeoJSON for ZeroClaw
python anomaly_logger.py --export-geojson

# Run the full contour extraction pipeline (10 min)
python bathy_contours.py

# On-demand agent (for Captain's questions)
python agent.py

# Background daemon (Ctrl+C to stop)
python capture.py
```

---

## Data Format

Observations are logged as JSONL in `memory/observations/YYYY-MM-DD.jsonl`:

```json
{
  "ts": "2026-07-15T18:59:40+00:00",
  "position": {"lat": 55.785, "lon": -131.527},
  "vessel": {"sog": 1.6, "cog": 265},
  "sounder": {
    "depth_fm": 22.5,
    "bottom_type": "hard",
    "confidence": "high",
    "fish_returns": {
      "count": 45,
      "distribution": "moderate"
    }
  }
}
```

Anomalies are logged to `bathymetry/anomalies.db`:

```json
{
  "lat": 55.78595,
  "lon": -131.527017,
  "sounder_fm": 53.2,
  "contour_fm": 67.3,
  "delta_fm": -14.1,
  "sog": 1.6
}
```

---

## Bathymetry Contour Layers

Contour files are GeoJSON FeatureCollections of LineString polylines, stored in `bathymetry/contours/`:

| File | Depth | Polylines | Vertices |
|------|-------|-----------|----------|
| `contours_5fm.geojson` | 5 fm (anchor safe) | 170 | 2,360 |
| `contours_10fm.geojson` | 10 fm | 404 | 7,077 |
| `contours_20fm.geojson` | 20 fm | 755 | 17,685 |
| `contours_30fm.geojson` | 30 fm | 1,151 | 28,319 |
| **`contours_48fm.geojson`** | **48 fm (gear drag)** | **1,081** | **32,440** |
| `contours_60fm.geojson` | 60 fm | 979 | 29,900 |
| `contours_80fm.geojson` | 80 fm | — | — |
| `contours_100fm.geojson` | 100 fm | 472 | 14,164 |
| `contours_150fm.geojson` | 150 fm | 231 | 6,576 |

The elevation grid (`elevation_grid.npy`, 153 MB) covers 54-59°N, 130-138°W at 0.001° (~100m) resolution. Built from 125.6M survey soundings in the ROI.

---

## Dependencies

- Python 3.10+
- Pillow, numpy
- pytesseract + Tesseract 5.x system install
- PowerShell 5.1+ (Windows)
- NMEA bridge running on :6006 / :6007 (or hermit-crab)
- Hermit Crab dashboard on :8654

---

## Architecture

```
Captain (Picard) — mission: produce product, stay safe, keep crew comfortable
  └── Riker (Operations Officer) — maintain the machine, integrate, keep vision
       └── ZeroClaw tzpro-agent (Tactical Copilot)
            ├── Capture loop (30s / 4min)
            ├── Contour query engine
            ├── Anomaly logger
            └── Alert engine (planned)
```

See `zeroclaw_architecture.md` for the full integration design.

---

## Sounder Palette

Confirmed by Captain Casey DiGennaro:

**Dark blue background** → **cyan** → **yellow** → **orange** → **red** as returns intensify.

Measured background color average: `rgb(13, 31, 54)` — very dark navy blue.
The thresholds in `config.py` are tuned specifically for this palette on this display.

---

## Repositories

- **tzpro-agent** — this repo. The first field sensor node.
- **hermit-crab** — NMEA bridge, dashboard, ActiveTrack, outbox routing

---

## Long-term Vision

Day-by-day filmstrip of every pass, every bottom transition. Cross-season mark analysis. Pattern learning: drag speed vs bottom type vs catch rates. Bathymetric corrections that compound year over year.

Commercial fishing intelligence, born on one boat in Ketchikan, open-sourced for every fisherman who wants to build their own.

---

*Part of the CoCapn ecosystem — CoCapn.com / ActiveLedger.ai / FishingLog.ai*
*Riker, Operations Officer, F/V EILEEN*
