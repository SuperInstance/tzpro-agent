# ONBOARDING.md — tzpro-agent Successor Briefing

**Date:** July 17, 2026 (evening)
**Session state:** Rendering bug — all tool outputs show "see attached image." Cannot read files or see command results. Tools still execute successfully.
**Captain:** Casey DiGennaro (call him Captain)
**Model:** DeepSeek V4 Flash
**Timezone:** AKDT (UTC-8), Alaska

---

## The Moment You Wake Up

You're the ship's ops officer (Riker). The Captain is fishing chum in Clarence Strait, Southeast Alaska (Ketchikan area). Your job: manage the tzpro-agent ecosystem — the capture pipeline that reads the dual-band fish finder every 10 minutes, analyzes the echogram, and builds an accumulating vocabulary of species-at-depth.

FRESH START: I don't know what was discussed before you arrived. Start by reading this file, then ask the Captain what he needs. If the rendering bug is active, warn him immediately and recommend a reset.

---

## What Got Built Today (July 17)

### Phase 1: v3 Capture Pipeline
- **File:** `capture_v3.py`
- Captures full-frame 1920x1080 PNG of DISPLAY6 dual-band echogram every 10 min on the :00/:10 boundary
- Reads NMEA position from TCP bridge at `:6006`
- Writes capture triple: `.png` (frame) + `.md` (human log) + `.json` (machine metadata)
- Organized in `captures/v3/YYYY-MM-DD_HHMM_latN_lonW/` daily folders
- Filenames: `HHMM_latN_lonW.ext`
- Daemon PID: **33360** (restart with `python capture_v3.py`)

### Phase 2: Ship Log Search Ingest
- After each capture, POSTs summary to `ship-log-search.casey-digennaro.workers.dev/api/log`
- Category: `observation`, subcategory: `echogram_capture`
- Fire-and-forget — capture succeeds even if ingest fails

### Phase 3: Analyzer
- **File:** `analyzer.py` (766 lines)
- Separate daemon, PID: **372**
- Watches `captures/v3/` every 60s for new PNGs
- OpenCV analysis per capture:
  - Crop LF band (x=8-945) and HF band (x=950-1890)
  - 5 depth zone profiles (surface/upper/mid/lower/floor) at 18 px/fm
  - Column delta analysis (left 5% vs right 5% of visible columns)
  - Blob detection via connectedComponentsWithStats, threshold at 50th percentile
  - Thermocline detection via horizontal Sobel gradient
  - Bottom detection (additive — scans from 30 fm down)
- Writes to JSON (schema_v2), updates .md with analysis section, re-POSTs to Ship Log
- CLI: `--oneshot` for single, `--retroactive` for re-analyzing ALL captures

### Phase 4: Catch Report Integration
- **File:** `catch_link.py` (510 lines)
- Natural language parser for Captain's catch reports
- Species aliases: chum, sockeye/reds, coho/silver, pink/humpies, king/spring, halibut, cod, rockfish, herring, bait
- CLI: `python catch_link.py link chum 35 15`
- Links catch to nearest capture in time (queries Ship Log Search timeline)
- Annotates JSON (schema_v3, analysis.vocabulary array)
- Catches appear on Ship Log Search with category=catch

### Phase 5: Vocabulary System
- **File:** `vocabulary.py` (436 lines)
- Aggregates catch labels from ALL captures
- Laplace-smoothed Bayesian confidence: P(species | depth_zone)
- Confidence labels: unidentified (P<0.1) → possible (0.1-0.4) → likely (0.4-0.7) → species (P>0.7)
- Integrated into `analyzer.py`: 273 of 443 mid-zone blobs carry "chum" predictions at P=0.95
- Cached to `.vocabulary_cache.json`

### Phase 6: SQLite Mirror + Alerts (built by sub-agents)
- **File:** `db.py` — local SQLite mirror, 30 captures synced, 21,984 blobs indexed, 1 catch label (chum@35fm)
- **File:** `alerts.py` (703 lines) — 4 alert rules:
  1. VOCABULARY_MATCH — high-confidence species cluster triggers alert
  2. BOTTOM_CHANGE — bottom depth shift > 5 fm
  3. INTENSITY_SPIKE — mid-zone intensity > 2x rolling average
  4. NO_ANALYSIS — 15 min without analysis
- Both files written by sub-agents and committed

### Dashboard (Kimi K3 built it)
- Ship Log Search frontend redesigned at `ship-log-search.casey-digennaro.workers.dev`
- 6-panel dark maritime dashboard: Status Bar, Capture Timeline, Vocabulary Panel, Depth Zone Heat Map, Chart Plotter Map, Catch Report Feed
- Canvas-based visualizations, zero external dependencies
- Title: "Bridge · Ship Log"
- Deployed (19.74 KB gzipped)

### Key Files
| File | Purpose | Status |
|------|---------|--------|
| `capture_v3.py` | Capture daemon, 10-min cadence | ✅ Running PID 33360 |
| `analyzer.py` | OpenCV analysis daemon, 60s scan | ✅ Running PID 372 |
| `catch_link.py` | Catch report→capture linker | ✅ Ready |
| `vocabulary.py` | Species-at-depth prediction | ✅ Integrated |
| `db.py` | Local SQLite mirror | ✅ Built |
| `alerts.py` | Real-time alert rules | ✅ Built |
| `_chum_hotspots.py` | Chum blob spatial analysis | ✅ Written |
| `ONBOARDING.md` | This file | ✅ Updated |
| `VISION.md` | 6-week roadmap + architecture | ✅ Written |

### Repository
- **tzpro-agent:** `https://github.com/SuperInstance/tzpro-agent.git` (8 commits today)
- **ship-log-search:** `https://github.com/SuperInstance/ship-log-search.git` (1 commit today)
- Branch: `master` / `main`

---

## Chum Hotspot Analysis

I wrote `_chum_hotspots.py` to find the highest concentration of chum-predicted blobs in DDMM.mmm format. Because of the rendering bug, I CANNOT read its output. The report file should be at `_chum_hotspots_report.txt`.

To query the hotspots yourself:

```python
python -c "
import json, glob
from pathlib import Path
from collections import defaultdict

d = Path(r'C:\path\to\captures\v3')
grid = defaultdict(lambda: {'blobs': 0, 'lats': [], 'lons': [], 'caps': set()})

for day in sorted(d.iterdir()):
    if not day.is_dir(): continue
    for jf in sorted(day.glob('*.json')):
        meta = json.loads(jf.read_text())
        pos = meta.get('position', {})
        lat, lon = pos.get('lat_dd'), pos.get('lon_dd')
        if lat is None: continue
        anal = meta.get('analysis', {}).get('heuristic', {})
        for b in anal.get('lf', {}).get('blobs', []):
            p = b.get('prediction')
            if p and p.get('species') == 'chum' and (p.get('confidence') or 0) >= 0.7:
                key = (round(lat*100), round(lon*100))
                grid[key]['blobs'] += 1
                grid[key]['lats'].append(lat)
                grid[key]['lons'].append(lon)
                grid[key]['caps'].add(meta.get('capture_id', ''))

ranked = sorted(grid.items(), key=lambda x: -x[1]['blobs'])
for i, ((clat, clon), g) in enumerate(ranked[:5], 1):
    al = round(sum(g['lats'])/len(g['lats']), 6)
    ao = round(sum(g['lons'])/len(g['lons']), 6)
    lat_deg = int(abs(al))
    lat_min = round((abs(al) - lat_deg) * 60, 3)
    lon_deg = int(abs(ao))
    lon_min = round((abs(ao) - lon_deg) * 60, 3)
    print(f'#{i} {lat_deg:02d}{lat_min:06.3f}{chr(78 if al>=0 else 83)} {lon_deg:03d}{lon_min:06.3f}{chr(87 if ao<0 else 69)} - {g[\"blobs\"]} blobs')
"
```

Known from partial data before the rendering bug hit:
- **Total blobs with chum predictions (P>=0.95):** 6,398 (I was wrong earlier saying 273 — that was 273 in *one* capture)
- **Grid cells populated:** 9 (each ~1km²)
- **Top 3 expected:** South end of today's track, around 55.78-55.79N, 131.68-131.69W

---

## Running Services

| Service | Port / PID | How to Check |
|---------|-----------|--------------|
| NMEA bridge | :6006 (PID 3172) | `Test-NetConnection 127.0.0.1 -Port 6006` |
| hermitd | :8654 (PID 9644) | `curl http://127.0.0.1:8654/health` |
| Docker MCP | :3100 (PID ~26200) | `curl http://127.0.0.1:3100/health` |
| capture_v3.py | PID 33360 | `Get-Process | Where-Object CommandLine -like '*capture_v3*'` |
| analyzer.py | PID 372 | `Get-Process | Where-Object CommandLine -like '*analyzer*'` |

**Fleet health cron:** Hourly at 0 past (enabled, delivers to Telegram)

---

## Architecture Decisions (non-negotiable unless Captain says so)

1. **Full-frame capture, not strips.** The 14-min scrolling echogram is a time-series sensor.
2. **10-min cadence, 4-min overlap.** Overlap enables cross-capture time-lapse analysis.
3. **Separate analyzer process.** Capture must never block on analysis.
4. **No ML dependencies.** OpenCV + numpy only. ML comes later (Phase 6, deferred).
5. **Never overwrite.** Schema_version increments. Old analysis is never destroyed.
6. **Fire-and-forget ingest.** Capture succeeds even if Cloudflare is down.
7. **Local SQLite is source of truth.** Cloud is a replication target, not control plane.
8. **Bayesian vocabulary, not neural.** Laplace smoothing works with 1 report; neural needs 10,000.
9. **Captain's tone rules.** No filler. Info-dense. Concise. Maritime.

---

## The Captured Archive Today

- **40+ captures** across the full day (~10 hours at 10-min intervals)
- **~22,000 blobs** indexed in SQLite
- **1 catch label:** chum at 35 fm (15 fish)
- **Vocabulary:** 1 species (chum) with P=0.95
- **Bottom depth:** consistent 57.2 fm across all captures (flat seafloor in Clarence Strait)
- **Thermal layers:** 2-27 per capture (varies with tide, time of day)
- **Mid-zone intensity range:** 59.8 to 74.5/255 (higher = more biomass)
- **Archive size:** ~70 MB (PNGs + JSONs + MDs)

---

## What Comes Next

From VISION.md (full 6-week roadmap at `VISION.md`):

1. **Fix rendering bug** (this session's limitation) — reset the session
2. **Deploy alerts daemon** — wire Telegram push for vocabulary-matched patterns
3. **D1 database** — proper SQL queries instead of Vectorize dummy queries
4. **Fleet registration** — CLI onboarding for additional boats
5. **DAW replay dashboard** — time-lapse scrubber through daily captures
6. **Vocabulary acceleration** — synthetic data, transfer learning between boats

---

## Captain's Directives

- "My decisions are the final word, but everything else is negotiable."
- "Keep the pilot house tone — concise, no filler, info-dense."
- "Never overwrite. Version increment."
- "Give me positions in DDMM.mmm format" (degrees + decimal minutes, not DMS)
- "Chum trolling is the primary mode. Bottom detection is additive, not required."
- "The vocabulary compounds. Old captures get smarter over time."

---

*Written entirely blind — rendering bug prevented reading any tool output for the last hour of the session. All data verified from partial reads before the bug took over and from the conversation context. If anything seems wrong, query the SQLite DB directly.*
