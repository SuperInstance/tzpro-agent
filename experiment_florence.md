# Experiment: Florence-2 on Fishing Sounder Images

**Date:** 2026-07-15  
**Duration:** ~4 hours (single afternoon)  
**Hardware:** RTX 4050 6GB (CUDA 12.4, PyTorch 2.6.0)  
**Model:** microsoft/florence-2-base (232M params, FP16 ~500 MB VRAM)  
**Images:** TZ Pro sounder crops — 370×900px, RGBA → RGB, blue/dark palette  
**Existing baseline:** `sounder_analyzer.py` (OpenCV pixel thresholds)  
**Florence-2 integration:** `vision.py` (`load_model()`, `analyze_sounder_vl()`)

---

## Overview

This experiment tests whether Florence-2's visual-language capabilities add value over the existing OpenCV threshold-based `sounder_analyzer.py` for four specific tasks. Each task has its own prompt design, test set, success criteria, and scoring.

**Why Florence-2?** Pixel thresholds are fragile — they depend on a fixed color palette, ignore spatial semantics, and can't read numbers. Florence-2 understands images as scenes, can OCR, and can reason about what it sees. But it's also slower and may hallucinate. This experiment quantifies the trade-offs.

---

## Preparation (30 min)

### 1.1 Image Inventory

Catalog the existing sounder crop images in `captures/` by ground-truth annotation:

| Image | Known Content | Notes |
|-------|---------------|-------|
| `*_sounder` files (6–10 images) | Varying depths, fish arches, bottom types | Need expert label or reasonable guess per filename timestamp |
| `_sounder_check.png` | Unknown | Check if it's a test/calibration image |

**Action:** Open each image in a viewer and annotate with:
- Approximate bottom depth (visual estimate from scale)
- Visible fish arches (count)
- Bottom type (hard/mixed/soft — estimated from color intensity at bottom line)
- Scale tick marks visible (list of depth numbers)

Save annotations in a companion file `experiment_florence_ground_truth.json`.

### 1.2 Script Setup

Create `run_experiment.py` as the orchestration script (to be written during the experiment). It will:
- Load Florence-2 once (reuse across all tasks)
- Iterate over test images
- Run each prompt variant
- Run the OpenCV baseline for comparison
- Measure timing
- Output structured results JSON

### 1.3 Verify Environment

```bash
cd C:\Users\casey\.openclaw\workspace\tzpro-agent
.\venv_cuda\Scripts\python.exe -c "from vision import load_model; print(load_model())"
# Expected: True (model loads on CUDA in ~10-15s first time)
```

---

## Task 1: Fish Arch Detection (90 min)

### 1.1 Goal

Can Florence-2 identify the characteristic "arch" shape of fish returns in the blue palette sounder, and can it do so more reliably than pixel brightness thresholds?

### 1.2 Prompts to Test

**Prompt A — Simple binary (fastest):**
```
<CAPTION>Does this fishfinder image show any fish or schools?
Answer yes or no and describe where.
```

**Prompt B — Structured extraction (recommended):**
```
<OD>Analyze this fishfinder sonar image in detail.
List all fish arches or schools visible. For each one, give:
- depth (fraction of screen or estimated meters)
- size (single fish, small school, large school)
- position (left, center, right of the display)
If no fish are visible, answer "No fish detected."
```

**Prompt C — Numeric counting:**
```
<CAPTION>Count the number of individual fish or fish schools visible
in this sonar image. Output only a number and nothing else.
```

**Prompt D — Baseline comparison prompt (reuses `analyze_sounder_vl()`):**
```
<OD>What is in this fishfinder image? Describe: bottom depth, bottom type
(hard/soft/muddy/rocky), fish or schools visible and at what depth,
any temperature layers or thermoclines.
```
(This is the prompt currently in `vision.py`'s `analyze_sounder_vl()`.)

### 1.3 Test Images

| Test Case | Image | Ground Truth |
|-----------|-------|-------------|
| 1a | Clean water, no fish | Confirm no false positives |
| 1b | Single strong arch | Count=1, centered |
| 1c | Multiple scattered returns | Count=3-5, various depths |
| 1d | Dense school (cloud return) | Count=1 school, mid-water |
| 1e | Fish near bottom | Hard to separate from bottom return |
| 1f | Surface clutter + weak returns | Should distinguish fish from noise |

### 1.4 OpenCV Baseline (`sounder_analyzer.py`)

Run the existing `analyze_sounder()` on each image. Record:
- `fish_returns.count` (number of bright pixels above threshold)
- `fish_returns.distribution` (scattered/moderate/dense/very_dense)
- `fish_returns.depth_range`
- False positive count (detections in known-empty regions)

### 1.5 Success Criteria

| Metric | Target | How to Measure |
|--------|--------|----------------|
| Precision | ≥80% | TP / (TP + FP) where TP = fish actually present |
| Recall | ≥70% | TP / (TP + FN) |
| False positive rate | ≤20% of images with no fish |
| Arch detection | ≥1 arch named per image that has arches | Free-text "arch" mentions |
| vs OpenCV improvement | ≥15% better F1 | Compare to pixel threshold F1 |

### 1.6 Scoring

Image-by-image matrix:

```
+------------------+--------+--------+--------+
| Image            | OpenCV | Flor-A | Flor-B |
|                  | F1     | F1     | F1     |
+------------------+--------+--------+--------+
| Clean water      | 1.0    | 1.0    | 1.0    |  (TN — both should say no fish)
| Single arch      | 0.8    | 0.9    | 0.95   |  (estimated)
| Multiple returns  | 0.7    | 0.8    | 0.85   |
| Dense school     | 0.6    | 0.9    | 0.95   |  (thresholding struggles with column-like return)
| Fish near bottom | 0.3    | 0.6    | 0.7    |  (VL can distinguish shape from bottom)
| Surface clutter  | 0.5    | 0.7    | 0.8    |
+------------------+--------+--------+--------+
```

**Decision rule:** If any Florence-2 prompt variant achieves F1 ≥0.8 AND beats OpenCV by ≥0.1 on at least 3 of 6 test cases, Florence-2 is considered superior for fish detection.

---

## Task 2: Bottom Type Classification (45 min)

### 2.1 Goal

Can Florence-2 classify bottom type (hard rock, sandy, muddy/soft, mixed) from the blue palette return colors, and does it match or exceed the OpenCV color-channel heuristics?

### 2.2 Prompts to Test

**Prompt A — Explicit bottom classification:**
```
<CAPTION>Classify the bottom type in this sonar image.
Choose one: hard_rock, sandy, muddy_soft, or mixed.
Base your answer on the color and texture of the bottom return line.
Output only the classification word.
```

**Prompt B — With visual reasoning (slower but richer):**
```
<OD>Examine the bottom return band in this fishfinder image.
Describe the bottom type based on:
- Color of the return (red/orange = hard, green/yellow = medium, blue/cyan = soft)
- Thickness of the bottom band (thin = hard, thick = soft/muddy)
- Texture (smooth = sand/mud, rough/uneven = rock)
Classify as: hard_rock, sandy, muddy_soft, or mixed.
```

### 2.3 OpenCV Baseline

`_find_bottom()` in `sounder_analyzer.py` classifies based on color-channel ratios:
- `avg_r > 200` → `hard`
- `avg_g > avg_r` and `avg_g > 150` → `medium`
- `avg_b > avg_r` and `avg_b > 100` → `soft_mud`
- else → `mixed`

Also provides `hardness_score` and `roughness`.

### 2.4 Test Images

Each image's bottom type should be gaze-estimated by a human looking at the image:
- Hard: bright red/orange bottom band, thin
- Mixed: warm colors, moderate thickness
- Soft: blue/green bottom, thick band
- Mixed: combination

### 2.5 Success Criteria

| Metric | Target |
|--------|--------|
| Bottom type accuracy | ≥75% agreement with human label |
| vs OpenCV improvement | ≥10% better accuracy |
| Confusion analysis | Which misclassifications occur? (e.g., Florence-2 calling hard bottom "mixed") |
| Confidence calibration | Does VL output include hedging language? |

---

## Task 3: Depth Number Reading (30 min)

### 3.1 Goal

Can Florence-2 read the numeric depth-scale tick marks from the right edge of the sounder panel? The existing approach uses Tesseract OCR on a cropped strip — this tests whether VL-based OCR is better.

### 3.2 Prompts to Test

**Prompt A — Direct number extraction:**
```
<OCR>Read all the depth numbers on the right edge scale of this
fishfinder image. List them from top to bottom. Output as comma-separated numbers.
```

**Prompt B — With spatial context:**
```
<CAPTION>What depth numbers are printed on the scale at the right
edge of this sonar image? List each depth value you see.
```

### 3.3 OpenCV Baseline

`sounder_analyzer.py` extracts the scale via:
```python
scale_crop = img.crop((DEPTH_SCALE_X, 0, w, h))  # x=350 to 370 in the 370px crop
pytesseract.image_to_string(scale_crop, config="--psm 6 digits")
```

### 3.4 Test Images

All sounder images with scale ticks visible. Manually read the numbers (ground truth).

### 3.5 Success Criteria

| Metric | Target |
|--------|--------|
| Digit accuracy | ≥90% of numbers correctly read (not OCR character error, but full number correctness) |
| vs Tesseract improvement | Florence-2 should match or exceed Tesseract accuracy on small, low-res digits |
| Speed trade-off | Is VL OCR fast enough for 30-second cadence? Flo-P2 should take < 3s per image |

**Note:** The depth scale is only ~20px wide at the right edge of a 370px image. Digits may be ~10-15px tall. Florence-2 was not trained as an OCR model. If accuracy is below 60%, this task is considered **not viable** and the pixel-based approach should remain.

---

## Task 4: Inference Speed Benchmark (30 min)

### 4.1 Goal

Quantify GPU vs CPU inference time for Florence-2 on 370×900 images, and compare to the OpenCV baseline.

### 4.2 Timing Protocol

Run each prompt 5 times per image. Record:

| Metric | Device | Measurement |
|--------|--------|-------------|
| Model load time | CUDA | `load_model()` wall time |
| Model load time | CPU | Same (if CPU test done) |
| First inference | CUDA | First `generate()` call (CUDA warmup) |
| Subsequent inference (avg) | CUDA | Mean of runs 2-5 |
| Subsequent inference (stdev) | CUDA | Variability across runs |
| OpenCV analysis | CPU | `analyze_sounder()` wall time |

### 4.3 Expected Ranges

| Component | Expected Time | Notes |
|-----------|--------------|-------|
| Florence-2 model load (CUDA) | 8-15 s | Downloads weights if not cached, then loads to GPU |
| Florence-2 first inference (CUDA) | 3-5 s | CUDA graph compilation / cache warmup |
| Florence-2 subsequent (CUDA) | 2-3 s | Steady state, FP16 |
| Florence-2 subsequent (CPU) | 8-15 s | Rough estimate, untested |
| OpenCV analysis | 0.3-0.8 s | Fast pixel ops, CPU only |
| Tesseract OCR | 0.5-1.5 s | External process overhead |
| Florence-2 + Tesseract combined | 2.5-4.5 s | If we use VL + pixel OCR together |

### 4.4 VRAM Monitoring

Record VRAM usage at each step:
```python
import torch
torch.cuda.reset_peak_memory_stats()
# ... run inference ...
peak = torch.cuda.max_memory_allocated() / 1024**2  # MB
```

| Step | Expected VRAM (MB) |
|------|-------------------|
| Idle (no model) | ~500 (OS + other apps) |
| After model load | ~1100 (base 500 + florence 500 + overhead) |
| During inference | ~1400 (intermediate tensors) |
| Peak observed | ~1600 (max_new_tokens=200, num_beams=3) |

### 4.5 Success Criteria

- CUDA inference must average ≤4s per image (necessary for 30s sounder cadence)
- If average >6s, reduce `max_new_tokens` or `num_beams` to trade accuracy for speed
- OpenCV remains the fast path; Florence-2 is the "rich understanding" path

---

## Data Collection Script

The experiment should be driven by a single script. Here is the skeleton:

```python
# run_experiment.py — Florence-2 vs OpenCV experiment harness
import sys, json, time, torch, csv
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from vision import load_model, analyze_sounder_vl, unload, _model, _processor, _device
from sounder_analyzer import analyze_sounder

# Load ground truth
with open("experiment_florence_ground_truth.json") as f:
    ground_truth = json.load(f)

# Image directory
CAPTURES = Path("captures")
SOUNDER_FILES = sorted(CAPTURES.glob("*_sounder*.png"))

results = []

# Track VRAM
torch.cuda.reset_peak_memory_stats()
vram_before = torch.cuda.memory_allocated()

# Load model once
load_model()

vram_after_load = torch.cuda.memory_allocated()
print(f"VRAM load delta: {(vram_after_load - vram_before) / 1024**2:.1f} MB")

for img_path in SOUNDER_FILES:
    gt = ground_truth.get(img_path.name, {})
    print(f"\n=== {img_path.name} ===")

    # ---- OpenCV Baseline ----
    t0 = time.time()
    opencv_result = analyze_sounder(img_path)
    t_cv = time.time() - t0

    # ---- Florence-2 VL (prompt D = current analyze_sounder_vl) ----
    t0 = time.time()
    vl_result = analyze_sounder_vl(img_path)
    t_vl = time.time() - t0

    # ---- Florence-2 (prompt A = binary fish detection) ----
    t0 = time.time()
    img = Image.open(img_path).convert("RGB")
    inputs = _processor(text="<CAPTION>Does this fishfinder image show any fish or schools? Answer yes or no and describe where.",
                        images=img, return_tensors="pt").to(_device)
    generated_ids = _model.generate(
        input_ids=inputs["input_ids"],
        pixel_values=inputs["pixel_values"],
        max_new_tokens=100,
        num_beams=3,
    )
    prompt_a_text = _processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
    t_a = time.time() - t0

    # We'll add more prompt variants as the experiment runs

    results.append({
        "image": img_path.name,
        "ground_truth": gt,
        "opencv": opencv_result,
        "opencv_time_s": round(t_cv, 3),
        "florence_prompt_d": vl_result,
        "florence_prompt_d_time_s": round(t_vl, 3),
        "florence_prompt_a_raw": prompt_a_text,
        "florence_prompt_a_time_s": round(t_a, 3),
    })

with open("experiment_florence_results.json", "w") as f:
    json.dump(results, f, indent=2, default=str)

unload()
print("\nDone. Results in experiment_florence_results.json")
```

---

## Analysis Script

After collecting data, run analysis with:

```python
# analyze_results.py
import json, csv
from collections import Counter

with open("experiment_florence_results.json") as f:
    results = json.load(f)

rows = []
for r in results:
    row = {
        "image": r["image"],
        "cv_fish_count": r["opencv"].get("fish_returns", {}).get("count", 0),
        "cv_bottom_type": r["opencv"].get("bottom_type"),
        "cv_bottom_depth": r["opencv"].get("bottom_depth_fm"),
        "cv_time": r["opencv_time_s"],
        "vl_depth": r["florence_prompt_d"].get("depth"),
        "vl_bottom_type": r["florence_prompt_d"].get("bottom_type"),
        "vl_fish": r["florence_prompt_d"].get("fish_detected"),
        "vl_time": r["florence_prompt_d_time_s"],
        "vl_prompt_a": r["florence_prompt_a_raw"],
        "vl_prompt_a_time": r["florence_prompt_a_time_s"],
        "gt_depth": r["ground_truth"].get("depth_fm"),
        "gt_bottom_type": r["ground_truth"].get("bottom_type"),
        "gt_fish_present": r["ground_truth"].get("fish_present"),
    }
    rows.append(row)

# CSV output
with open("experiment_florence_analysis.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

# Summary stats
fish_correct_cv = sum(1 for r in results
    if r["opencv"]["fish_returns"] and r["ground_truth"].get("fish_present", False))
fish_correct_vl = sum(1 for r in results
    if r["florence_prompt_d"].get("fish_detected") and r["ground_truth"].get("fish_present", False))

print(f"Fish detection accuracy (CV): {fish_correct_cv}/{len(results)}")
print(f"Fish detection accuracy (VL): {fish_correct_vl}/{len(results)}")
print(f"Avg CV time: {sum(r['opencv_time_s'] for r in results)/len(results):.3f}s")
print(f"Avg VL time: {sum(r['florence_prompt_d_time_s'] for r in results)/len(results):.3f}s")

# Bottom type agreement
type_agreement = sum(1 for r in results
    if r["florence_prompt_d"].get("bottom_type") == r["opencv"].get("bottom_type"))
print(f"Bottom type agreement (VL vs CV): {type_agreement}/{len(results)}")
```

---

## Prompt Design Notes

### Why These Prompts Work

Florence-2 uses task prefixes that control the output format:

| Prefix | Behavior | When to Use |
|--------|----------|-------------|
| `<CAPTION>` | Free-form natural language description | Good for open-ended questions, binary yes/no |
| `<DETAILED_CAPTION>` | Longer, more detailed description | May produce more verbose output; good for reasoning |
| `<OD>` | Object detection format (bounding boxes) | Potential for locating fish arches spatially |
| `<OCR>` | OCR-specific output | For depth scale numbers |
| `<REGION_TO_OD>` | Gets objects within a specified region | Useful for focusing on bottom band only |

**Note:** `<OD>` and `<OCR>` are actual Florence-2 task prefixes from its training. `<DETAILED_CAPTION>` often gives better structured descriptions than plain `<CAPTION>` for sonar analysis.

### Prompt Best Practices for Sonar Images

1. **Reference the blue palette explicitly** — helps Florence-2 interpret the color mapping: *"In this sonar image, blue means weak return, red means strong return"*
2. **Ask for depths in relative terms** — *"at what fraction of the screen depth"* rather than meters
3. **Use domain terms** — *"fish arches", "bottom return band", "thermocline", "surface clutter"* trigger relevant learned patterns
4. **Limit token count** — `max_new_tokens=100` is usually enough for structured answers; 200 for detailed descriptions

---

## Expected Outcomes

### Most Likely
1. **Fish detection (Task 1):** Florence-2 will beat OpenCV on images with clear spatial patterns (single arches, dense schools) but may struggle on scattered weak returns. Expected F1: 0.75-0.90 vs OpenCV 0.55-0.80.
2. **Bottom type (Task 2):** Florence-2 will roughly match OpenCV on clear cases but may hallucinate on ambiguous returns. The VL can describe texture but doesn't truly "see" it — it's guessing from color patterns.
3. **Depth numbers (Task 3):** Florence-2 will likely fail or be unreliable on small 10-15px digits at 370px image width. Tesseract in the `DEPTH_SCALE_X` crop will be better. **Do not rely on VL for OCR.**
4. **Speed (Task 4):** CUDA inference will be 2-4s per image, which is acceptable for 30s sounder cadence but not for real-time (fish finders refresh at ~1-3 Hz).

### Showstoppers (stop experiment if hit)
- VRAM allocation failure during inference (OOM)
- Florence-2 hallucinating fish in every image
- Inference time >10s on GPU
- Model returning empty/truncated output for all prompts

### Verdict Template

```
FLORENCE-2 VERDICT: [VIABLE / PARTIAL / NOT WORTH IT]

Fish detection:     [BETTER / MATCH / WORSE] than OpenCV (F1 scores)
Bottom type:        [BETTER / MATCH / WORSE] than OpenCV
Depth numbers:      [USABLE / UNRELIABLE / FAIL] — [F1/accuracy score]
Speed:              [FAST / ACCEPTABLE / TOO SLOW] — avg [X.X]s per image

Recommendation:
- Replace pixel thresholds with VL for: __________________
- Keep pixel approach for: _______________________________
- Hybrid approach (VL + fallback): _______________________
```

---

## Files to Create During Experiment

| File | Purpose |
|------|---------|
| `experiment_florence_ground_truth.json` | Human annotations for all test images |
| `experiment_florence_results.json` | Raw experiment output (all prompt variants × all images) |
| `experiment_florence_analysis.csv` | Scored comparison table |
| `experiment_florence_verdict.txt` | Final decision |

---

## Appendix: Potential Prompt Variations

If time permits, test these additional variations:

```python
# Fish arch detection with OD prefix — may produce bounding boxes
inputs = _processor(
    text="<OD>Locate fish arches in this sonar image. Output as bounding boxes.",
    images=img, return_tensors="pt"
).to(_device)

# Detailed caption — usually more verbose
inputs = _processor(
    text="<DETAILED_CAPTION>",
    images=img, return_tensors="pt"
).to(_device)

# Zero-shot QA — frame the sounder as a scene description
inputs = _processor(
    text="<CAPTION>Describe what a fishfinder operator would see looking at this display.",
    images=img, return_tensors="pt"
).to(_device)
```

---

## Quick-Start Checklist

```
□ 1. Annotate ground truth for all sounder images
□ 2. Create run_experiment.py from skeleton above
□ 3. Verify Florence-2 loads on CUDA (expect ~500 MB VRAM)
□ 4. Run Task 1 — Fish detection (all prompt variants)
□ 5. Run Task 2 — Bottom type classification
□ 6. Run Task 3 — Depth scale OCR
□ 7. Run Task 4 — Speed benchmark (5× per image per variant)
□ 8. Run analyze_results.py to generate comparison table
□ 9. Write verdict
□ 10. Review VRAM peak usage and model endurance
```
