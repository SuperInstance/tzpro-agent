# TzPro-Agent Workshop Plan: Agentic Digital Twin

**Three one-afternoon sessions**
> *Decompose the "Agentic Digital Twin" into buildable pieces that strengthen the existing contour pipeline + anomaly logger, and connect directly to the Captain's fishing workflow.*

---

## Overview

| Session | Output | Builds On | RTX 4050 Role | Captain's Workflow |
|---------|--------|-----------|---------------|---------------------|
| **1** | Shadow Mode — real-time sounder vs contour comparison | contour GeoJSON + anomaly DB | Floor for live spatial queries | "Is this chart right?" |
| **2** | Catch Correlation — echogram signature matching | capture pipeline + observations JSONL | Pattern matching (numpy/scipy on GPU arrays) | "This looks like salmon — should I set gear?" |
| **3** | Anomaly Heatmap + Chart Correction Pipeline | anomaly DB + contour export | GPU-rendered heatmap tiles | "Where are the charts wrong, and by how much?" |

**Thread**: Each session produces a concrete, shippable thing. None requires more than 4 hours. All three nest into the Digital Twin feedback loop (measure → compare → correct → remeasure).

The RTX 4050 6GB is already running Ollama (qwen3:4b, ~3 GB VRAM). These sessions are designed to **use the remaining VRAM headroom** (~1.5–2.4 GB) or bypass GPU entirely for the first iteration.

---

## Session 1 — Shadow Mode: Live Contour Comparison

### What We Build

A real-time depth comparison daemon that:
1. On each 30-second capture, reads the NMEA position
2. Looks up the charted depth from the nearest contour at that lat/lon
3. Compares real sounder depth vs charted contour depth
4. Logs the delta to the anomaly database (contour_fm is currently always `None`)

**Concrete output**: A running log in `bathymetry/anomalies.db` with real `contour_fm` values. A live console that shows: `"55.785°N, -131.527°W | Sounder: 22.5 fm | Chart: 20 fm | Delta: +2.5 fm"`.

### How It Uses the RTX 4050 / Existing Data

**Existing data already available:**
- 9 contour GeoJSON files (5fm through 150fm) in `bathymetry/contours/`
- `elevation_grid.npy` — 160 MB float32 grid of the entire SE Alaska ROI
- Capture daemon running every 30 seconds with NMEA position
- Anomaly database (`anomalies.db`) — schema is ready, just needs the contour lookup

**RTX 4050 use (light):**
- Spatial queries use CPU (R-tree, nearest-neighbor on GeoJSON polylines) — sub-millisecond
- If we pre-bucket: load the elevation grid into a NumPy array on GPU for instant lat/lon → depth lookup
  - `gpu_grid = cp.array(np.load("elevation_grid.npy"))` — fits in < 500 MB GPU VRAM
  - Lat/lon → grid index → `gpu_grid[i, j]` returns charted elevation in 0.05 ms
  - This is the first time the **contour grid touches a GPU at all** — a bridge we'll need for the full Digital Twin

### How It Connects to the Captain's Workflow

Captain Casey fishes the same grounds day after day. NOAA surveys are infrequent; charts get stale. This session answers the most common question at the helm:

> *"Is the sounder showing the same depth the chart says should be here?"*

When the delta is large (e.g., chart says 20 fm but sounder reads 35 fm), the Captain:
- Knows not to trust the charted contour for gear placement
- Can annotate the correction directly ("this boulder field doesn't exist anymore")
- Builds institutional knowledge: "Tongass Narrows is 5 fm shallower than charted after the winter storms"

### Experiment That Proves It Works

**Test**: Run the daemon for 30 minutes while trolling a known area (e.g., Behm Canal around the NOAA survey lines).

**Pass Criteria**:
1. Every 30-second capture produces an anomaly row with non-null `contour_fm`
2. At least 5 distinct depth bands (e.g., 10fm, 20fm, 48fm) are crossed during the run
3. Delta values are numerically reasonable (within ±5 fm of sounder reading)
4. A known shoal or charted feature produces a consistent delta pattern across multiple passes

**Failure mode if it works**: Contour depth matches sounder within ±1 fm everywhere → the chart is accurate here. That's useful information too.

### Step-by-Step (1 Afternoon = 4 Hours)

| Time | Task | Code | Riskiest Bit |
|------|------|------|-------------|
| 0:00-0:30 | **R-tree contour index** — load all 9 GeoJSON files into an `rtree` spatial index. Each contour polyline indexed by its bounding box. | `from rtree import index; idx = index.Index()` | The 150fm contour is a huge polyline — may need simplification |
| 0:30-1:00 | **Nearest contour depth** — at a given lat/lon, query the R-tree for the nearest polyline, snap the depth from its depth_fm property. Fall back to bilinear interpolation on `elevation_grid.npy` if no contour within 1 km. | `nearest = list(idx.nearest((lon, lat, lon, lat), 1))` | Contour crossings near 0-fm/coastline can be ambiguous |
| 1:00-1:30 | **Inject into capture loop** — patch `capture.py` to call contour lookup after each sounder analysis and pass `contour_fm` to `anomaly_logger.log_anomaly()`. | Edit `_log_and_analyze()` in capture.py | Must not block the 30-second loop (>2s = skip) |
| 1:30-2:30 | **Console display** — `anomaly_logger.py --live` mode: tail the DB and print a one-line status update every capture. | `watch -n 30 python anomaly_logger.py --last` | PowerShell alternative: `Get-Content anomalies.db` won't work — need a SQL tail loop |
| 2:30-3:30 | **Test run** — deploy, run 30 min, collect results. | `python run_daemon.py` + `python show_deltas.py` | NMEA bridge must be up on :8654 |
| 3:30-4:00 | **Review anomalies vs ground truth** — overlay on QGIS, check deltas. | QGIS opens `qgis_corrections.csv` | |

### Files to Create

| File | Purpose |
|------|---------|
| `contour_lookup.py` | R-tree index builder + `depth_at(lat, lon) → (depth_fm, contour_id)` |
| `show_deltas.py` | Live console: `anomaly_logger.py --tail`, refreshes every capture |
| Patch: `capture.py` | 5-line change to pass `contour_fm` to anomaly logger |

---

## Session 2 — Catch Correlation: Echogram Signature Matching

### What We Build

A lightweight catch correlation engine that:
1. Lets the Captain (or Riker) log a catch event: species, time, depth range
2. Extracts a waveform "signature" from the 10-minute sounder window around each catch
3. Compares new echogram windows against known catch signatures
4. Emits a prediction: *"80% match with chinook signature — same bottom type, same depth layer profile as July 9 catch at this location"*

**Concrete output**: A working `predict_catch()` call that runs on every 30-second loop and logs predictions alongside observations. A simple CLI: `python catch_correlator.py --predict` shows the current match.

### How It Uses the RTX 4050 / Existing Data

**Existing data:**
- Observations JSONL files in `memory/observations/YYYY-MM-DD.jsonl` — depth, bottom type, fish returns every 30 seconds
- Sounder crops saved as PNGs in `captures/` — 370×900 images at 30s cadence
- NMEA position for every observation

**RTX 4050 role:**
- **Signature extraction** is numpy/scipy on CPU — ~15 ms per 10-frame window, no GPU needed
- **Batch signature comparison** — if we eventually have 100+ signatures, we can vectorize the comparison on GPU: `cp.array(sig_library) @ cp.array(live_sig)` for instant similarity across all known patterns
- **For this session**: Use CPU. GPU acceleration is a free upgrade when the library grows — the code path is identical with `cupy` import swap

### How It Connects to the Captain's Workflow

The Captain trolls for hours, watching the sounder for signs of fish. After a season, they know *what* a chinook school looks like, what a coho stack looks like, what a halibut on the bottom looks like. But that knowledge dies with the season.

This session answers:

> *"I caught a chinook at 11:30 AM last Tuesday at this spot. What did the sounder look like 10 minutes before? Does it look like that now?"*

Over time, the correlation engine becomes an **institutional memory** for fish detection patterns — the kind of knowledge that takes a deckhand years to build, now available on day 1 of every season.

### Experiment That Proves It Works

**Test**: Use 3 catch events from a single day's fishing. For each event:
1. Extract signature from 10-minute window *around* the catch
2. Extract signatures from 20 non-catch windows that day (random times)
3. Verify: catch-event signatures cluster together, non-catch signatures scatter

**Pass Criteria**:
1. Intra-catch similarity (same species, same day) > 0.7
2. Cross-catch similarity (different species, same day) < 0.5
3. Catch vs non-catch similarity < 0.3
4. At least one false alarm (no fish → predicts catch) to sanity-check the threshold

### Step-by-Step (1 Afternoon = 4 Hours)

| Time | Task | Code | Riskiest Bit |
|------|------|------|-------------|
| 0:00-0:45 | **Catch event data model** — SQLite table for catch events + quick CLI to log one: `python catch_correlator.py --log chinook "depth 18-22 fm" "55.78 -131.53"`. | `catch_correlator.py` with `create_db.py` | Timestamp alignment — NMEA timestamps and capture timestamps need to be in the same clock |
| 0:45-1:15 | **Signature extraction** — implement `extract_catch_signature()` from ARCHITECTURE_REVIEW.md §3.2. Reads 10 frames of sounder crop → returns feature vector (bottom intensity, fish arch rate, depth layer profile, temporal variance). | Function in `catch_correlator.py` | Sounder frames must be available — first verify captures directory has contiguous frames |
| 1:15-2:00 | **Signature library** — when a catch is logged, pull the 10-minute window around it, extract signature, store in SQLite. Build similarity search over all stored signatures. | `CatchSignatureLibrary` class with add + predict | Small dataset (<10 catches initially, need to bootstrap with synthetic positives) |
| 2:00-2:30 | **Hack the anomaly logger** — on each 30-second capture, extract the live signature from the last 10 frames, compare against library, log prediction alongside the anomaly row. | Add `catch_prediction` column to anomalies schema | Must not slow the 30-second loop — benchmark `predict_catch()` first |
| 2:30-3:00 | **Bootstrap with 5-10 simulated catch events** — use existing observations to create plausible catch scenarios. Or use yesterday's manual anchor/anomaly marks as proxies. | `catch_correlator.py --seed-db memory/observations/` | |
| 3:00-3:30 | **Test with live sounder** — run while the vessel is transiting. The correlation engine should report "no match" (since no fish). Then simulate a catch at the current time and watch the prediction flip. | `python catch_correlator.py --live` | |
| 3:30-4:00 | **Write up results** — similarity cluster plot + decision threshold analysis. | `matplotlib` scatter | |

### Files to Create

| File | Purpose |
|------|---------|
| `catch_correlator.py` | All-in-one: DB model, signature extraction, library management, prediction CLI |
| `bathymetry/catch_signatures.db` | SQLite database (created on first run) |

---

## Session 3 — Anomaly Heatmap + Chart Correction Pipeline

### What We Build

A visual heatmap of all recorded anomalies over time, plus an automated chart correction export pipeline.

**Concrete output**:
1. A lightweight web heatmap (Streamlit or FastAPI + Leaflet) showing anomaly density and magnitude overlayed on the chart
2. A script that generates corrected bathymetry patches: for any area with ≥ N anomalies exceeding ±1 fm, output a `correction_patch.geojson` that can be loaded into OpenCPN or TZ Pro as an overlay
3. A one-click QGIS export that generates the "true depth" heightmap from sounder-corrected data

### How It Uses the RTX 4050 / Existing Data

**Existing data:**
- `bathymetry/anomalies.db` — all logged anomalies (sound depth vs chart depth deltas)
- `bathymetry/contours/elevation_grid.npy` — the raw grid that needs patching
- `bathymetry/qgis_corrections.csv` — already exported points

**RTX 4050 role (GPU-rendered heatmap tiles):**
- For the Streamlit map, every render paints hundreds of anomaly points on a canvas
- Using CuPy for **inverse distance weighted (IDW) interpolation** of anomaly deltas across the grid:
  - `gpu_known = cp.array(anomaly_deltas)` — aligns with the 160 MB elevation grid already in GPU memory from Session 1
  - `gpu_grid_patch = cp.zeros_like(gpu_elevation_grid)`
  - Scatter the delta values, then run a GPU-accelerated IDW fill using CuPy's `scatter_add` and radial basis
  - Result: a full corrected grid where every cell with nearby anomalies gets a delta adjustment
- The entire 5000×8000 grid correction runs in ~2 seconds on GPU vs ~2 minutes on CPU
- This is the first time we **demonstrate the Digital Twin's core loop**: measure (sounder) → compare (contour) → correct (patch the grid)

### How It Connects to the Captain's Workflow

Every commercial fisherman has a mental map of "where the chart is wrong." This session externalizes that mental map:

> *"I've fished this reef for 10 years. I know the 48-fm line is actually at 52 fm in the southwest quadrant. But I can't show that to anyone else."*

Now:
- The anomaly heatmap **visualizes** every place the sounder disagreed with the chart
- The correction patches **fix the chart** for next time
- Over a season, the chart **gets more accurate** — the Digital Twin's core value proposition

### Experiment That Proves It Works

**Test**: Run the anomaly collection for a full day of fishing (6+ hours, ~720 captures). Then:

1. Export the anomaly heatmap as a web page
2. Visual inspection: does the heatmap correlate with known chart features? (shoals, channel edges, deep basins)
3. Pick a 2×2 nm area with ≥ 20 anomalies. Generate a correction patch.
4. Split the area: use 70% of anomalies to compute the correction, reserve 30% as validation
5. Measure: root mean squared error (RMSE) between corrected depth and reserved sounder readings

**Pass Criteria**:
1. Corrected grid RMSE < 5 fm on validation points
2. Heatmap shows at least 3 distinct anomaly clusters (high-density areas where chart is consistently wrong)
3. Correction patch loads successfully in QGIS or OpenCPN
4. Anomaly-free areas show zero correction (no false positives)

### Step-by-Step (1 Afternoon = 4 Hours)

| Time | Task | Code | Riskiest Bit |
|------|------|------|-------------|
| 0:00-0:30 | **Export aggregated anomalies** — `anomaly_logger.py --stats` now also produces a gridded delta map: group anomalies by 0.001° grid cell, compute median delta per cell. | Extend `anomaly_logger.py stats()` | Sparse data — need at least ~100 anomalies for meaningful gridding |
| 0:30-1:15 | **GPU anomaly heatmap** — CuPy scatter of anomaly deltas on the full elevation grid. Render as a `matplotlib` heatmap or export to GPU-computed PNG tile. | `heatmap_render.py` | CuPy's `scatter_add` on a 40M-cell grid — memory check: 40M × float32 = 160 MB, within budget |
| 1:15-2:00 | **Correction patch generation** — for each grid cell with ≥ 3 anomalies, compute the median delta. Write out a corrected elevation grid: `elevation_grid_corrected.npy`. Export correction patches as GeoJSON polygons with `charted_depth`, `corrected_depth`, `confidence`. | `grid_patcher.py` | The corrected grid needs to be differentiable from the original — don't overwrite |
| 2:00-2:30 | **Streamlit heatmap dashboard** — leaflet map + slider for time range + delta magnitude filter + export button. | `streamlit run anomaly_map.py` | |
| 2:30-3:15 | **Validation experiment** — compute RMSE on reserved anomalies, produce comparison plot. | `validate_correction.py` | |
| 3:15-4:00 | **OpenCPN overlay export** — patch GeoJSON in OpenCPN-compatible format: draw the corrected contour line in dashed red over the charted line. Captain can load as an overlay. | `export_opencpn_patch.py` | GeoJSON spec compliance for OpenCPN overlay |

### Files to Create

| File | Purpose |
|------|---------|
| `heatmap_render.py` | CuPy-based anomaly heatmap → PNG tiles |
| `grid_patcher.py` | Corrected elevation grid generation + GeoJSON patches |
| `anomaly_map.py` | Streamlit web dashboard with Leaflet map |
| `validate_correction.py` | RMSE + cross-validation on correction patches |
| `export_opencpn_patch.py` | OpenCPN-compatible contour overlay GeoJSON |

---

## How the Three Sessions Nest Into the Digital Twin

```
                  ┌─────────────────────────────────────┐
                  │      Full Agentic Digital Twin       │
                  │  (measure → compare → correct → RL) │
                  └─────────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│  Session 1    │   │  Session 2    │   │  Session 3    │
│  Shadow Mode  │──▶│  Catch Corr   │──▶│  Anomaly      │
│  (comparison) │   │  (correlation)│   │  Heatmap      │
│               │   │               │   │  (correction) │
│ Sounder vs    │   │ Catch sigs →  │   │ Anomalies     │
│ contour at    │   │ pattern lib → │   │ → corrected   │
│ every capture │   │ predict fish  │   │ grid → overlay│
└───────┬───────┘   └───────┬───────┘   └───────┬───────┘
        │                   │                   │
        └───────────────────┼───────────────────┘
                            │
                    ┌───────▼───────┐
                    │  Contour      │
                    │  Pipeline     │
                    │  (core model) │
                    │  elevation_   │
                    │  grid.npy     │
                    └───────┬───────┘
                            │
                    ┌───────▼───────┐
                    │  Anomaly DB   │
                    │  (ground      │
                    │   truth log)  │
                    └───────────────┘
```

**Data flows**:
- **Session 1** feeds the anomaly DB with real `contour_fm` values (closing the feedback loop)
- **Session 2** enriches anomalies with catch predictions (adding context)
- **Session 3** consumes both to produce corrected charts (closing the Digital Twin loop)

**RTX 4050 GPU VRAM budget across all three**:

| Session | GPU Component | VRAM | Notes |
|---------|--------------|------|-------|
| 1 | CuPy elevation grid lookup | ~500 MB | Coexists with Ollama (~3 GB), total ~3.5 GB → **2.5 GB headroom** ✅ |
| 2 | CuPy vectorized sig comparison | ~200 MB (only when library > 50 sigs) | CPU-only by default; GPU is optional optimization |
| 3 | CuPy IDW grid correction | ~500 MB (grid + anomaly scatter) | Run as batch job, not real-time — schedule when Ollama is idle |

No session exceeds the GPU budget, and all can run simultaneously with Ollama idling.

---

## Dependencies to Install

```bash
# Session 1
pip install rtree           # spatial indexing for contour lookup
# or: numpy bilinear interpolation on grid (zero-dependency fallback)

# Session 2
pip install scipy           # signal.find_peaks for fish arch detection

# Session 3
pip install streamlit       # heatmap dashboard
pip install leafmap         # leaflet integration in streamlit
pip install cupy-cuda12x    # GPU array operations (optional, not required for MVP)

# All sessions
pip install numpy           # already installed
```

## Quick-Start Path

Short on time? Do the **critical path** across sessions:

```
Day 1: Session 1 Steps 0:00-1:30 (contour lookup + capture loop injection)
         → Gets you real contour_fm in the anomaly DB

Day 2: Session 3 Steps 0:00-1:15 (anomaly heatmap on captured data)
         → Gets you the visual feedback loop

Day 3: Session 2 Steps 0:00-2:00 (catch signature library + prediction)
         → Gets you the correlation engine
```

This path produces a shippable artifact at the end of each half-day while building toward the full Digital Twin.

---

*Workshop plan for F/V EILEEN — Ketchikan, Alaska*
*CoCapn ecosystem — CoCapn.com / ActiveLedger.ai / FishingLog.ai*
