# Experiment: Virtual Forward-Looking Sonar

## Objective

Determine whether the contour query + forward look pipeline can reliably predict
depth changes **before** the vessel's sounder reaches those positions — i.e., does
the pre-gridded bathymetry serve as a viable "virtual forward-looking sonar"?

## Hypothesis

**H0 (null):** Predicted ahead depths have no significant correlation with
sounder readings when the vessel actually reaches the predicted positions.

**H1 (alternative):** The forward look pipeline predicts depth with accuracy
better than ±10 fm RMS error up to 1 nm ahead, providing actionable
navigation awareness.

---

## 1. System under Test

### Components

| Component | File | Role |
|---|---|---|
| Elevation grid (160 MB, float32) | `bathymetry/contours/elevation_grid.npy` | Precomputed min-elevation surface at 0.001° (~100 m) |
| Contour query | `contour_query.py` | `get_depth_fm(lat, lon)` — nearest-neighbor grid lookup, returns depth in fathoms |
| Forward look | `forward_look.py` | `predict_ahead(lat, lon, heading, sog)` — projects positions along a bearing using haversine, queries depth at each projected point |
| NMEA bridge | `http://127.0.0.1:8654/vessel` | Live position at 55.78595, -131.527017, SOG 1.6 kts |
| Sounder capture | `capture.py` + `sounder_analyzer.py` | Periodic sounder screenshot, OCR'd depth scale, bottom detection |
| Prediction log | `bathymetry/prediction_log.csv` (created on first log) | CSV accumulating predicted vs actual depth pairs |

### Known Limitations (pre-experiment)

1. **COG is null** — the NMEA bridge reports `"cog": null`. Heading must be
   supplied manually or derived from position deltas over time.
2. **SOG is 1.6 kts** (~0.82 m/s, ~82 cm/s). At this speed, reaching a point
   200 m ahead takes ~4 minutes. The experiment must wait for vessel movement.
3. **Grid resolution is 0.001°** — at 55.8° N, 1° longitude = ~62 km, so
   0.001° ≈ 62 m longitude, 111 m latitude. Features smaller than ~100 m may
   be aliased.
4. **Grid is min-elevation** — deeper points from overlapping survey lines
   dominate. The grid may show deeper water than the vessel actually
   experiences in complex terrain.

---

## 2. Experimental Design

### 2.1 Core Concept

At regular intervals (every 60 seconds), the experiment will:

1. **Read live position** from the NMEA bridge
2. **Project ahead** at 8 compass headings (0°, 45°, 90°, 135°, 180°, 225°, 270°, 315°)
   at the same set of distances
3. **Record predicted depths** for each heading × distance cell
4. **Train a heading estimator** from position deltas to compute actual vessel heading
5. **Log predictions** keyed by position + heading
6. **When the vessel reaches a previously-predicted position**, compare
   the actual sounder depth against the stored prediction
7. **Log the comparison** to `prediction_log.csv`

### 2.2 Compass Rose Parameters

**Projection distances** (matching `DEFAULT_DISTANCES_M` in `forward_look.py`):

| Distance (m) | Distance (nm) | Time to reach @ 1.6 kts | Grid cells traversed |
|---|---|---|---|
| 50 | 0.027 | ~1.6 min | ~0.5 |
| 100 | 0.054 | ~3.2 min | ~1 |
| 200 | 0.108 | ~6.5 min | ~2 |
| 300 | 0.162 | ~9.8 min | ~3 |
| 500 | 0.270 | ~16 min | ~5 |
| 750 | 0.405 | ~24 min | ~7.5 |
| 1000 | 0.540 | ~33 min | ~10 |
| 1500 | 0.810 | ~49 min | ~15 |
| 2000 | 1.080 | ~65 min | ~20 |

**Eight headings** (true bearings):

| Heading (°) | Cardinal | Notes |
|---|---|---|
| 0 | N | Along longitude line |
| 45 | NE | |
| 90 | E | Along latitude line |
| 135 | SE | |
| 180 | S | Along longitude line |
| 225 | SW | |
| 270 | W | Along latitude line |
| 315 | NW | |

### 2.3 Position Buffer and Look-Back

Maintain a **position history buffer** (last 300 positions, ~5 minutes at 1 Hz
or 300 points total). For each new position:

1. **Derive heading** from the last N seconds of position deltas (see §3.1)
2. **Compute forward look** along the derived heading
3. **Publish the prediction** to a spatial lookup table: for each (lat, lon) in
   the projected profile, store the predicted depth

When a new sounder capture arrives with (lat, lon):
1. **Look up** whether this position was previously predicted
2. If yes: compare `sounder_depth_fm` vs `predicted_depth_fm`
3. Log to `prediction_log.csv`

### 2.4 Data Collected per Experiment Cycle

Each cycle produces:

```json
{
  "cycle_ts": "2026-07-15T22:15:00Z",
  "vessel_position": { "lat": 55.78595, "lon": -131.527017 },
  "derived_heading": 142.3,
  "sounder_depth_fm": 68.2,
  "contour_depth_fm": 67.3,
  "delta_vs_contour": 0.9,
  "compass_rose": {
    "N":  { "50m": 68.1, "100m": 69.3, "200m": 70.2, ... },
    "NE": { "50m": 67.5, "100m": 66.8, "200m": 65.0, ... },
    ...
  }
}
```

Each cycle also triggers:
- Log to `prediction_log.csv` if this position matches a prior prediction
- Log to anomaly DB if `|delta_vs_contour| > 1.0 fm`

---

## 3. Methodology

### 3.1 Heading Estimation (since COG is null)

Derive heading from position deltas using a sliding window:

```
Given position history: [(lat_0, lon_0, t_0), ..., (lat_n, lon_n, t_n)]

1. Compute bearing from (lat_n-k, lon_n-k) → (lat_n, lon_n) using haversine
   where k = window_size (default: 5 positions, ~15-30 seconds apart)

2. Bearing formula:
   Δlon = lon_n - lon_n-k
   x = sin(Δlon) * cos(lat_n)
   y = cos(lat_n-k) * sin(lat_n) - sin(lat_n-k) * cos(lat_n) * cos(Δlon)
   heading = atan2(x, y)  [0-360°, 0 = North]

3. Smooth with a 3-sample median filter to reject outliers
```

**Implementation note:** The `forward_look.py` `predict_ahead()` function
accepts a `heading` parameter. Pass the derived heading. When position delta
is too small (< 0.0001° from last position), fall back to the previous heading.

### 3.2 Data Collection Protocol

#### Pre-requisites

- [ ] Daemon running (`python run_daemon.py` in background)
- [ ] NMEA bridge responding at `:8654/vessel`
- [ ] Screen capture working on the correct display
- [ ] Sounder analyzer calibrated (depth scale OCR working)

#### Collection steps (automated script)

1. **Create experiment directory:**

   ```bash
   mkdir -p tzpro-agent/experiment_data/forward_look_pilot
   ```

2. **Run experiment harness:**

   ```bash
   python tzpro-agent/experiment_forward_look_harness.py \
       --interval 60 \
       --headings 0,45,90,135,180,225,270,315 \
       --distances 50,100,200,300,500,750,1000,1500,2000 \
       --duration 3600 \
       --output tzpro-agent/experiment_data/forward_look_pilot
   ```

3. **Harness does the following every 60 s:**
   - Fetch position from NMEA bridge
   - Derive heading from position history
   - Sounder capture + analysis (using existing `capture_oneshot` logic)
   - For each of 8 headings, project ahead at all distances
   - Store result as a JSON line in `cycles.jsonl`
   - Check prediction_log.csv for any matches since last cycle
   - Log any matches found

4. **Manual override:** If the vessel is stationary at study start,
   artificially inject heading values to seed the prediction log,
   then let natural movement create matching opportunities.

#### Duration

Minimum **4 hours** of continuous collection during vessel transit.
At 1.6 kts, the vessel covers ~6.5 nm in 4 hours. The key metric is
**how many prediction→reality matches** we accumulate, not elapsed time.

Target: **≥ 50 matched prediction/reality pairs** for statistical significance.

### 3.3 Success Metrics

| Metric | Target | How to measure |
|---|---|---|
| **RMS prediction error** at 200 m | ≤ 10 fm | `sqrt(mean((predicted - actual)²))` for all 200-m matches |
| **RMS prediction error** at 1,000 m | ≤ 20 fm | Same for 1,000-m matches |
| **Mean error** (bias) at all distances | \|bias\| ≤ 5 fm | `mean(predicted - actual)` — systematic bias indicates grid offset |
| **Directional consistency** | ≥ 70% correct direction | `sign(predicted_trend) == sign(actual_trend)` — did depth get shallower/deeper correctly? |
| **Contour crossing prediction** | ≥ 80% early warning rate | Did we predict a 48-fm crossing before it happened? |
| **Alert lead time** | ≥ 5 min average | For each alert triggered, how far ahead was it predicted? |
| **Coverage** | ≥ 50 matched pairs | Total prediction→reality comparisons collected |

### 3.4 Grid Position Confirmation

Before interpreting forward-look errors as "pipeline failure," confirm the
grid position is valid:

```python
from contour_query import get_depth_fm, in_roi

assert in_roi(lat, lon), "Position outside charted region"
depth = get_depth_fm(lat, lon)
assert depth is not None, "No grid data at position"
assert 1 < depth < 500, f"Unreasonable depth: {depth} fm"
```

This sanity-check is run on every cycle and logged.

---

## 4. Analysis Approach

### 4.1 Phase 1: Raw Error Analysis (after data collection)

Compute for each distance bucket:

```python
import numpy as np

matches = load_prediction_log()
for dist_m in [50, 100, 200, 300, 500, 750, 1000]:
    bucket = [m for m in matches if m.distance_m == dist_m]
    errors = [m.actual_fm - m.predicted_fm for m in bucket]
    
    rms = np.sqrt(np.mean(np.array(errors)**2))
    bias = np.mean(errors)
    std = np.std(errors)
    
    print(f"{dist_m:5d}m: n={len(bucket):3d}  "
          f"RMS={rms:.1f}  bias={bias:+.1f}±{std:.1f} fm")
```

Plot error vs distance to check divergence (prediction should degrade
with distance — how fast?).

### 4.2 Phase 2: Directional Accuracy

For each pair, compute:

- **Predicted gradient:** `Δdepth_pred = predicted_deep - predicted_shallow`
  across the same track segment
- **Actual gradient:** `Δdepth_actual` from the sounder
- **Direction match:** `True` if both gradients have the same sign

This tells us: even if absolute depth is wrong, do we at least predict
*shallowing* vs *deepening* correctly? That alone is navigationally useful.

### 4.3 Phase 3: Error Attribution

If bias is present, decompose into:

1. **Grid interpolation error** — compare grid value at a position vs
   the known contour polylines at that exact spot. Could the min-elevation
   gridding have picked a deeper point from an overlapping survey?
2. **Projection error** — haversine projection accuracy at 1,000 m is
   < 0.1 m, so this is negligible.
3. **Heading estimation error** — If COG is noisy or lags, predicted
   positions will be wrong. This is the most likely source of error.
4. **Sounder measurement error** — The sounder pixel→depth calibration
   (OCR + proportional) is ±5-10 fm. This contributes noise.

### 4.4 Phase 4: Alert Performance

Simulate the alert pipeline on logged data:

- For each cycle, check if an alert *would have* been generated
  (gear-crossing / shoaling warnings)
- Compare against the actual sounder data to see if alerts were:
  - **True positive:** Correctly predicted real contour crossing
  - **False positive:** Predicted crossing that never materialized
  - **False negative:** Contour crossing happened but wasn't predicted
  - **True negative:** No crossing, no alert

Calculate:

```
Precision = TP / (TP + FP)
Recall    = TP / (TP + FN)
Lead time = time_between_alert_and_crossing
```

Target: Precision > 0.7, Recall > 0.8, Mean lead time > 5 min.

---

## 5. Implementation Plan

### 5.1 Experiment Harness Script

Create `experiment_forward_look_harness.py` — a new script that:

1. Reads position from NMEA bridge on configurable interval
2. Maintains a `PositionHistory` class (rolling window of (lat, lon, ts))
3. Derives heading from position deltas
4. Calls `predict_ahead()` from `forward_look.py` at 8 headings
5. Calls `capture_sounder()` + `analyze_sounder()` from existing modules
6. Logs everything to:
   - `cycles.jsonl` — per-cycle dump of all data
   - `prediction_log.csv` — prediction→reality matches
   - `bathymetry_anomalies` DB — anomaly logger integration
7. Includes a `--replay` mode to run against an existing track log
   (so the experiment can be simulated with historical data)

### 5.2 Position History Class

```python
class PositionHistory:
    """Rolling window of recent positions for heading derivation."""
    
    def __init__(self, max_age_s=120):
        self.positions = []  # [(lat, lon, ts)]
        self.max_age_s = max_age_s
    
    def add(self, lat, lon, ts=None):
        self.positions.append((lat, lon, ts or time.time()))
        self._prune()
    
    def _prune(self):
        cutoff = time.time() - self.max_age_s
        self.positions = [p for p in self.positions if p[2] >= cutoff]
    
    def derive_heading(self, window=5) -> Optional[float]:
        """Derive bearing from the latest `window` positions."""
        if len(self.positions) < window + 1:
            return None
        # Use positions[-window:] to compute delta
        p0 = self.positions[-window]
        p1 = self.positions[-1]
        return haversine_bearing(p0[0], p0[1], p1[0], p1[1])
```

### 5.3 Stale Prediction Cleanup

Predictions older than 60 minutes should be evicted from the match buffer
to prevent stale comparisons. The prediction log stores a timestamp so
we can filter.

### 5.4 Manual Heading Override

Since COG is null, include a CLI flag `--heading DEG` to manually supply
heading for the first cycle. The harness will then track subsequent heading
changes from position deltas relative to the seeded direction.

---

## 6. Risk Assessment

| Risk | Impact | Mitigation |
|---|---|---|
| Vessel moves < prediction distance | Few matched pairs | Extend collection time; use shorter distances (50-200 m) |
| Heading estimation is noisy | Predicted positions are wrong | Use wider smoothing window; log heading confidence |
| Grid has systematic bias | All predictions are off | Compute bias from first 10 matches and report separately |
| Sounder OCR fails | No actual depth to compare | Fall back to proportional pixel→depth estimate |
| Vessel doesn't transit during experiment | Zero matches | Replay mode using historical track data as simulation |
| Weather/current causes heading != course-made-good | Predicted and actual diverge | Log COG vs heading discrepancy when both are available |

---

## 7. Deliverables

After completing the experiment, produce:

1. **`experiment_forward_look_report.md`** — structured report with:
   - Data collection summary (hours, cycles, matched pairs)
   - Error analysis by distance (table + plots)
   - Directional accuracy results
   - Alert performance (precision, recall, lead time)
   - Error attribution breakdown
   - Go/no-go recommendation for deploying forward look as virtual sonar

2. **`forward_look_accuracy_plots.png`** — scatter plots:
   - Predicted vs actual depth at each distance
   - Error vs distance
   - Error distribution histogram
   - Directional match rate bar chart

3. **Recommendations:**
   - If RMS error < 10 fm at 500 m: deploy and integrate into agent_loop
   - If RMS error 10-20 fm: deploy with "low confidence" warnings
   - If RMS error > 20 fm: investigate grid quality; consider interpolation methods

---

## 8. Quick-Start Checklist

```
[ ] Create experiment_forward_look_harness.py
[ ] Verify NMEA bridge is running and position is updating
[ ] Verify sounder capture works (python capture.py --oneshot)
[ ] Verify contour query at position returns sensible depth
[ ] Verify forward look works at current position
[ ] Start experiment harness:
    python experiment_forward_look_harness.py \
        --interval 60 --duration 14400 \
        --output experiment_data/forward_look_pilot
[ ] Monitor first 10 cycles for data integrity
[ ] Let run for 4+ hours during vessel transit
[ ] After collection: run analysis notebook / script
[ ] Publish report
```

---

## 9. Replay Mode (Fallback)

If live vessel transit time is limited, the harness supports `--replay TRACK_JSON`
to simulate the experiment against logged track data plus grid queries. The
NMEA bridge's `window` field already contains historical positions:

```json
"window": [
  { "ts": "10:09:46", "lat": 55.78595, "lon": -131.527017, "sog": 1.6 }
]
```

Replay accelerates time (e.g., 60x) and runs the full experiment logic against
the logged track, treating each waypoint as a "current position" and simulating
what the forward look would have predicted.
