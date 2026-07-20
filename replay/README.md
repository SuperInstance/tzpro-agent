# replay v0 — Perception Replay Harness

**What it is:** A lightweight script that answers "would we have done the same thing?" by re-running perception analysis over stored twin data and comparing fresh results to stored records.

**What it is NOT:**
- NOT a framework — it's a single-purpose script with a clear exit criteria
- NOT counterfactual — it doesn't test alternate conditions (that's the disturbance-observer upgrade in boat-agent docs/25)
- NOT a full testing suite — it focuses on perception drift detection

## Purpose

The replay harness validates that your perception pipeline remains stable over time. By re-analyzing stored frames with current models and comparing to original records, you can detect:
- Model drift (semantic changes in vision output)
- Threshold violations (numeric tolerances exceeded)
- Vocabulary shifts (search term divergence)

## Installation

No external dependencies required — uses stdlib only.

```bash
cd replay/
python -m replay.cli <twin_root> <date>
```

## Usage

### Basic: Self-Consistency Check (Stub Mode)

The default `--model` flag disabled uses a stub analyzer that returns the stored record data, yielding 1.0 agreement (self-consistency validation).

```bash
python -m replay.cli <twin_root> <date>
```

Example:
```bash
python -m replay.cli C:/Users/casey/.openclaw/workspace/tzpro-agent/twin 2024-01-15
```

Output:
```
============================================================
REPLAY REPORT — 2024-01-15
============================================================
Frames:     144
Replayed:   144
Agreement:  100.0%

✓ No disagreements found

✓ Verdict: PASS
```

### Model Replay: Real Vision Inference

Use `--model` to run actual vision models via cascade's ollama_client:

```bash
python -m replay.cli <twin_root> <date> --model
```

This re-runs M10 analysis on each frame and compares to stored records, detecting real drift.

### Verbose Output

Show all disagreements (not just top 5):

```bash
python -m replay.cli <twin_root> <date> --verbose
```

### JSON Output

Get the raw structured report:

```bash
python -m replay.cli <twin_root> <date> --json > report.json
```

## Agreement Criteria

A frame is considered "in agreement" if ALL of:
1. **Bottom type matches** (if both present)
2. **Bottom depth within 3.0 fathoms** (`|bottom_fm delta| <= 3.0`)
3. **Search terms overlap sufficiently** (Jaccard similarity >= 0.3)

## Verdict

- **PASS**: >= 80% agreement (0.8 threshold)
- **DRIFT**: < 80% agreement

Exit code: 0 for PASS, 1 for DRIFT (useful for CI/CD).

## Output Format

### Human-Readable Report

```
============================================================
REPLAY REPORT — 2024-01-15
============================================================
Frames:     144
Replayed:   140
Agreement:  92.1%

Disagreements (11):
------------------------------------------------------------

[1] Frame: 00000192a3e2d8f4c1b2
    bottom_fm: stored=45.0 vs fresh=51.0 (delta=6.0)

[2] Frame: 00000192a3e2d8f4c1b3
    search_terms: Jaccard=0.0
      stored: ['chum', 'feed', 'school']
      fresh:  ['herring', 'bait']
...

⚠ Verdict: DRIFT

Note: 4 frames skipped (no stored record or blob missing)
```

### JSON Report

```json
{
  "date": "2024-01-15",
  "frames": 144,
  "replayed": 140,
  "agreement_rate": 0.9214,
  "per_frame": [
    {
      "frame_id": "00000192a3e2d8f4c1b2",
      "stored": {
        "bottom_type": "hard",
        "bottom_fm": 45.0,
        "search_terms": "chum feed school"
      },
      "fresh": {
        "bottom_type": "hard",
        "bottom_fm": 51.0,
        "search_terms": ["chum", "feed"]
      },
      "agree": false,
      "deltas": [
        {
          "field": "bottom_fm",
          "stored": 45.0,
          "fresh": 51.0,
          "delta": 6.0
        }
      ]
    }
  ]
}
```

## Determinism

The harness is deterministic: replaying the same date twice produces byte-identical JSON reports (sorted keys, no wall-clock timestamps in output).

This enables:
- CI/CD integration
- Regression tracking
- Diff-based validation

## Integration

### With Twin

The replay harness reads from twin's meta.db and blob storage:

```python
from replay import replay

# Load a day's data
day_data = replay.load_day(twin_root, "2024-01-15")

# Run replay
report = replay.replay_day(twin_root, "2024-01-15")
```

### With Cascade

The `--model` flag integrates with cascade's ollama_client for vision inference:

```python
from replay import replay

# Get a model analyzer
analyzer = replay._model_analyzer(twin_root, model="gemma4:12b")

# Run with real model
report = replay.replay_day(twin_root, "2024-01-15", analyzer)
```

## Testing

Run the test suite:

```bash
python -m unittest replay.test_replay -v
```

Tests cover:
1. Self-consistency (stub analyzer = 1.0 agreement)
2. Perturbed analyzer detection
3. Determinism (byte-identical reports)
4. Empty day error handling
5. Date validation

## Future: Disturbance Observer (v1)

Per boat-agent docs/25, v1 will add counterfactual testing:
- What if we had used a different model?
- What if we had enabled different equipment?
- What if conditions were different?

v0 focuses on validating current perception stability — v1 explores alternate realities.

## License

Same as parent tzpro-agent project.
