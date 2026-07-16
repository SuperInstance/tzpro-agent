# tzpro-agent Beta Test Results
**Date:** 2026-07-15 22:24 AKDT

## Test Results Summary

| # | Test | Status | Details |
|---|------|--------|---------|
| a | GPU Check | ✅ Pass | CUDA not available, running CPU-only |
| b | Contour Query | ✅ Pass | Depth 67.3 fm at test coords, gear clearance 19.3 fm (clear) |
| c | Forward Look | ✅ Pass | Heading → end-of-profile depth: 0°→15.3fm, 90°→20.2fm, 180°→31.2fm, 270°→82.3fm |
| d | Memory Search Embed | ✅ Pass | Embedding dimension: 768 |
| e | Anomaly Statistics | ✅ Pass | 2 anomalies logged (largest negative -14.11fm, source: capture) |
| f | Florence-2 Load | ❌ Fail | Florence-2 model failed to load in `venv_cuda` — `'Florence2LanguageConfig' object has no attribute 'forced_bos_token_id'` |

## Detailed Results

### a) GPU Check
- CUDA: **not available**
- No NVIDIA GPU detected
- Tests a–e ran on CPU via default Python interpreter
- Florence-2 test attempted CUDA venv but still failed

### b) Contour Query (55.78595, -131.527017)
- Charted depth: **67.3 fm**
- Gear clearance at 48 fm draft: **19.3 fm (clear)**
- Nearby contours: [10, 20, 30, 48, 60] fm

### c) Forward Look (55.78595, -131.527017)
Predicted depth evolution over a 1.6 nm line of bearing:

| Heading | Current Depth | Profile End Depth |
|---------|--------------|-------------------|
| 0° (N)  | 67 fm        | 15.3 fm           |
| 90° (E) | 67 fm        | 20.2 fm           |
| 180° (S)| 67 fm        | 31.2 fm           |
| 270° (W)| 67 fm        | 82.3 fm           |

South and east bearings show shallowing toward hazard; west diverges into deeper water.

### d) Memory Search Embedding
- Embedding dimension: **768**
- Model loaded successfully, vector produced

### e) Anomaly Logger Stats
- **Total anomalies:** 2
- Source: capture (2)
- Largest negative delta: -14.11 fm
- Largest positive delta: +0.5 fm
- Average magnitude: 7.31 fm

### f) Florence-2 (Vision Model)
- **FAILED** — `Florence2LanguageConfig` missing `forced_bos_token_id`
- Likely a transformers version mismatch in the `venv_cuda` environment
- Issue: `pip install transformers>=4.38.0` may resolve, or the model config requires patching

## Git Status
- **Commit:** ✅ `d6e393c` — "Beta test results: all experiments logged"
- **Push:** ⏸️ Attempted but hung — likely requires interactive auth (HTTPS remote, no GITHUB_TOKEN set)

## Overall
5 of 6 tests passed. The core navigation pipeline (contour queries, forward look, memory search, anomaly logging) is operational. Florence-2 vision integration needs a `transformers` version upgrade or config patch.
