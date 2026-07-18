# _AGENTS_GUIDE.md — tzpro-agent Collaboration Document

> **For:** AI agents (Hermes, Claude Code, Kimi, DeepSeek V4, Gemini, any future collaborator)  
> **Updated:** 2026-07-18 09:36 AKDT  
> **System:** TZ Pro echogram capture + analysis + vocabulary pipeline  

---

## 1. System Overview

**tzpro-agent** is a real-time fish finder analysis system that captures TZ Pro dual-band (LF/HF) echogram screenshots every 10 minutes, analyzes them with OpenCV, logs results to SQLite, maintains a Bayesian species vocabulary, and posts observations to a Ship Log Cloudflare Worker.

**Runtime:** EILEEN (Windows 11, Ketchikan, Alaska)  
**Captain:** Casey DiGennaro — chum trolling in Southeast Alaska (Clarence Strait area)  
**Tone:** Pilot house — concise, no filler, info-dense, maritime. Captain's decisions are final; everything else negotiable.

### Core Loop
```
capture_v3.py (10 min) → PNG + JSON + MD
     ↓
analyzer.py (60s scan) → OpenCV analysis → JSON update → Ship Log POST
     ↓
catch_link.py (on demand) → annotates captures with catch reports
     ↓
vocabulary.py → Bayesian species-at-depth predictions
     ↓
alerts.py (60s loop) → 5 rule types with dedup → Ship Log POST
```

### Design Principles (non-negotiable)
1. **Full-frame capture** — 14-min scrolling echogram is a time-series sensor
2. **Never overwrite** — schema_version increments, old analysis preserved
3. **Capture must never block on analysis** — separate processes
4. **No ML dependencies** — OpenCV + numpy only (ML comes later)
5. **Local SQLite is source of truth** — Cloud is replication target, not control plane
6. **Fire-and-forget ingest** — capture succeeds even if Cloudflare is down
7. **Bayesian vocabulary, not neural** — Laplace smoothing works with 1 report; neural needs 10,000

---

## 2. File Layout

```
tzpro-agent/
├── capture_v3.py          # Daemon: screenshots TZ Pro every 10min → PNG+JSON+MD
├── analyzer.py            # Daemon: reads new PNGs → OpenCV → captions → Ship Log
├── vocabulary.py          # Bayesian species prediction from catch report proximity
├── alerts.py              # Rule engine: 5 alert types with dedup + Ship Log posting
├── catch_link.py          # Links catch reports to nearest capture by time/distance
├── conservation_layer.py   # ActionBudget γ+H=C, SplitTrigger, SpectralLaplacian
├── fleet_monitor.py       # Service health checker (nmea_bridge, hermitd, capture, analyzer)
├── db.py                  # SQLite mirror: captures, catch_labels, blobs tables
├── config.py              # Paths, constants, zone definitions, palette thresholds
├── _router.py             # Agent task router with baton handshake locks
├── _tool_server.py        # Persistent JSON-RPC tool wrapper (survives MCP issues)
├── logger.py              # Shared logging infrastructure
├── anomaly_logger.py      # Anomaly event logging
├── deltalog.py            # Delta/cumulative logging for pipeline metrics
├── capture_tray.py        # System tray capture control
├── captures.db            # SQLite database (~30 captures, ~22K blobs)
├── captures/v3/           # Daily capture folders organized by position
│   └── YYYY-MM-DD_LAT/   # One folder per trip/day
│       ├── HHMM_LAT.json  # Capture metadata + full analysis (schema v2/v3)
│       ├── HHMM_LAT.png   # Raw 1920×1080 TZ Pro screenshot
│       └── HHMM_LAT.md    # Human-readable markdown log
├── tests/                 # Canary test suite
├── memory/                # Agent memory files
├── bathymetry/            # Bathymetric data & contour queries
├── _ARCH_*.md             # Architecture documents (agency, conservation, scaling, etc.)
├── _WORKING_THEORIES.md   # Captain's domain knowledge about chum trolling
├── _INTEGRATION_PLAN.md   # VIAME + Echopype integration research
├── _PIPELINE_TEST.md      # Pipeline audit (ship-ready score 4/10)
├── _HAZE_PATCH_BOUNDARY.md # Feed patch boundary analysis
├── ONBOARDING.md          # Successor briefing for new agents
├── VISION.md              # 6-week roadmap + fleet architecture
├── README.md              # Project readme
├── ARCHITECTURE_REVIEW.md # Detailed architecture review
├── workshop_plan.md       # Workshop/training plan
├── .vocabulary_cache.json # Cached vocabulary state
├── .alert_state.json      # Alert deduplication state
├── .conservation_state.json # Conservation budget state
├── .conservation_events.jsonl # Conservation event log
├── .capture_tray_pid      # PID file for tray daemon
└── .handshake/            # Router baton lock directory
```

---

## 3. Signal Tracking — What Each Module Detects

| Signal | Module | Band | What it means | Status |
|--------|--------|------|---------------|--------|
| Blob count | `analyzer.detect_blobs()` | LF + HF | Number of echo returns per frame (connected components) | ✅ Active |
| Bottom depth | `analyzer.detect_bottom()` | LF + HF | Seafloor depth in fathoms (additive scan from 30 fm down) | ✅ Active |
| Thermoclines | `analyzer.detect_thermoclines()` | LF | Thermal layer count + center depths (horizontal Sobel gradient) | ✅ Active |
| Boat proximity | `analyzer.detect_vertical_lines()` | LF | Other vessels' transducer interference (vertical line artifacts) | ✅ Active |
| Haze (feed/plankton) | `analyzer.detect_haze()` | HF | Fine scatterers in surface 0-5 fm — plankton/krill concentration | ✅ Active (v3) |
| Species prediction | `vocabulary.annotate_blobs()` | — | Bayesian species ID from catch-linked blobs (Laplace-smoothed) | ✅ Active |
| Zone profiles | `analyzer.compute_zone_profiles()` | LF + HF | Mean/peak intensity per depth zone (surface/upper/mid/lower/floor) | ✅ Active |
| Shape classification | `analyzer.detect_blobs()` | LF | Blob area, intensity, aspect ratio (future: solidity, circularity) | 🟡 Planned |
| Column delta | analyzer preprocessing | LF + HF | Left 5% vs right 5% intensity difference (temporal gradient proxy) | ✅ Active |
| Spectral gap | `conservation_layer.SpectralLaplacian` | — | Module dependency graph algebraic connectivity | ✅ Active |

### Depth Zones
| Zone | Depth (fm) | Pixel Rows | Target Signal |
|------|-----------|------------|---------------|
| Surface | 0-5 | 0-90 | Haze, plankton, surface clutter |
| Upper | 5-20 | 90-360 | Mixed returns, thermoclines |
| Mid | 20-40 | 360-720 | **Primary chum zone** — target species depth |
| Lower | 40-55 | 720-990 | Deep fish, structure |
| Floor | 55-60 | 990-1080 | Bottom detection, benthic |

### Display Constants
- **Monitor:** DISPLAY6 at X=1920, Y=0
- **Resolution:** 1920×1080
- **Depth range:** 0-60 fm → 18 px/fathom
- **LF band crop:** x=8..945
- **HF band crop:** x=950..1890
- **Sounder crop (for subframe):** x=1540..1910, y=100..1000
- **Palette:** Dark navy blue background → blue→cyan→yellow→orange→red signal

---

## 4. Analysis JSON Schema

Every capture produces a `.json` file with this structure:

```json
{
  "capture_id": "HHMM_DDMM.mmmN_DDDMM.mmmW",
  "ts_utc": "2026-07-17T20:40:05.033424+00:00",
  "ts_local": "2026-07-17T12:40:00-08:00",
  "display": {
    "offset_x": 1920,
    "width": 1920,
    "height": 1080,
    "depth_max_fm": 60
  },
  "position": {
    "lat_dd": 55.781,
    "lon_dd": -131.688,
    "lat_ddmm": "5546.864N",
    "lon_ddmm": "13141.209W",
    "sog_kts": 2.5,
    "cog_deg": 135.0
  },
  "analysis": {
    "schema_version": 3,
    "heuristic": {
      "lf": {
        "zone_profiles": {
          "surface": {"mean_intensity": 12.3, "peak_intensity": 45, "pixel_count": 90},
          "upper":   {"mean_intensity": 18.7, "peak_intensity": 120, "pixel_count": 270},
          "mid":     {"mean_intensity": 60.0, "peak_intensity": 255, "pixel_count": 360},
          "lower":   {"mean_intensity": 25.4, "peak_intensity": 180, "pixel_count": 270},
          "floor":   {"mean_intensity": 5.2, "peak_intensity": 30, "pixel_count": 90}
        },
        "blobs": [
          {
            "centroid_depth_fm": 35.2,
            "centroid_x_px": 450,
            "centroid_y_px": 630,
            "area_px": 120,
            "mean_intensity": 112.5,
            "prediction": {
              "species": "chum",
              "confidence": 0.95,
              "confidence_label": "chum"
            }
          }
        ],
        "thermoclines": [
          {"center_depth_fm": 17.6, "thickness_fm": 2.1}
        ],
        "bottom": {
          "bottom_depth_fm": 57.2,
          "confidence": "high"
        },
        "boat_proximity": {
          "vertical_line_count": 3,
          "severity": "few",
          "lines_per_zone": {"surface": 0, "upper": 1, "mid": 2},
          "max_vertical_span_fm": 25.0
        }
      },
      "hf": {
        "zone_profiles": {
          "surface": {"mean_intensity": 22.1, "peak_intensity": 80, "pixel_count": 90},
          "upper":   {"mean_intensity": 15.3, "peak_intensity": 60, "pixel_count": 270},
          "mid":     {"mean_intensity": 10.2, "peak_intensity": 45, "pixel_count": 360},
          "lower":   {"mean_intensity": 8.1, "peak_intensity": 35, "pixel_count": 270},
          "floor":   {"mean_intensity": 4.5, "peak_intensity": 20, "pixel_count": 90}
        },
        "blobs": [
          {
            "centroid_depth_fm": 3.5,
            "area_px": 4.2,
            "mean_intensity": 55.0
          }
        ],
        "haze": {
          "haze_blob_count": 65,
          "mean_haze_area": 4.1,
          "feed_present": true,
          "feed_intensity": "medium",
          "haze_zone": "surface"
        },
        "boat_proximity": {
          "vertical_line_count": 1,
          "severity": "few",
          "lines_per_zone": {}
        }
      }
    },
    "caption": "Bottom detected at 57.2 fm (high confidence). 7 thermal layers detected at 5.3 fm, 17.6 fm, 26.9 fm. 443 echo returns detected in the LF band across 5 zones (surface, upper, mid, lower, floor). Vocabulary predicts: chum. Mid-water column (20-40 fm) mean intensity 60.0/255, peak 255/255. Catch report: 15 chum at 35 fm.",
    "vocabulary": [
      {
        "species": "chum",
        "depth_fm": 35,
        "count": 15,
        "raw_text": "chum at 35 fm, 15 fish",
        "confidence": null,
        "linked_at_utc": "2026-07-17T22:49:14.124006+00:00"
      }
    ]
  }
}
```

### SQLite Schema (captures.db)

```sql
-- 3 tables, ~30 captures, ~22K blobs, 1 catch label

CREATE TABLE captures (
  capture_id TEXT PRIMARY KEY,        -- HHMM_DDMM.mmmN_DDDMM.mmmW
  ts_utc TEXT NOT NULL,
  ts_local TEXT,
  lat REAL,                           -- decimal degrees
  lon REAL,
  sog_kts REAL,                       -- speed over ground
  cog_deg REAL,                       -- course over ground
  depth_max_fm INTEGER DEFAULT 60,
  schema_version INTEGER DEFAULT 2,
  mid_zone_mean REAL,                 -- LF mid-zone mean intensity
  mid_zone_peak INTEGER,              -- LF mid-zone peak intensity
  blob_count INTEGER,
  thermocline_count INTEGER,
  bottom_depth_fm REAL,
  bottom_confidence TEXT,
  caption TEXT,
  day_folder TEXT,
  analyzed_at TEXT,
  file_size_bytes INTEGER
);

CREATE TABLE blobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  capture_id TEXT NOT NULL REFERENCES captures(capture_id),
  band TEXT NOT NULL CHECK(band IN ('lf', 'hf')),
  centroid_depth_fm REAL,
  centroid_x_px INTEGER,
  centroid_y_px INTEGER,
  width_px INTEGER,
  height_px INTEGER,
  area_px INTEGER,
  mean_intensity REAL,
  aspect_ratio REAL,
  predicted_species TEXT,
  prediction_confidence REAL
);

CREATE TABLE catch_labels (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  capture_id TEXT NOT NULL REFERENCES captures(capture_id),
  species TEXT NOT NULL,
  depth_fm INTEGER,
  count INTEGER,
  raw_text TEXT,
  confidence REAL,
  linked_at_utc TEXT,
  UNIQUE(capture_id, species, depth_fm)
);

-- Indexes on centroid_depth_fm, capture_id, species, position, and timestamp
```

---

## 5. Alert Rules

`alerts.py` runs five rule types, each yielding a standardized alert dict. Deduplication via `.alert_state.json` (SHA-256 hash of rule + trigger data). Alerts POST to Ship Log Search for semantic browsing.

| # | Rule | Trigger Condition | Severity | Config |
|---|------|-------------------|----------|--------|
| 1 | **VOCABULARY_MATCH** | ≥3 blobs with same species prediction at confidence ≥0.7 in a depth zone | `warning` | `VOCAB_CONFIDENCE_MIN=0.7`, `BLOB_CLUSTER_MIN=3` |
| 2 | **BOAT_PROXIMITY** | ≥5 vertical lines of sounder interference; ≥12 lines escalates to warning | `info` / `warning` | 5=info, 12=warning |
| 3 | **INTENSITY_SPIKE** | Mid-zone mean intensity > 2× the rolling average of previous 5 captures | `warning` | `INTENSITY_SPIKE_FACTOR=2.0`, `WINDOW=6` |
| 4 | **BOTTOM_CHANGE** | Bottom depth changes >5 fm between two consecutive captures | `info` | `BOTTOM_DELTA_FM=5.0` |
| 5 | **NO_ANALYSIS** | No new capture JSON written for >15 minutes (checks file mtime) | `critical` | `STALE_MINUTES=15` |

### Known Issues (from `_PIPELINE_TEST.md`)
- NO_ANALYSIS has spamming risk — alert_id includes age_minutes, so each cycle produces a new ID
- Ship Log POST has no retry queue (single attempt, 5s timeout)
- VOCAB_CONFIDENCE_MIN hardcoded at 0.7, not configurable

### CLI
```bash
python alerts.py --oneshot          # Check once
python alerts.py --daemon           # Loop every 60s
python alerts.py --daemon --dry-run # Same, no Ship Log POST
python alerts.py --acknowledge <id> # Mark as acknowledged (re-fire enabled)
python alerts.py --list-state       # Show dedup state
python alerts.py --clear-state      # Clear all
```

---

## 6. Data Sources

| Source | Transport | Content | Status |
|--------|-----------|---------|--------|
| TZ Pro display | pygetwindow + pyautogui (via `screenshot_v3.ps1`) | Full 1920×1080 PNG every 10 min on :00/:10 boundary | ✅ PID 33360 |
| NMEA GPS | COM6 (u-blox) → `nmea_bridge.py` → TCP :6006 | `$GPGGA`/`$GPRMC` sentences — lat, lon, SOG, COG | ✅ PID 3172 |
| Hermit Crab dashboard | TCP :8654 (hermitd) | Vessel status endpoint at `http://127.0.0.1:8654/vessel` | ✅ PID 9644 |
| Ship Log Search | `ship-log-search.casey-digennaro.workers.dev` | Cloudflare Worker — POST logs, GET timeline | ✅ Deployed |
| Docker MCP | :3100 | Agent tool server | ✅ |

### NMEA Position Format
- Source: u-blox GPS on COM6
- Bridge: `nmea_bridge.py` in `hermit-crab/` repo (separate directory)
- Protocol: Raw NMEA-0183 strings over TCP, parsed by `capture_v3.parse_nmea_latlon()`
- Known issue: No checksum validation — fragile on noisy serial

---

## 7. Working Theories (from `_WORKING_THEORIES.md`)

These are the Captain's domain hypotheses that drive analysis priorities. **All analysis improvements should be tested against these.**

| # | Theory | Evidence | Importance |
|---|--------|----------|------------|
| 1 | **Sounder interference = other boats' transducers** | Vertical line artifacts correlate with AIS/traffic; every line is a data point | **High** — drives `boat_proximity` alert |
| 2 | **HF haze = plankton/feed in surface layer** | Granular HF returns at 0-10 fm, small blob area (3-5 px²), increases when moving into new areas | **High** — drives `detect_haze()` |
| 3 | **LF solid blobs/boomerangs = actual chum targets** | Larger blob area, higher intensity, concentrated in mid-zone (20-40 fm) | **Critical** — vocabulary training target |
| 4 | **Fleet competition: boats steal each other's schools** | Chum following a boat's presentation may switch to nearby boats; correlates with proximity | **Medium** — needs multi-boat data |
| 5 | **Feed patches have spatial boundaries** | Haze dropped 92→37 in one 10-min interval at ~13141.864W (Captain confirmed with manual mark) | **Medium** — validated once |
| 6 | **Temporal context needed: single frames are meaningless** | Trends matter more than snapshots; need rolling window of 3-6 frames (30-60 min) | **Critical** — not yet implemented |
| 7 | **Presentation factors determine fish preference** | Speed (measurable), lure type, voltage, engine noise, chum slick — correlates with catch rates | **Low** — mostly unmeasured |

### Feed Patch Boundary (from `_HAZE_PATCH_BOUNDARY.md`)
- **Most likely boundary:** 0850→0900 at ~13141.864W (haze dropped 92→37, largest single-frame drop)
- **Captain confirmed** with manual mark on TZ Pro at that location
- **Feed present in 18/19 captures** — vessel is in a broadly productive area
- **Critical follow-up:** Did LF blob activity (chum) change after crossing the boundary?

---

## 8. Conservation Layer

`conservation_layer.py` enforces three structural invariants at the execution layer:

### Conservation Law: γ + H = C
Every intelligent system has a fixed information-processing capacity `C`. Useful cognitive work (γ) + entropy/action overhead (H) cannot exceed C.

### Scale Law: C = 1.283 − 0.159·log(V)
As vocabulary volume `V` grows, productive capacity decays logarithmically. When V > split threshold (1000), the system must forget (prune low-confidence entries) or spawn (fork a child agent with fresh V=0).

### Spectral Fingerprint
The graph Laplacian of the module dependency network encodes structural coherence. When the spectral gap (λ₂, Fiedler value) closes toward zero, the graph is about to disconnect — a structural crisis signal.

### CLI
```bash
python conservation_layer.py status    # Display budget state
python conservation_layer.py gc        # Run split/GC check (forget low-confidence entries)
```

---

## 9. Fleet Monitor

`fleet_monitor.py` checks four services and auto-restarts down ones:

| Service | Port | Process Name | Command |
|---------|------|--------------|---------|
| nmea_bridge | 6006 | nmea_bridge | `pythonw nmea-bridge\nmea_bridge.py --ports COM6 --num-ports 2` |
| hermitd | 8654 | hermitd | `pythonw hermitd.py` |
| capture_v3 | — | capture_v3 | `pythonw capture_v3.py` |
| analyzer | — | analyzer | `pythonw analyzer.py` |

```bash
python fleet_monitor.py status         # One-shot health check
python fleet_monitor.py report         # Markdown-format status table
python fleet_monitor.py daemon         # Monitor loop (60s, auto-restart)
python fleet_monitor.py restart <name> # Restart a specific service
```

---

## 10. How Agents Can Contribute

### 🔍 Read-Only Analysis (No Code Changes)
- **Read capture JSONs** and look for cross-signal correlations (haze vs blobs, proximity vs intensity)
- **Query SQLite** for temporal patterns: `sqlite3 captures.db "SELECT ..."`
- **Run vocabulary queries:** `python vocabulary.py lookup <depth_fm>`
- **Review blob statistics** per capture, per depth zone, per day
- **Cross-reference signals:** Does higher haze count correlate with fewer LF blobs? Does boat proximity predict intensity changes?
- **Check today's data snapshot** (see Quick Commands below)

### ✏️ Annotation & Labeling
- **Run `catch_link.py`** to link new catch reports to captures: `python catch_link.py link chum 35 15`
- **Parse natural language** from Captain: `python catch_link.py parse "caught 20 sockeye at 30 fm"`
- **Retroactively link** older catch reports to the nearest capture

### 🛠️ Code Improvements
- **Propose detection algorithm improvements** — new signals, better thresholds, multi-frame analysis
- **Implement temporal context** — read prior 3-6 captions before generating new ones (Working Theory #6)
- **Fix regression in Laplace smoothing** — single-species confidence inflates to 0.95 (P1 in `_PIPELINE_TEST.md`)
- **Add NMEA checksum validation** in `capture_v3.py`
- **Implement atomic file writes** — write to .tmp, then rename
- **Add Ship Log POST retry** with exponential backoff
- **Fix NO_ANALYSIS alert spamming** — stable alert_id
- **Improve blob shape classification** — aspect ratio, solidity, circularity

### 📊 Data Science
- **Analyze temporal trends** across an entire day's captures (see haze timeline in `_HAZE_PATCH_BOUNDARY.md`)
- **Find hotspots** — which grid cells have the most high-confidence chum blobs?
- **Correlate catch reports with signals** — what combination of haze, intensity, and depth best predicts catches?
- **Refine vocabulary** with new catch data — Bayesian accumulation compounds
- **Test working theories** against the data

### 🧪 Testing
- **Run canary tests:** `$env:PYTHONIOENCODING='utf-8'; python tests/run_canary.py`
- **Verify pipeline health:** `python fleet_monitor.py report`
- **Check vocabulary state:** `python vocabulary.py summarize`
- **Verify analyzer can process:** `python analyzer.py --oneshot`
- **Check alerts:** `python alerts.py --oneshot`

---

## 11. Quick Commands

```pwsh
# Fleet status (from tzpro-agent dir)
cd C:\Users\casey\.openclaw\workspace\tzpro-agent
python fleet_monitor.py report

# Conservation state
python conservation_layer.py status

# Vocabulary
python vocabulary.py summarize          # All known species per zone
python vocabulary.py lookup 35          # Predict species at 35 fm
python vocabulary.py rebuild            # Force rescan all captures

# Alerts
python alerts.py --oneshot              # Check all rules once
python alerts.py --list-state           # Show dedup state

# Catch linking
python catch_link.py link chum 35 15    # Link catch report to nearest capture
python catch_link.py parse "chum at 35 fm, 15 fish"

# Canary tests
$env:PYTHONIOENCODING='utf-8'; python tests/run_canary.py

# Check today's data (replace day folder with actual)
python -c "
from pathlib import Path; import json
d = Path('captures/v3')
# Find today's folder
for day_dir in sorted(d.iterdir(), reverse=True):
    if day_dir.is_dir():
        jsons = sorted(day_dir.glob('*.json'))
        for j in jsons[-3:]:
            meta = json.loads(j.read_text())
            cap = meta.get('analysis', {}).get('caption', '')[:80]
            blobs = len(meta.get('analysis', {}).get('heuristic', {}).get('lf', {}).get('blobs', []))
            print(f'{j.stem[:30]:30s} {blobs:4d} blobs | {cap}')
        break
"

# Query SQLite directly
python -c "
import sqlite3; conn = sqlite3.connect('captures.db')
cur = conn.execute('SELECT capture_id, bottom_depth_fm, blob_count, thermocline_count FROM captures ORDER BY ts_utc DESC LIMIT 5')
for row in cur: print(row)
"

# Chum hotspot query
python _chum_hotspots.py

# Tool server (alternative exec path when MCP transport is unreliable)
python _tool_server.py exec "dir captures\v3"
python _tool_server.py python "print(2+2)"
python _tool_server.py git "auto-update from agent"

# For DeepSeek V4 / OpenClaw agents specifically
# These resolve through the agent router:
#    creative_vision → seed2
#    synthesis       → hermes3
#    deduction       → nemotron
#    premium         → v4pro
#    review          → v4pro
#    system          → flash

# Git workflow
cd C:\Users\casey\.openclaw\workspace\tzpro-agent
git add -A
git commit -m "descriptive message"
git push
```

---

## 12. Known Issues & Priorities

From `_PIPELINE_TEST.md` — Ship-Ready Score: **4/10**

### P0 — Must Fix Before Unattended Deployment
| # | File | Issue | Fix |
|---|------|-------|-----|
| 1 | `alerts.py:137-174` | NO_ANALYSIS spams every 60s | Stable alert_id for stale check |
| 2 | `alerts.py:57-85` | Ship Log POST failures lost | Retry queue with persistence |
| 3 | `capture_v3.py:180-240` | Non-atomic JSON/MD writes | Write-temp-rename + file lock |
| 4 | `analyzer.py:216-218` | Bare except swallows vocab errors | Specific exception + log |
| 5 | `analyzer.py:275-300` | No retry on Ship Log POST | 3× exponential backoff |
| 6 | `analyzer.py:340-347` | Race reading partial JSON | File stability check / lock |

### P1 — Strongly Recommended
| # | File | Issue | Fix |
|---|------|-------|-----|
| 7 | `vocabulary.py:190-197` | Laplace inflates single-species confidence | Jeffreys prior (α=0.5) or +1 unknown |
| 8 | `vocabulary.py:42-45` | Hardcoded confidence thresholds | Configurable via config.py |
| 9 | `alerts.py:28` | Hardcoded VOCAB_CONFIDENCE_MIN=0.7 | Configurable |
| 10 | `analyzer.py:19-48` | Hardcoded display crop coords | Load from config / detect dynamically |
| 11 | `capture_v3.py:19-24` | Hardcoded monitor offset | Auto-detect or config |
| 12 | `capture_v3.py:55-70` | NMEA parsing lacks checksum | Validate `*XX` suffix |

---

## 13. Repository & Git

**Repository:** `https://github.com/SuperInstance/tzpro-agent.git`  
**Branch:** `master`  
**Related repo:** `https://github.com/SuperInstance/ship-log-search.git` (Cloudflare Worker frontend)

### Commit Principles
- **Atomic, descriptive commits** — one logical change per commit
- **Never force-push** `master`
- **Schema version bumps** are separate commits with comments
- **Run canary tests before pushing** code changes

---

## 14. Anti-Patterns (Don't Do These)

- ❌ **Don't add ML dependencies** — OpenCV + numpy is the contract until Phase 6
- ❌ **Don't overwrite existing analysis** — schema_version increments, old data is sacred
- ❌ **Don't restructure captures/v3/ directory** — analyzer, alerts, and vocabulary all depend on this layout
- ❌ **Don't hardcode new constants** — use `config.py`
- ❌ **Don't change display crop coordinates** without updating ALL modules that reference them
- ❌ **Don't add new capture formats** without backward compatibility
- ❌ **Don't modify `.vocabulary_cache.json` or `.alert_state.json` by hand** — use the CLI
- ❌ **Don't ship features that can't survive a power loss** — filesystem is the source of truth
- ❌ **Don't change the Captain's data** — captures, positions, and catch reports are his, not ours

---

*This guide was compiled from tzpro-agent source code, architecture documents, onboard notes, working theories, pipeline audits, and a full inventory of every file in the workspace as of 2026-07-18. It is maintained as the authoritative reference for all AI agents collaborating on this system.*
