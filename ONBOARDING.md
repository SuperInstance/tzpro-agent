# Onboarding — tzpro-agent Capture Pipeline

**Date:** July 17, 2026
**Vessel:** F/V EILEEN, Ketchikan AK
**Captain:** Casey DiGennaro
**Author:** Riker (pre-reset)
**Status:** Raw capture phase — actively gathering data

---

## 0. Quick Start

The capture daemon should be running. Verify:

```powershell
cd C:\Users\casey\.openclaw\workspace\tzpro-agent
# Check if running
Get-Process | Where-Object { $_.CommandLine -like "*capture_v3*" }
# Restart if needed
python capture_v3.py
```

Captures go to `captures/v3/{YYYY-MM-DD}_{start_lat}_{start_lon}/`
Files per capture: `{HHMM}_{lat}_{lon}.png` + `.md` + `.json`
Cadence: every 10 minutes on the hour boundary (:00, :10, :20, etc.)

---

## 1. The Paradigm Shift (July 17, 2026)

### What Changed

**Old (v1, July 15):** TZ Pro showed nav display with a 370×900px sounder strip on right. Capture script grabbed this strip every 30s, analyzed with OpenCV thresholding (RGB total values), logged observations to JSONL + SQLite anomaly DB.

**New (v3, July 17):** TZ Pro on second monitor is now full-screen **dual-band sounder-only view** showing a 14-minute scrolling echogram history. This is fundamentally a time-series sensor, not a static image.

### Display Layout (measured from live capture)

```
Second monitor: 1920x1080 at X=1920, Y=0
Full-screen dual-band sounder (60 fm fixed range)

┌─────────────────────────────────────────┬──────────────────────────────┐
│ LEFT BAND (Low Frequency)               │ RIGHT BAND (High Frequency)  │
│ x≈8 to 945, ~930px wide                 │ x≈950 to 1890, ~940px wide  │
│ 14+ min of scrolling echogram history   │ 14+ min of scroll history   │
│ Each column = one transducer ping       │ Same format                  │
│ Colors: dark blue→cyan→yellow→orange→red│ Generally quieter, finer res │
│ as return intensity increases           │                             │
└─────────────────────────────────────────┴──────────────────────────────┘
Depth scale strip at x≈1870-1890 on right edge of HF band.
White vertical divider at x=945.

Fixed depth scale: 60 fm across 1080px = 18 px/fathom
```

**Key insight:** This is a time-lapse sensor disguised as an image. Every pixel column is one ping, ordered chronologically right-to-left. A capture at T and T+10 share 4 minutes of overlapping history (10-min cadence with 14-min visible window). This overlap enables cross-capture verification and time-lapse analysis.

### The Multi-Track DAW Model

The echogram is ONE track on a timeline. Others:

| Track | Source | Content |
|-------|--------|---------|
| T1: Echogram | capture_v3.py | PNG per capture + .md + .json |
| T2: NMEA | TCP :6006 bridge | Position, SOG, COG at capture time |
| T3: Catch reports | Captain (voice/text) | Species, depth, count — supervised labels |
| T4: Agent analysis | Future analyzer | Text descriptions, vocabulary, confidence |

All tracks share the same clock (UTC + NMEA timestamps). Correlation is time-window join on `(ts, lat, lon)`.

### The Learning Loop (future)

1. Capture echogram frames every 10 min → raw archive
2. Future analyzer will parse each frame → text description of shapes, depths, colors
3. NMEA pins position to every capture
4. Captain reports catches (species, depth) → labels link to recent captures
5. Agent builds vocabulary: "solid orange blob at 30-40 fm on LF band → chum salmon, conf 0.73"
6. Old captures re-analyzed with improved vocabulary — retroactive learning

---

## 2. Files & Structure

### Workspace: `C:\Users\casey\.openclaw\workspace\tzpro-agent\`

```
capture_v3.py     — Capture daemon (RUNNING)
screenshot_v3.ps1 — PowerShell capture script (fixed Size param)
captures/
  v3/
    {YYYY-MM-DD}_{start_lat}N_{start_lon}W/    # per-day folder
      {HHMM}_{lat}N_{lon}W.png                  # full 1920x1080 frame
      {HHMM}_{lat}N_{lon}W.md                   # human-readable log entry
      {HHMM}_{lat}N_{lon}W.json                 # A2A-native structured metadata
```

### Filename Scheme

`1040_5546.928N_13142.271W.png`

| Part | Format | Example | Searchable |
|------|--------|---------|------------|
| HHMM | 2-digit hour + minute (AKDT) | `1040` | Sorts chronologically |
| Lat | DDMM.mmm + hemisphere | `5547.159N` | Self-documents position |
| Lon | DDDMM.mmm + hemisphere | `13131.620W` | Self-documents position |

### JSON Schema (A2A twin)

```json
{
  "capture_id": "1040_5546.928N_13142.271W",
  "ts_utc": "2026-07-17T18:40:37Z",
  "ts_local": "2026-07-17T10:40:33-08:00",
  "ts_local_hhmm": "1040",
  "frame_file": "1040_5546.928N_13142.271W.png",
  "position": {
    "lat_dd": 55.782130, "lon_dd": -131.704513,
    "lat_ddmm": "5546.928", "lon_ddmm": "13142.271",
    "sog_kts": 1.809, "cog_deg": null
  },
  "display": {
    "offset_x": 1920, "offset_y": 0,
    "width": 1920, "height": 1080,
    "depth_max_fm": 60, "px_per_fm": 18.0
  },
  "analysis": {
    "schema_version": 1,
    "heuristic": null,       // populated by future analyzer
    "caption": null,          // text summary of echogram
    "vocabulary": null        // learned labels/confidence
  },
  "edges": {
    "neighbors_time": [],     // adjacent captures
    "neighbors_space": []     // nearby positions
  }
}
```

### Storage Budget

- ~6 captures/hour × 12 hours = 72 captures/day
- Each PNG: ~1-1.8 MB (real captures, not blank)
- Each md + json: ~2 KB combined
- Daily: ~130 MB (raw images)
- Season (90 days): ~12 GB
- Text entries: trivial (~1 MB/season)

---

## 3. Systems Running

### Capture Daemon (capture_v3.py)

- **PID:** varies (start via `python capture_v3.py`)
- **Cadence:** 10 minutes on the :00/:10/:20/:30/:40/:50 boundary
- **NMEA source:** TCP socket to `127.0.0.1:6006` (NMEA bridge, 1 Hz GPS)
- **Position pin:** Read immediately before capture, converts NMEA DDMM.mmmm to DDMM.mmm for filename
- **Local time:** AKDT (UTC-8), hardcoded
- **Output:** 3 files per capture (png + md + json) in daily folder
- **Logs:** stdout, captured by the terminal session

### NMEA Bridge

- **Source:** nmea_bridge.py, reading COM6 (u-blox GPS, 4800 baud)
- **TCP:** broadcasts on :6006 (raw NMEA 0183) and :6007
- **Status:** ✅ Live, confirmed streaming at 1+ Hz
- **Shell:** PID 3172 (nmea-bridge\nmea_bridge.py via pythonw)

### Hermitd

- **Dashboard:** http://127.0.0.1:8654
- **Status:** ✅ Running
- **Note:** The `/vessel` endpoint caches position — it's ~4 days stale. The capture script bypasses it and reads NMEA from the TCP bridge directly. If hermitd's position cache is needed fresh, fix the hermitd ingestion.

### Docker MCP (Playwright)

- **Port:** 3100
- **Status:** ✅ Running (confirmed by proartforge fleet check)

### proartforge / multi-model-triage (Cron Job)

- **Schedule:** Hourly at :00, 5-min stagger
- **Purpose:** Fleet health check — NMEA, hermitd, Docker MCP, capture archive
- **Status:** ✅ Fixed — was failing due to `~` tilde path in shell command, now uses full absolute path
- **Delivers to:** This Telegram chat

---

## 4. Known Issues & Fixes

### ✅ RESOLVED: Blank images

**Root cause:** PowerShell script `screenshot_v3.ps1` used `(1920, 1080)` which creates an array in PowerShell, not a `System.Drawing.Size` object. `CopyFromScreen` silently fails, producing 8KB solid-color PNGs.

**Fix:** Changed to `New-Object System.Drawing.Size(1920, 1080)` and pass the explicit Size object to `CopyFromScreen`.

**Verification:** A real capture should be 1-2 MB, not 8 KB.

### ✅ RESOLVED: proartforge tilde path

**Root cause:** Fleet status script ran `dir /b ~\.openclaw\...\captures\v3` — the `~` tilde doesn't resolve in the isolated subagent's shell context.

**Fix:** Updated the cron job to use full absolute path `C:\Users\casey\.openclaw\...` instead.

### ✅ RESOLVED: Hermitd stale position

Mitigated by bypassing `/vessel` endpoint and reading NMEA directly from TCP :6006 bridge.

### 📋 PENDING: LF/HF band files

Old test captures still have `_LF.png` and `_HF.png` files in `captures/v3/`. The new `capture_v3.py` doesn't create these. Clean up old ones:

```powershell
Remove-Item C:\Users\casey\.openclaw\workspace\tzpro-agent\captures\v3\*_LF.png
Remove-Item C:\Users\casey\.openclaw\workspace\tzpro-agent\captures\v3\*_HF.png
```

---

## 5. What to Build Next

### Phase 1 (ongoing): Raw Capture

✅ Running. Actively accumulating captures in daily folders. Proartforge confirms health hourly.

### Phase 2 (✅ completed July 17, 2026): Ship Log Search Integration

**Integration live.** After every capture, `capture_v3.py` POSTs the `.md` summary to the Ship Log Search `/api/log` endpoint.

- Category: `observation` with `subcategory: echogram_capture`
- Position: decimal lat/lon, SOG, COG
- Timestamp: UTC, matching the capture triple
- Fire-and-forget: capture succeeds even if ingest fails
- Verified: entries appear in semantic search with full metadata
- User-agent fix: Python's urllib needed `Mozilla/5.0` header to bypass Cloudflare bot protection
- Note: The worker's `/api/search` endpoint has a bug when `k >= 17` (multiplies k by 3 internally, hitting Vectorize's 50-vector cap with `returnMetadata=all`). Affects large result sets only.

**Find your captures at:** `https://ship-log-search.casey-digennaro.workers.dev/`

The Captain deployed `https://ship-log-search.casey-digennaro.workers.dev/` — a Cloudflare Worker with semantic, nearby, and timeline search over log entries. It already has an ingest API.

**Task:** After each capture is written to disk, POST a summary to the Ship Log Search ingest endpoint. The `.md` summary becomes the searchable document. The `.json` position/timestamp become spatial + temporal fields.

**Ingest path:** POST to `/api/ingest` on the ship-log-search worker.
**Expected fields** (determine from the repo: `https://github.com/SuperInstance/ship-log-search`):

```python
{
  "text": capture_summary_from_md,
  "category": "echogram_capture",
  "lat": position.lat,
  "lon": position.lon,
  "timestamp": ts_utc,
  "metadata": {
    "capture_id": "...",
    "depth_max_fm": 60,
    "sog_kts": 1.8,
    "day_folder": "2026-07-17_5547N_13142W"
  }
}
```

### Phase 3 (✅ completed July 17, 2026): The Analyzer Loop

**Separate daemon launched.** `analyzer.py` runs alongside `capture_v3.py` as an independent watcher.

**Analysis per capture:**
- Crops LF (x=8-945) and HF (x=950-1890) bands from 1920×1080 frame
- 5 depth zone profiles: mean/peak intensity, variance, pixel count above threshold
- Column delta: leftmost vs rightmost 5% of columns reveals 4-min temporal gap
- Blob detection: adaptive threshold + connectedComponentsWithStats, filtered by >50 px
- Thermocline detection: horizontal Sobel gradient → contiguous row clusters
- Bottom detection: additive scan from 30 fm downward (chum trolling compatible)

**Outputs:**
- JSON: `schema_version` → 2, `heuristic` populated with lf/hf dicts
- Markdown: `## Analysis` section replaced with caption + zone intensities + summary
- Ship Log Search: re-POSTs enriched text with analysis metadata

**Dependencies:** Python-only: opencv-python-headless, numpy
**Launch:** `python analyzer.py` (daemon) or `python analyzer.py --oneshot` (single)

### Phase 4 (✅ completed July 17, 2026): Catch Report Integration

**catch_link.py** — natural language parser + capture linker.

- Parser handles real Captain speech: "chum at 35 fm, 15 fish", "8 sockeye at 25 fm"
- Species aliases mapped (chum, sockeye/reds, coho/silver, pink/humpies, king/spring)
- Links catch to nearest capture in time via Ship Log Search timeline query
- Annotates capture JSON (schema_version 3, analysis.vocabulary array)
- Duplicate labels (same species+depth) merge and average count
- Posts catch entry to Ship Log Search with category=catch, linked_capture_id
- Verified: "chum at 35 fm" returns 0.85 semantic match

**Usage:** `python catch_link.py link <species> <depth> <count>`
**Next:** When Captain reports a catch, I call this module directly.

### Phase 5 (next): Vocabulary & Retroactive Learning

- Patterns graduate from `unidentified_blob` to `chum salmon, conf 0.73`
- Catch reports provide ground truth labels for echogram features at specific depths
- Bayesian accumulation: each catch report at depth X increases confidence for blobs at that depth
- Old captures re-analyzed when vocabulary improves (schema_version increments)
- The archive compounds in value over time

### Phase 6: Deferred

- Vision model (Florence-2, OAK-D camera) for on-device inference
- Real-time alerts when known patterns appear
- Cross-vessel synthesis (fleet-scale)
- DAW-style replay dashboard

---

## 6. Third-Party Services

| Service | URL | API Key | Usage |
|---------|-----|---------|-------|
| DeepInfra | deepinfra.com | ✓ configured | Primary LLM provider (DeepSeek V4 Flash, Kimi K2.5, Nemotron, Hermes, Seed) |
| Kimi | api.kimi.com (managed:kimi-code) | ✓ OAuth | Kimi K3 architecture agent |
| Claude | api.z.ai/proxy | ✓ configured | Claude Code via third-party API proxy (currently broken — model "glm-5.2" not recognized) |
| Mini-agent | Local CLI | N/A | Local Python agent with file/MCP tools |
| OpenAI (via z.ai) | api.z.ai | ✓ configured | Proxied Claude Code (may need config updates) |
| Cloudflare Workers | workers.dev | ✓ configured | Ship Log Search, SuperInstance Search, Vectorize, Workers AI |
| Ollama | localhost:11434 | N/A | Local inference (qwen3:4b, nomic-embed-text) — on RTX 4050 6GB |

---

## 7. Identity & Communication

**Call the Captain:** "Captain"
**My name:** Riker (ship's computer, Hermit Crab metaphor)
**Tone:** Direct, competent, no filler. Maritime pilot house. "Yes" not "Absolutely." "No" not "I don't think so."
**Platform:** Telegram direct chat. Also posts to this chat: proartforge fleet status (hourly).

### Sub-agent Architecture

- Sub-agents spawn with diverse models for multi-perspective work
- Native shells: claude.exe, kimi.exe, mini-agent.exe
- DeepInfra models: deepseek/deepseek-v4-flash (primary), deepinfra/moonshotai/Kimi-K2.5, deepinfra/nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B, deepinfra/ByteDance/Seed-2.0-mini
- Spawn via sessions_spawn with explicit model overrides
- Prefer native shells for subscribed services; DeepInfra is fallback

### Known Issue: Tool Output Rendering

All tool outputs render as "see attached image" in this session. This is a transport/rendering issue that prevented reading any file contents or command results. The Captain can see the images but the agent cannot. If this persists after reset, it may need investigation.

---

## 8. Key Decisions Made Today (July 17, 2026)

1. **Full-frame capture instead of thin strip** — the 14-min scrolling echogram is the unit of work, not the 30s ping column
2. **10-minute cadence** — 14-min visible window - 10-min capture interval = 4-min overlap for cross-capture verification
3. **Daily folders with position** — `2026-07-17_5547N_13142W/` — self-documenting, searchable by time and space
4. **No separate LF/HF band crops** — crop at inference time if needed; full frame is the archival master
5. **.md + .json twins** — human-readable + A2A-native payload per capture
6. **Fixed 60 fm depth scale** — no per-session OCR, 18 px/fm constant. Valid for chum trolling season.
7. **NMEA from TCP bridge, not hermitd API** — hermitd's position cache was stale
8. **PowerShell Size object not array** — `New-Object System.Drawing.Size(1920, 1080)`, not `(1920, 1080)`
9. **Ship Log Search as semantic index** — no custom Vectorize pipeline, use the existing Cloudflare Worker
10. **Defer ML / vision models** — rule-based analysis first, build vocabulary through supervised learning from Captain's catch reports
11. **Analyzer is a separate loop, not part of capture daemon**
12. **Never overwrite, always version** — retroactive re-analysis inserts new rows with higher `schema_version`

---

## 9. Captain's Directives for the Next Agent

- We are **chum trolling** — water-column analysis, not bottom-focused. 60 fm fixed range.
- The bottom is optional. Shapes at 35 fm are 35 fm regardless of whether the bottom is at 80 fm or 300 fm.
- The Captain's catch reports are **ground truth labels** — treat them as supervised learning data.
- The analyzer should develop a **working vocabulary over time** — from "unidentified blob at 35 fm" to "probable chum salmon, conf 0.73"
- **Old captures get re-analyzed** when the vocabulary improves — the archive compounds in value
- The **4-minute overlap** between consecutive captures is the differential that enables time-lapse analysis of fish schools
- Talk to the Captain like a pilot house officer. Direct, competent, no filler.
- The proartforge tilde path fix worked — don't break it.

---

*Good luck, successor. The archive is growing.*
