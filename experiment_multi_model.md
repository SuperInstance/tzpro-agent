# Multi-Model Experiment: Bathymetric Analysis Comparison

> **Objective**: Feed identical sensor data to 3+ AI models and compare their analyses.
> **Date**: 2026-07-15
> **Context**: CoCapn ecosystem on F/V EILEEN, Ketchikan, Alaska
> **Vessel**: F/V EILEEN, RTX 4050 6GB laptop, Ollama + TZ Pro sounder pipeline

---

## 1. The Hypothesis

**Not all intelligence is equal — and more importantly, not all blind spots overlap.**

When three different models analyze the same 4 data sources:
1. They will each notice different patterns
2. They will each have different failure modes
3. Their combined judgment will be more robust than any single model
4. Speed/quality tradeoffs will map to model architecture, not just parameter count

This experiment is the **fleet strategy validation** — the empirical test of whether the
multi-model approach in `boat_brain_models.md` produces better maritime situational
awareness than any single model alone.

---

## 2. Data Sources (The Fixed Inputs)

Every model in the experiment receives exactly these four data inputs, identically formatted.

### Input A — TZ Pro Sounder Screenshot (Last Capture)

| Field | Value |
|-------|-------|
| **Source file** | `captures/tzpro_20260715_190041_sounder.png` |
| **Crop** | `(1540, 100)-(1910, 1000)` = 370×900 px |
| **Palette** | Dark navy `rgb(14,29,52)` → blue → cyan → yellow → orange → red |
| **Depth range** | ~0–80 fm (proportional, 900 px tall) |
| **Bottom line** | Detected by `sounder_analyzer.py` via per-column brightest-pixel scan |
| **Analysis output** | JSON from `sounder_analyzer.analyze_sounder()` — bottom depth, type, fish returns, thermoclines, signal profile |

**Prompt given to each model:**
> Analyze this TZ Pro fishfinder screenshot. Identify: (1) the bottom depth and type,
> (2) any fish schools or individual targets, (3) thermocline layers,
> (4) whether the bottom is fishable for gear, and (5) anything unusual.
> Format as structured observations with confidence levels.

### Input B — Contour Profile at Current Position

| Field | Value |
|-------|-------|
| **Source** | `contour_query.py` + `elevation_grid.npy` (160 MB, 5000×8000 grid, 0.001° res) |
| **Coordinates** | Latest NMEA position from `http://127.0.0.1:8654/vessel` |
| **Outputs** | `get_depth_fm(lat, lon)` → charted depth; `get_gear_clearance()` → clearance + status; `get_contour_bands()` → nearby contour lines |
| **Grid bounds** | 54.0–59.0°N, -138.0 to -130.0°W (SE Alaska) |
| **Contour bands** | 5, 10, 20, 30, 48, 60, 80, 100, 150 fm |

**Prompt given to each model:**
> Here is the charted depth and contour data for our current position.
> Interpret: (1) what this tells us about the seafloor, (2) whether the
> chart data looks reliable, (3) how this area compares to surrounding
> bathymetry, (4) gear-fishing suitability.

### Input C — Anomaly Log Stats

| Field | Value |
|-------|-------|
| **Source** | `bathymetry/anomalies.db` via `anomaly_logger.stats()` |
| **Schema** | `(ts, lat, lon, sog, sounder_fm, contour_fm, delta_fm, source, cruise)` |
| **Stats format** | Total count, largest negative/positive deltas, avg magnitude, by source, recent 10 anomalies |
| **DB path** | `bathymetry/anomalies.db` (SQLite) |

**Prompt given to each model:**
> Here are the statistics from our bathymetric anomaly database — places where
> the real sounder reading disagreed with the charted contour depth.
> Interpret: (1) the overall health of our chart data, (2) systematic biases
> (is the chart consistently too shallow or too deep?), (3) geographic
> patterns in anomalies, (4) which anomalies need Captain attention.

### Input D — Forward Look Profile

| Field | Value |
|-------|-------|
| **Source** | `forward_look.predict_ahead()` — projects position along heading at 50–2000 m intervals |
| **Headings** | Current heading from NMEA, or synthetic test heading |
| **Outputs** | Depth profile at each distance, gear clearance, contour crossing alerts |
| **Alerts** | Critical (anchor-safe 5 fm crossing), Warning (gear contour 48 fm crossing) |

**Prompt given to each model:**
> Here is the forward-looking depth profile along our current heading.
> Interpret: (1) what's ahead in terms of seafloor changes, (2) critical
> contour crossings, (3) navigation risk, (4) optimal heading adjustment,
> (5) fishing strategy implications.

---

## 3. The Models

### Model Selection

| # | Model | Access | Strengths | Weaknesses | Role in Fleet |
|---|-------|--------|-----------|------------|---------------|
| **A** | **qwen3:4b** (Ollama, local) | `ollama run qwen3:4b` | Always on, low power, fast inference, zero latency | Limited reasoning depth, small context, misses subtle patterns | Always-on baseline monologue |
| **B** | **DeepSeek V4 Flash** (current session) | Native runtime | Very fast, good structured output, strong at summarization | Can hallucinate specifics with sparse data | Real-time alert triage |
| **C** | **Seed 2.0 Mini** (sub-agent) | Spawn as sub-agent | Creative connections, divergent thinking, pattern-finding | Less reliable with precise numbers, slower | Novel interpretation, "what else could this mean?" |
| **D** | **Hermes 3** (sub-agent) | Spawn as sub-agent | Philosophical/systemic thinking, meta-cognition | Verbose, sometimes over-interprets noise | Long-term system health, "what is the system learning?" |
| **E** | **Nemotron** (sub-agent) | Spawn as sub-agent | Engineering precision, quantitative analysis, technical rigor | Narrow focus, misses human/contextual factors | Calibration, thresholds, data quality checks |
| **F** | **DeepSeek V4 Pro** (sub-agent) | Spawn as sub-agent | Architectural reasoning, system-level thinking, strategic depth | Expensive (tokens), slower | Synthesis, strategy, "what should we build next?" |

### Which 3 for Each Run?

The experiment can be run with different triads depending on what we're testing:

| Run | Triad | Purpose |
|-----|-------|---------|
| **1** | A + B + C | Baseline: fastest available models. Tests local-vs-cloud-vs-creative. |
| **2** | A + D + E | Depth: philosophical + engineering + baseline. Tests coverage of blind spots. |
| **3** | B + E + F | Authority: Flash + Nemotron + Pro. Tests best-available analysis. |
| **4** | C + D + F | Divergence: creative + philosophical + strategic. Tests non-obvious insights. |
| **Full** | All 6 | Grand synthesis. Tests fleet-vs-single-model hypothesis. |

---

## 4. Experiment Protocol

### Step 1: Data Collection (Phase 1 — < 30 seconds)

Prepare one standardized JSON payload containing all 4 data sources:

```python
# experiment_runner.py — collects & serializes inputs
import json, time
from pathlib import Path
from anomaly_logger import stats as get_anomaly_stats
from forward_look import predict_ahead
from contour_query import get_depth_fm, get_gear_clearance, get_contour_bands
from config import CAPTURES_DIR

def collect_inputs(lat, lon, heading, sog):
    """Gather all 4 data sources into one standardized payload."""
    payload = {
        "experiment_ts": time.time(),
        "position": {"lat": lat, "lon": lon, "heading": heading, "sog": sog},
        "anomaly_stats": get_anomaly_stats(),
        "forward_look": predict_ahead(lat, lon, heading, sog),
        "contour": {
            "depth_fm": get_depth_fm(lat, lon),
            "gear_clearance": get_gear_clearance(lat, lon),
            "contour_bands": get_contour_bands(lat, lon),
        },
    }
    return payload
```

### Step 2: Prompt Template (identical for every model)

Each model receives the exact same prompt, injected with the payload from Step 1:

```
You are an expert maritime analyst examining sensor data from a commercial fishing
vessel in Southeast Alaska. Analyze the following 4 data sources and produce a
structured analysis.

IMPORTANT RULES:
- Be specific. Give numbers, depths, distances, bearings.
- State confidence levels (HIGH/MEDIUM/LOW) for every claim.
- Flag anything unusual, contradictory, or noteworthy.
- Format your response in the JSON structure below.

=== DATA INPUTS ===

[INPUT A — Sounder Screenshot Analysis]
{sounder_analysis_json}

[INPUT B — Contour Profile at Current Position]
{contour_json}

[INPUT C — Anomaly Log Statistics]
{anomaly_stats_json}

[INPUT D — Forward Look Profile]
{forward_look_json}

=== REQUIRED OUTPUT STRUCTURE ===

{
  "model": "<model_name>",
  "inference_time_s": <float>,
  "analysis": {
    "bottom_assessment": {
      "depth_fm": <float or null>,
      "type": "<hard|medium|soft|mixed|null>",
      "confidence": "<HIGH|MEDIUM|LOW>",
      "notes": "<string>"
    },
    "fish_activity": {
      "present": <bool>,
      "confidence": "<HIGH|MEDIUM|LOW>",
      "estimated_species": "<string or null>",
      "depth_range": "<string or null>",
      "notes": "<string>"
    },
    "chart_health": {
      "overall_confidence": "<HIGH|MEDIUM|LOW>",
      "systematic_bias": "<shallower|deeper|none>",
      "bias_magnitude_fm": <float or null>,
      "anomalous_hotspots": <int>,
      "notes": "<string>"
    },
    "navigation_risk": {
      "immediate_threat": "<bool>",
      "next_critical_crossing": "<string or null>",
      "distance_to_crossing_nm": <float or null>,
      "recommended_action": "<string>",
      "confidence": "<HIGH|MEDIUM|LOW>"
    },
    "fishing_recommendation": {
      "gear_friendly": "<bool>",
      "reason": "<string>",
      "alternate_headings": ["<bearing>", ...],
      "confidence": "<HIGH|MEDIUM|LOW>"
    },
    "unusual_observations": [
      {"observation": "<string>", "significance": "<HIGH|MEDIUM|LOW>"}
    ],
    "cross_correlation": {
      "sounder_vs_contour": "<string>",
      "forward_look_vs_anomalies": "<string>",
      "notes": "<string>"
    }
  }
}
```

### Step 3: Inference (Phase 2 — timed)

Each model receives the payload and generates its response. Timing is measured from
first token request to complete response.

**For qwen3:4b (local):** Use Ollama API, measure wall-clock time including
model load (should be negligible since it's always loaded).

**For all others:** Spawn as sub-agents with identical system prompt and input.
Measure wall-clock time from spawn to complete response.

### Step 4: Comparison (Phase 3)

The experiment runner compares model outputs on these dimensions:

| Dimension | Metric | Measurement |
|-----------|--------|-------------|
| **Speed** | Wall-clock time (seconds) | `response_time_s` |
| **Accuracy** | Depth agreement (fm) | `abs(model_depth - sounder_depth)` |
| **Coverage** | Fields filled in output structure | `filled_fields / total_fields` |
| **Confidence calibration** | Correlation between claimed confidence and actual correctness | Self-consistency: does HIGH confidence align with numerical accuracy? |
| **Novelty** | Observations not made by other models | Unique entries in `unusual_observations` |
| **False positive rate** | Claims of "fish" or "hazard" that don't match other evidence | Cross-model disagreement analysis |
| **False negative rate** | Missed anomalies that other models caught | Cross-model disagreement analysis |
| **Actionability** | Quality of recommended actions | Rated by human (Captain) on 1-5 scale |
| **Conciseness** | Tokens used relative to information density | `useful_claims / total_tokens` |
| **Hallucination rate** | Claims contradicted by input data | Manual audit |

---

## 5. Scoring Rubric

Each model gets a composite score across 4 axes:

### Axis 1: Analytical Quality (0–10)

| Score | Description |
|-------|-------------|
| 0–2 | Hallucinates data. Misses obvious patterns. Contradicts input. |
| 3–4 | Basic summarization. Gets depths/numbers right but no insight. |
| 5–6 | Good analysis. Catches major patterns. Reasonable recommendations. |
| 7–8 | Deep analysis. Cross-correlates data sources. Nuanced confidence. |
| 9–10 | Expert-level. Catches subtle patterns. Actionable insights. Identifies what questions to ask next. |

### Axis 2: Blind Spot Coverage (0–10)

Counts unique observations made by this model that *no other model* made:

| Uniques | Score |
|---------|-------|
| 0 | 0 |
| 1 | 3 |
| 2 | 5 |
| 3 | 7 |
| 4+ | 10 |

### Axis 3: Speed Efficiency (0–10)

Normalized against the fastest model in the run:

| Time Ratio (model / fastest) | Score |
|------------------------------|-------|
| ≤ 1.5× | 10 |
| ≤ 3× | 7 |
| ≤ 5× | 4 |
| ≤ 10× | 2 |
| > 10× | 0 |

### Axis 4: Actionability (0–10)

| Score | Description |
|-------|-------------|
| 0–2 | Vague recommendations ("monitor the situation") |
| 3–4 | Generic recommendations ("check the charts") |
| 5–6 | Specific recommendations ("adjust heading 15° to port") |
| 7–8 | Quantitative recommendations ("head 175° at 6 kts for 0.8 nm to the 48-fm line") |
| 9–10 | Captain-ready: specific, quantified, timed, with fallback plan |

### Composite Score

```
Composite = (Analytical × 0.35) + (Blind Spots × 0.20) + (Speed × 0.15) + (Actionability × 0.30)
```

The weights reflect the maritime domain: analysis and actionability matter most,
speed and blind spots are important but secondary.

---

## 6. Run Script

```python
#!/usr/bin/env python3
"""experiment_multi_model.py — Run the multi-model comparison experiment."""

import json, sys, time, subprocess
from pathlib import Path

WORKSPACE = Path(__file__).parent.resolve()
EXPERIMENTS_DIR = WORKSPACE / "experiments"
EXPERIMENTS_DIR.mkdir(exist_ok=True)

def run():
    """Execute the full experiment pipeline."""
    from anomaly_logger import stats
    from forward_look import predict_ahead
    from contour_query import get_depth_fm, get_gear_clearance, get_contour_bands
    from capture import get_latest_nmea

    # 1) Collect inputs
    nmea = get_latest_nmea()
    lat, lon, hdg, sog = nmea["lat"], nmea["lon"], nmea["heading"], nmea["sog"]
    
    payload = {
        "experiment_ts": time.time(),
        "position": {"lat": lat, "lon": lon, "heading": hdg, "sog": sog},
        "anomaly_stats": stats(),
        "forward_look": predict_ahead(lat, lon, hdg, sog),
        "contour": {
            "depth_fm": get_depth_fm(lat, lon),
            "gear_clearance": get_gear_clearance(lat, lon),
            "contour_bands": get_contour_bands(lat, lon),
        },
    }
    
    # 2) Build the prompt template
    prompt_template = """..."""  # (template from §4 above)
    
    # 3) Run each model
    models = {
        "qwen3:4b": lambda p: _query_ollama("qwen3:4b", p),
        "seed2_mini": lambda p: _spawn_subagent("Seed 2.0 Mini", p),
        "hermes3": lambda p: _spawn_subagent("Hermes 3", p),
        "nemotron": lambda p: _spawn_subagent("Nemotron", p),
        "deepseek_v4_pro": lambda p: _spawn_subagent("DeepSeek V4 Pro", p),
    }
    
    results = {}
    for name, runner in models.items():
        print(f"[experiment] Running {name}...")
        t0 = time.time()
        response = runner(payload)
        elapsed = time.time() - t0
        results[name] = {"response": response, "time_s": round(elapsed, 2)}
        print(f"[experiment] {name} done in {elapsed:.1f}s")
    
    # 4) Compare and score
    comparison = compare_results(results)
    
    # 5) Write output
    run_id = time.strftime("%Y%m%d_%H%M%S")
    out_path = EXPERIMENTS_DIR / f"experiment_{run_id}.json"
    out_path.write_text(json.dumps({
        "experiment_id": run_id,
        "inputs": payload,
        "results": results,
        "comparison": comparison,
    }, indent=2))
    
    print(f"\n[experiment] Results written to {out_path}")
    return results, comparison
```

---

## 7. Scoring Execution

```python
def compare_results(results: dict) -> dict:
    """Compare model outputs and produce the comparison matrix."""
    
    # Empty comparison scaffold
    comparison = {
        "run_ts": time.time(),
        "fastest_model": None,
        "slowest_model": None,
        "time_range_s": None,
        "overall_ranking": [],
        "per_axis_scores": {},
        "unique_observations": {},
        "consensus_map": {},
    }
    
    # Find speed extremes
    times = {name: r["time_s"] for name, r in results.items()}
    fastest = min(times, key=times.get)
    slowest = max(times, key=times.get)
    comparison["fastest_model"] = fastest
    comparison["slowest_model"] = slowest
    comparison["time_range_s"] = times[slowest] - times[fastest]
    
    # Parse each model's response into structured comparison
    all_observations = []
    for name, r in results.items():
        try:
            parsed = json.loads(r["response"])
            r["parsed"] = parsed
        except (json.JSONDecodeError, TypeError):
            r["parsed"] = {"error": "failed to parse"}
            continue
        
        # Collect unusual observations
        obs = parsed.get("analysis", {}).get("unusual_observations", [])
        all_observations.append({"model": name, "observations": obs})
    
    # Find unique observations (made by only one model)
    obs_by_content = {}
    for entry in all_observations:
        for obs in entry["observations"]:
            text = obs.get("observation", "")
            sig = obs.get("significance", "LOW")
            obs_by_content.setdefault(text, []).append(entry["model"])
    
    unique_obs = {obs: models for obs, models in obs_by_content.items() if len(models) == 1}
    comparison["unique_observations"] = unique_obs
    
    # Consensus map: which claims do all models agree on?
    for entry in all_observations:
        model = entry["model"]
        parsed = results[model].get("parsed", {})
        analysis = parsed.get("analysis", {})
        
        # Extract key claims
        bottom = analysis.get("bottom_assessment", {})
        fish = analysis.get("fish_activity", {})
        nav = analysis.get("navigation_risk", {})
        
        comparison.setdefault("consensus_map", {}).setdefault("bottom_depth_fm", {})
        comparison["consensus_map"]["bottom_depth_fm"][model] = bottom.get("depth_fm")
        
        comparison.setdefault("consensus_map", {}).setdefault("fish_present", {})
        comparison["consensus_map"]["fish_present"][model] = fish.get("present")
        
        comparison.setdefault("consensus_map", {}).setdefault("immediate_threat", {})
        comparison["consensus_map"]["immediate_threat"][model] = nav.get("immediate_threat")
    
    # Compute per-axis scores for each model
    for name in results:
        axis_scores = {}
        parsed = results[name].get("parsed", {}).get("analysis", {})
        
        # Axis 1: Analytical Quality
        filled_fields = sum(1 for v in _flatten(parsed) if v is not None)
        total_fields = sum(1 for _ in _flatten(parsed))
        depth_accuracy = abs(parsed.get("bottom_assessment", {}).get("depth_fm", 0) or 0)
        has_cross_correlation = bool(parsed.get("cross_correlation", {}).get("sounder_vs_contour", ""))
        axis_scores["analytical_quality"] = min(10, round(
            (filled_fields / max(total_fields, 1) * 5) +
            (0.5 if depth_accuracy < 3 else 0) +
            (2 if has_cross_correlation else 0)
        , 1))
        
        # Axis 2: Blind Spot Coverage
        unique_for_model = [obs for obs, models in unique_obs.items() if name in models]
        n_unique = len(unique_for_model)
        if n_unique == 0:
            axis_scores["blind_spots"] = 0
        elif n_unique == 1:
            axis_scores["blind_spots"] = 3
        elif n_unique == 2:
            axis_scores["blind_spots"] = 5
        elif n_unique == 3:
            axis_scores["blind_spots"] = 7
        else:
            axis_scores["blind_spots"] = 10
        
        # Axis 3: Speed
        time_ratio = results[name]["time_s"] / results[fastest]["time_s"]
        if time_ratio <= 1.5:
            axis_scores["speed"] = 10
        elif time_ratio <= 3:
            axis_scores["speed"] = 7
        elif time_ratio <= 5:
            axis_scores["speed"] = 4
        elif time_ratio <= 10:
            axis_scores["speed"] = 2
        else:
            axis_scores["speed"] = 0
        
        comparison.setdefault("per_axis_scores", {})[name] = axis_scores
    
    # Overall ranking
    composite_scores = {}
    for name in results:
        a = comparison["per_axis_scores"].get(name, {})
        composite = (
            a.get("analytical_quality", 0) * 0.35 +
            a.get("blind_spots", 0) * 0.20 +
            a.get("speed", 0) * 0.15 +
            a.get("actionability", 5) * 0.30  # placeholder until human-rated
        )
        composite_scores[name] = round(composite, 2)
    
    ranking = sorted(composite_scores, key=composite_scores.get, reverse=True)
    comparison["overall_ranking"] = ranking
    comparison["composite_scores"] = composite_scores
    
    return comparison


def _flatten(d, parent_key=""):
    """Flatten nested dict for field counting."""
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}.{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(_flatten(v, new_key))
        else:
            items.append((new_key, v))
    return items
```

---

## 8. Expected Results (Hypothesis)

Based on known model characteristics and the fleet strategy in `boat_brain_models.md`:

### Run 1: qwen3:4b + DeepSeek Flash + Seed 2.0 Mini

| Model | Analytical | Blind Spots | Speed | Actionability | Composite |
|-------|-----------|-------------|-------|---------------|-----------|
| qwen3:4b | 5 | 3 | 10 | 5 | 5.80 |
| DeepSeek Flash | 7 | 5 | 8 | 7 | **7.10** |
| Seed 2.0 Mini | 6 | **8** | 5 | 6 | 6.30 |

**Prediction**: DeepSeek Flash wins on composite, but Seed 2.0 Mini catches the
most unique observations. qwen3:4b is fastest but shallow.

### Run 2: qwen3:4b + Hermes 3 + Nemotron

| Model | Analytical | Blind Spots | Speed | Actionability | Composite |
|-------|-----------|-------------|-------|---------------|-----------|
| qwen3:4b | 5 | 3 | 10 | 5 | 5.80 |
| Hermes 3 | 7 | **7** | 3 | 6 | 5.95 |
| Nemotron | **8** | 5 | 5 | **8** | **7.05** |

**Prediction**: Nemotron dominates analytical and actionability. Hermes 3 catches
systemic issues others miss. qwen3:4b is the baseline.

### Run 3: DeepSeek Flash + Nemotron + DeepSeek Pro

| Model | Analytical | Blind Spots | Speed | Actionability | Composite |
|-------|-----------|-------------|-------|---------------|-----------|
| DeepSeek Flash | 7 | 4 | 8 | 7 | 6.65 |
| Nemotron | 8 | 5 | 5 | 8 | **7.05** |
| DeepSeek Pro | **9** | **6** | 3 | **9** | **7.75** |

**Prediction**: DeepSeek Pro wins overall but is slowest. Nemotron gives best
speed-quality tradeoff.

### Full Run (All 6)

| Rank | Model | Expected Composite | Primary Strength |
|------|-------|-------------------|-----------------|
| 1 | DeepSeek V4 Pro | 7.5–8.5 | Strategic depth + synthesis |
| 2 | Nemotron | 7.0–8.0 | Engineering precision |
| 3 | DeepSeek Flash | 6.5–7.5 | Speed + structure |
| 4 | Seed 2.0 Mini | 6.0–7.0 | Novel observations |
| 5 | Hermes 3 | 5.5–6.5 | Systemic thinking |
| 6 | qwen3:4b | 5.0–6.0 | Baseline speed |

**Key insight**: The top-3 model ensemble (Pro + Nemotron + Seed2) likely catches
>90% of important observations while the single-best model (Pro alone) catches
~75%. This is the fleet strategy hypothesis — test it here.

---

## 9. What Each Model Likely Notices That Others Miss

These are predictions based on model architecture and training. They will be
verified/falsified by actual experiment runs.

### qwen3:4b — Baseline Local

**Notices:**
- Obvious depth changes (>10 fm)
- Whether the sounder image is clearly blank (no data)
- Simple numerical consistency checks

**Misses:**
- Subtle bottom type differences (hard vs medium vs soft)
- Fish arch patterns
- Cross-correlation between data sources
- Anomaly trends over time

### DeepSeek V4 Flash — Fast Cloud

**Notices:**
- Structured analysis following the JSON template completely
- Numerical outliers in anomaly stats
- Obvious contour crossings in forward look
- Whether the sounder bottom matches the contour depth (within ±5 fm)

**Misses:**
- Subtle fish return patterns in sounder ("is that a school or noise?")
- Contextual reasoning ("this area is known for halibut")
- Long-term trends across multiple data sources

### Seed 2.0 Mini — Creative

**Likely unique observations:**
- "The bottom signal has a layered pattern that could indicate different sediment compositions"
- "This area might be a historic dredge spoil zone" (connects anomaly pattern to external knowledge)
- "The depth discrepancy correlates with tidal phase"
- "Fish returns clustering at thermocline suggests feeding behavior — might be salmon staging"

### Hermes 3 — Philosophical/Systemic

**Likely unique observations:**
- "The anomaly pattern suggests the chart data has systematic bias in this quadrant, not random noise"
- "The system is learning — comparison of early vs recent anomalies shows improving contour match rate"
- "The 48-fm line here is acting as a natural boundary for the species we're seeing"
- "What's the sampling bias? We have more anomalies in areas we fish more often"

### Nemotron — Engineering

**Likely unique observations:**
- "Sounder depth scale calibration may be off: autocorrelation suggests a consistent 2.1 fm offset"
- "The forward look prediction RMS error of X fm indicates the contour grid needs local refinement"
- "Anomaly confidence intervals: ±1.8 fm at 95% CI based on N=47 observations"
- "The bottom roughness index of X suggests a transition zone, not a homogeneous bottom type"

### DeepSeek V4 Pro — Strategic

**Likely unique observations:**
- "This area has structural potential for a Digital Twin correction patch — sufficient anomaly density"
- "The risk profile suggests we should run a targeted survey line at heading 215° to validate the 48-fm contour here"
- "Combined analysis: the sounder- chart delta at this location, when combined with bottom type change, suggests a debris field or wreck"
- "Fleet strategy update: we should prioritize Session 3 (heatmap + correction) for this quadrant"

---

## 10. Output Artifacts

After each run, the experiment produces:

| File | Contents |
|------|----------|
| `experiments/experiment_YYYYMMDD_HHMMSS.json` | Full raw results + comparison | 
| `experiments/experiment_YYYYMMDD_HHMMSS_summary.md` | Human-readable summary including ranking, unique observations, and recommendations |
| `experiments/latest.json` | Symlink to latest experiment (for dashboard consumption) |

### Summary Format (`*_summary.md`)

```markdown
# Multi-Model Experiment: YYYY-MM-DD HH:MM

## Inputs
- Position: 55.3422°N, 131.6433°W
- Heading: 90°, SOG: 6.0 kts
- Contour depth: 67.3 fm
- Anomalies in DB: 47

## Models Tested
1. qwen3:4b — 4.2s
2. DeepSeek V4 Flash — 6.8s
3. Seed 2.0 Mini — 12.1s
4. Hermes 3 — 18.5s
5. Nemotron — 15.3s
6. DeepSeek V4 Pro — 22.7s

## Rankings
| Rank | Model | Composite | Analytical | Blind Spots | Speed | Actionability |
|------|-------|-----------|-----------|-------------|-------|---------------|
| 1 | DeepSeek V4 Pro | 7.8 | 8.5 | 6.0 | 3.0 | 9.0 |
| 2 | Nemotron | 7.1 | 8.0 | 5.0 | 5.0 | 8.0 |
| ... | ... | ... | ... | ... | ... | ... |

## Unique Observations
(Observations made by exactly one model)

**Seed 2.0 Mini:**
- "Fish clustering at thermocline suggests salmon staging"
- "Depth anomaly pattern matches known dredge spoil zone"

**Hermes 3:**
- "Anomaly distribution shows spatial bias toward frequently-fished areas"

**Nemotron:**
- "Consistent 2.1 fm offset suggests depth scale calibration error"

## Consensus
All models agree on:
- Bottom depth: ~67 fm (±3 fm)
- No immediate navigation threat
- Gear-fishable depth

## Recommendations
1. Calibrate depth scale (Nemotron's 2.1 fm offset)
2. Run survey line at heading 215° to validate 48-fm contour
3. Proceed with Session 3 heatmap for this quadrant
```

---

## 11. Evolution Plan

The experiment framework itself should improve over time:

### v1 — Manual Analysis (this document)
- Run experiments manually
- Parse responses by hand
- Score qualitatively
- Write comparisons manually

### v2 — Automated Runner
- `experiment_multi_model.py` runs autonomously
- Automated scoring with the rubric above
- Writes comparison JSON + summary markdown
- Schedules runs at configurable intervals (e.g., every 6 hours while fishing)

### v3 — Dashboard Integration
- Results feed into Streamlit dashboard
- Historical comparison across runs (model improvement over time)
- Visual comparison: radar charts per model, heatmaps of unique observations
- Captain can rate actionability scores → ground truth for scoring

### v4 — Adaptive Fleet Routing
- Experiment results feed back into model selection
- If Seed 2.0 Mini consistently catches unique fish observations, route fish-related queries to it
- If Nemotron consistently identifies calibration issues, route quantitative queries to it
- The fleet becomes self-optimizing based on actual measured performance

---

## 12. Quick-Start Checklist

- [ ] Ensure Ollama is running: `ollama ps` shows qwen3:4b
- [ ] Verify anomaly DB has data: `python anomaly_logger.py --stats`
- [ ] Verify NMEA bridge is up: `curl http://127.0.0.1:8654/vessel`
- [ ] Verify forward look works: `python forward_look.py`
- [ ] Choose a triad from §3 (start with Run 1: qwen3:4b + Flash + Seed2)
- [ ] Collect inputs via `experiment_collect.py`
- [ ] Spawn sub-agents with identical prompt
- [ ] Score and compare results
- [ ] Write summary to `experiments/`
- [ ] Repeat with different triads
- [ ] After 3+ runs: reassess the fleet strategy hypothesis

---

*Experiment Framework v1 — CoCapn Ecosystem*
*F/V EILEEN — Ketchikan, Alaska*
