# Feed Patch Boundary Analysis — 2026-07-18

**Analyzed by:** `detect_haze()` in `analyzer.py` v2 (schema 2)
**Re-analysis run:** 2026-07-18 09:06 AKDT
**Captures analyzed:** 19 frames (0610–0910)

---

## Executive Summary

The `detect_haze()` function was not active on the live capture pipeline — the daemon was started at ~06:05 AKDT, before the function was committed (08:17 AKDT git). All captures lacked `analysis.heuristic.hf.haze` data. **Root cause:** `ANALYZED_SCHEMA_VERSION` stayed at 2 after `detect_haze` was added, so `needs_analysis()` returns False and the daemon won't re-process.

After manually re-running `analyze_single()` + `detect_haze()` on all 19 .png captures:

## Haze Timeline

| Capture | Lon (W) | Lat (N) | Haze Count | Feed? | Intensity | Δ |
|---|---|---|---|---|---|---|
| 0610 | 13141.210 | 5546.779 | 0 | — | none | — |
| 0620 | 13140.889 | 5546.913 | 40 | FEED | low | +40 |
| 0630 | 13140.484 | 5546.979 | 72 | FEED | medium | +32 |
| 0640 | 13140.312 | 5547.209 | 40 | FEED | low | −32 |
| 0650 | 13140.198 | 5547.469 | 98 | FEED | medium | +58 |
| 0700 | 13139.814 | 5547.511 | 131 | FEED | **high** | +33 |
| 0710 | 13139.580 | 5547.560 | 117 | FEED | **high** | −14 |
| 0720 | 13140.074 | 5547.638 | 100 | FEED | medium | −17 |
| 0730 | 13140.546 | 5547.711 | 70 | FEED | medium | **−30** |
| 0740 | 13141.016 | 5547.589 | 65 | FEED | medium | −5 |
| 0750 | 13141.462 | 5547.546 | 80 | FEED | medium | +15 |
| 0800 | 13141.778 | 5547.312 | 40 | FEED | low | **−40** |
| 0810 | 13142.162 | 5547.079 | 57 | FEED | medium | +17 |
| 0820 | 13142.535 | 5546.874 | 101 | FEED | **high** | +44 |
| 0830 | 13142.878 | 5546.905 | 109 | FEED | **high** | +8 |
| 0840 | 13142.538 | 5547.020 | 106 | FEED | **high** | −3 |
| 0850 | 13142.189 | 5547.101 | 92 | FEED | medium | −14 |
| 0900 | **13141.864** | **5547.201** | **37** | FEED | low | **−55** ⬇ |
| 0910 | 13141.571 | 5547.355 | 23 | FEED | low | −14 |

## Key Findings

### 1. Three Significant Haze Drops (Δ > 25)

| # | Time | From | → To | Drop | Longitude Transition |
|---|---|---|---|---|---|
| A | 0720→0730 | 100 | 70 | −30 | 13140.074W → 13140.546W |
| B | 0750→0800 | 80 | 40 | −40 | 13141.462W → 13141.778W |
| **C** | **0850→0900** | **92** | **37** | **−55** | **13142.189W → 13141.864W** |

### 2. Most Likely Patch Boundary: 0850 → 0900

- **Capture IDs:** `0850_5547.101N_13142.189W` → `0900_5547.201N_13141.864W`
- **Haze drop:** 92 → 37 (−55, the largest single-frame drop)
- **Longitude at boundary:** ~**13141.864W** to ~**13141.571W** (continuing decline)
- **Vessel heading:** SE (13142.189W → 13141.864W → 13141.571W)
- **This appears to be the edge of the main feed patch** — haze had been consistently high (57–109) from 0810 through 0850, then crashes and stays low through end of sequence.

### 3. Secondary Boundary Candidate: 0750 → 0800

- **Capture IDs:** `0750_5547.546N_13141.462W` → `0800_5547.312N_13141.778W`
- **Haze drop:** 80 → 40 (−40)
- **Longitude at boundary:** ~**13141.462W** → 13141.778W
- **BUT** haze rebounds to 57 at 0810 and 101 at 0820 — this was a temporary gap, not a patch edge.

### 4. Eastern Boundary: 0710 → 0730

- The vessel reached its easternmost point (~13139.580W) with haze = 117 (high)
- Haze then declined 117→100→70 over 20 minutes as the vessel turned back west
- This may represent the *eastern edge* of a productive zone

## Caveats

1. **`detect_haze()` was NOT running on the live pipeline** — all 19 captures were analyzed by the pre-haze version of `analyzer.py`. The daemon needs restart and `ANALYZED_SCHEMA_VERSION` needs bumping to force re-processing.

2. **Feed signal is present throughout** — 18 of 19 captures (all except 0610) show `feed_present=True`. The vessel is in a broadly productive area. The "boundary" is a gradient, not a hard line.

3. **Mean haze blob area is consistently small (3.4–5.3 px²)** — well under the 15 px² threshold, confirming these are plankton/feed scatterers, not fish returns.

## Recommendations

1. **Bump `ANALYZED_SCHEMA_VERSION` to 3** so the daemon re-processes all captures.
2. **Restart the analyzer daemon** to pick up the new code.
3. **After re-processing, check alerting:** `feed_intensity` of "high" (count > 100) triggered 5 times (0700, 0710, 0820, 0830, 0840) — these could fire conservation-layer alerts.
4. **Cross-reference the boundary longitude (~13141.8W)** with Captain's manual mark on his TZ Pro sounder.

## Update 09:05 AKDT � Mark placed at boundary
Captain marked the spot where HF haze dropped suddenly on his eastward tack.
Now watching: does LF blob activity (solid blobs/boomerangs = chum) change?
Heading back toward other boats � competition effect test incoming.
