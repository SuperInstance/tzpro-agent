# Integration Plan: VIAME + Echopype → tzpro-agent Pipeline

**Date:** 2026-07-18
**Pipeline:** `C:\Users\casey\.openclaw\workspace\tzpro-agent\`

---

## 1. VIAME — NOAA Marine CV Toolkit

**What it does:** VIAME (Video and Image Analytics for Multiple Environments) is an NOAA/Kitware toolkit purpose-built for marine species analytics. Object detection, tracking, image annotation, query-based search, image enhancement, multi-camera processing, rapid model training, and evaluation. Has both CLI pipeline framework (kwiver) and web platform (viame.kitware.com).

**Formats consumed/produced:**
- Input: Images (PNG/JPG/TIFF), video (mp4/avi), image sequences
- Output: Detection CSV with columns: `x, y, width, height, score, class_name, frame_number`
- Also supports KWIVER pipeline config files (.pipe), JSON detections
- Pre-trained fish models available (generic fish, specific species depending on training data)

**Integration surface with tzpro-agent:**
`capture_v3.py` → PNG frames → VIAME detector CLI → detection CSV → analyzer.py

The critical path: VIAME's `detector_dump` CLI takes a folder of images and produces a CSV of detections with confidence scores. Our analyzer.py already does blob detection on the same frames. VIAME would **augment** (not replace) the CV pipeline — its ML-based detections feed into vocabulary.py's Bayesian model alongside the opencv blob metrics.

**Concrete integration point:**

```python
# In a future vision_enhancer.py or within analyzer.py:
import subprocess, csv, os

def run_viame_detections(png_path: str) -> list[dict]:
    """Run VIAME detector on a single frame, return detections as dicts."""
    out_csv = png_path.replace('.png', '_viame.csv')
    cmd = [
        "viame_detector",           # CLI entry point (after conda install)
        "--input", png_path,
        "--output", out_csv,
        "--model", "fish_detector",  # pre-trained model name
        "--threshold", "0.3"
    ]
    subprocess.run(cmd, capture_output=True, timeout=120)
    results = []
    with open(out_csv) as f:
        for row in csv.DictReader(f):
            results.append({
                "species": row["class_name"],
                "confidence": float(row["score"]),
                "bbox": [int(row[c]) for c in ("x","y","width","height")],
            })
    return results
```

**Dependencies:**
- VIAME binary install (conda/pkg) — **~2.5 GB**
- Pre-trained model weights — separate download
- NVIDIA GPU highly recommended (CPU works, slow)

**Trade-offs:**
- + ML-based detection (finds fish our pixel blobs miss)
- + Confidence scores → direct feed into vocabulary Bayesian model
- - Heavy dependency (GB-scale)
- - Model may not be trained on Alaska species (chum, sockeye)
- - Real-time processing: GPU-needed for 10-min capture cadence

**Decision:** Install VIAME as an **optional enhancement** — the pixel pipeline runs without it. A `--with-viame` flag toggles the ML augment.

---

## 2. Echopype — Sonar Data Format Parser

**What it does:** Echopype (UW eScience) converts proprietary sonar formats into interoperable netCDF/Zarr. Supports Simrad EK60 (`.raw`), EK80 (`.raw`), Echosounder HAC (`.hac`), and others. Produces actual calibrated Sv (volume backscatter strength, dB re 1 m⁻¹) values — the physics, not just the rendered pixel colors.

**Formats consumed/produced:**
- Input: `.raw` (Simrad), `.hac`, `.bot`, `.idx` files
- Output: xarray Dataset → netCDF or Zarr
- Key variables: `Sv` (backscatter strength), `range` (depth), `frequency`, `ping_time`

**Integration surface with tzpro-agent:**
Currently tzpro-agent analyzes **screenshots** (PNG captures of the TZ Pro display). Echopype opens the door to **raw sonar data** — calibrated, multi-frequency, with actual Sv values. This is fundamentally more accurate than pixel analysis because:
- No display gamma/contrast/color mapping artifacts
- Full dynamic range (32-bit float vs 8-bit PNG)
- Multiple frequencies independently (LF/HF/EK80 broadband)
- Direct depth calibration (no pixel-to-fathom conversion)

**Concrete integration point:**

```python
# In a future raw_sonar_processor.py:
import echopype as ep

def analyze_raw_sv(raw_file: str, frequency_khz: int = 38) -> dict:
    """Load raw sonar file, compute Sv, extract depth-zone metrics."""
    ds = ep.open_raw(raw_file, sonar_model="EK80")  # xarray Dataset
    ds_sv = ep.calibrate.compute_Sv(ds)               # calibrated Sv
    
    # Mask to target frequency
    sv = ds_sv["Sv"].sel(frequency=frequency_khz, method="nearest")
    
    # Depth-binned intensity (analogous to analyzer.py zone profiles)
    mid_zone_sv = sv.sel(range=slice(20, 40))  # 20-40 m (convert to fm)
    
    return {
        "mean_sv_db": float(sv.mean().values),
        "mid_zone_sv": float(mid_zone_sv.mean().values),
        "ping_count": int(sv.sizes["ping_time"]),
    }
```

**Dependencies:**
- `echopype` (PyPI/conda) — **lightweight pure Python + xarray**
- `xarray`, `netCDF4`, `zarr` — standard scientific stack
- **No GPU needed**

**Trade-offs:**
- + Calibrated Sv values, not display pixels
- + xarray-native → integrate with pandas/vocabulary directly
- + Lightweight dependency
- - Requires raw sonar files (.raw/.hac), not just screenshots
- - TZ Pro may not expose raw files to filesystem
- - Different depth coordinate system (meters vs fathoms)

**Decision:** Echopype is **lower effort than VIAME** and provides **higher-value data** (physics vs pixels). Investigate whether TZ Pro records `.raw` files anywhere on EILEEN.

---

## Synthesis: Integration Priority

| Priority | Target | Effort | Value | Risk |
|----------|--------|--------|-------|------|
| **P1** | **Echopype raw parsing** | Low | High (calibrated Sv) | Medium (need raw files) |
| **P2** | **VIAME detection augment** | High (GB install) | Medium (ML augmentation) | Low (optional, non-blocking) |
| **P3** | **Both → unified vocabulary** | Medium | High | Medium |

### Most Impactful First Integration

**Echopype.** Install pip package (lightweight), check if TZ Pro writes .raw/.hac files, build a standalone processor that creates analytical tiers from raw sonar data. Run alongside pixel pipeline — compare Sv metrics vs pixel metrics for 3 captures to validate.

### Concrete Next Steps

1. **Search for raw sonar files:** `dir C:\ /s *.raw *.hac 2>nul` — check if TZ Pro stores raw sonar logs anywhere on disk. If yes, path is clear.

2. **If raw files exist:** Create `raw_sonar_processor.py` that:
   ```python
   # One-off script
   import echopype as ep
   ds = ep.open_raw(path_to_raw, sonar_model="EK80")
   ds_sv = ep.calibrate.compute_Sv(ds)
   # Save Sv mean per depth bin → integrate with vocabulary.py
   ```

3. **If raw files don't exist:** Install VIAME and create `viame_augment.py`:
   ```python
   # Callable from analyzer.py
   def augment_with_viame(png_path: str, existing_blobs: list) -> list:
       viame_results = run_viame_detections(png_path)
       return merge_blobs_and_ml(existing_blobs, viame_results)
   ```

### Technical Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| TZ Pro doesn't expose raw files | High | Check with Captain; may need TZ Pro add-on |
| VIAME fish model not trained on Alaska species | Medium | Can re-train on tzpro-agent captures (30 labeled images minimum) |
| Echopype frequency mismatch (TZ uses different freq) | Low | echopype handles arbitrary frequency labels |
| Both integrations add deploy complexity | Medium | Keep as optional plugins - core pipeline runs without them |

---

*After integration decision, update analyzer.py's `detect_blobs()` to accept augmentations as additive channels, and vocabulary.py to merge predictions from all sources with uncertainty-weighted averaging.*
