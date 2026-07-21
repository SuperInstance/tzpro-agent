# TZ Pro Agent — Your Boat's Digital Watchstander

> **New boat? Start at [FIRST_BOAT.md](FIRST_BOAT.md)** — 15 minutes to
> replaying your first day. Everything else in this repo is detail.

**Eyes on the sounder. Records what it sees. Learns your grounds. Tells you what changed.**

![Status](https://img.shields.io/badge/status-operational-green)
![Boat](https://img.shields.io/badge/boat-F/V%20EILEEN-blue)
![Location](https://img.shields.io/badge/home-Ketchikan%2C%20Alaska-8b4513)
![Built](https://img.shields.io/badge/first_cast-July%2015%2C%202026-ff6b35)

---

## TL;DR — What Does This Actually Do?

You know how you stare at the sounder all day, watching the bottom, watching for fish, noticing "huh, that spot used to be harder bottom" or "the thermocline sat deeper last week"? **This does that for you, automatically, every 30 seconds, and writes it down.**

Think of it like a **deckhand who never sleeps, never gets seasick, and takes perfect notes** — but instead of a notebook, it builds a searchable, queryable record of every pass over your grounds.

---

## The Problem It Solves

### What You Know (But Can't Prove)
- "That hump at 54°47' holds chum in July"
- "The bottom's softer now than it was three years ago"
- "When the tide pushes hard, the fish sit 5 fathoms deeper"
- "That rock pile at 48 fm — gear comes up clean on the north side"

### What You Lose
- Memory fades between seasons
- Crew turnover loses institutional knowledge
- "I think it was around here" isn't a waypoint
- Paper logbooks don't search, don't overlay, don't trend

### What This Gives You
| Before | After |
|--------|-------|
| "Good chum spot somewhere near that corner" | **55°47.312'N 131°41.778'W — 08:00 AKDT, July 18 — 557 fish returns at 31.9 fm, holding on 26 fm thermocline** |
| "Bottom feels different this year" | **Delta: -3.2 fm vs 2024 survey at this exact lat/lon. Bottom type shifted hard→soft.** |
| "Fish were deeper on the flood" | **Query: "Show me all chum detections on flood tide > 35 fm"** → 47 matches, avg depth 38.2 fm |
| "Wonder what that spot looked like last July" | **Type the coordinates. Get the echogram. Get the bottom type. Get the fish count.** |

---

## Real-World Example: A Day on the Grounds

### The Setup (One Time)
```
You're on F/V Eileen, longlining for chum in SE Alaska.
Gear: 32 hooks, 1.5 fm spacing, soaking at ~48 fm.
Sounder: Furuno TZ Pro (50/200 kHz dual band).
GPS: u-blox on COM6.
```

### What Happens Automatically

**06:00 AM — You start the haul**
- Agent is already running (started at boot via Windows Task Scheduler)
- Every 30 seconds: *click* — sounder screen captured
- Every 4 minutes: *click* — full chart screen saved (your filmstrip)

**07:15 AM — First chum comes over the roller**
- Agent's analyzer just processed the 07:10 sounder frame
- **Found:** 530 returns in mid-water (20–40 fm), biggest blob 254k pixels at 29.9 fm
- **Logged:** "chum signature — high LF, moderate HF, thermocline at 25.6 fm"
- **Compared to chart:** Chart says 67 fm. Sounder says 57.2 fm. **Delta: -9.8 fm**
- **Saved:** Anomaly #247 in the database. Tagged for QGIS export.

**08:00 AM — The bite turns on**
- **Peak frame:** 557 returns, 91.2 avg intensity, monster blob 279k pixels at 31.9 fm
- **Position:** 55°47.312'N, 131°41.778'W (drifting SW at 1.6 kts)
- **You say to crew:** "Hook 18 — big halibut!" 
- Agent hears nothing (yet) — but the **camera on the rail** records it
- Later: voice note + sounder frame = labeled training data

**12:00 PM — Haul done, steaming home**
- Agent has 120 sounder analyses for the day
- 47 anomalies logged (chart vs reality)
- 3 clear chum windows identified (07–08, 11:30–12:00, 14:00)
- All in `memory/observations/2026-07-18.jsonl` — searchable, permanent

**That evening (or next time you're at the dock)**
```
You: "What did 55°47.3N 131°41.8W look like yesterday at 0800?"
Agent: [shows echogram, bottom depth 57.2 fm, 530 mid-water returns, 
        thermocline 26 fm, LF/HF ratio 2.1 → chum signature]
        
You: "How's that compare to the chart?"
Agent: "Chart says 67 fm. You're 10 fm shallower. 
        Same spot last year: 8 fm delta. Bottom's building up."
        
You: "Export the anomalies for QGIS."
Agent: "Done. bathymetry/qgis_corrections.csv ready. 
        Open in QGIS, overlay on your chartplotter."
```

---

## How It Works (In Fisherman Terms)

### The Three Pieces

```
┌─────────────────────────────────────────────────────────────────┐
│                        YOUR BOAT                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   GPS (COM6) ──▶ NMEA Bridge ──▶ TZ Pro (nav)                   │
│        │                    │                                    │
│        │                    └──▶ TCP :6006 ──▶ Agent Dashboard   │
│        │                    └──▶ TCP :6007 ──▶ TZ Pro (position) │
│        │                                                     │
│        ▼                                                     │
│   ┌─────────────────────────────────────────┐                │
│   │         SOUNDER ANALYZER                │                │
│   │  (runs on your laptop/wheelhouse PC)    │                │
│   │                                          │                │
│   │  Every 30 sec:                           │                │
│   │  1. Screenshot sounder panel             │                │
│   │  2. Crop to just the water column        │                │
│   │  3. Read the palette (blue→red scale)    │                │
│   │  4. Find the bottom line                 │                │
│   │  5. Count fish returns above it          │                │
│   │  6. Measure intensity, depth, spread     │                │
│   │  7. Detect thermoclines                  │                │
│   │  8. Classify bottom type (hard/soft/mud) │                │
│   │  9. OCR the depth scale numbers          │                │
│   │  10. Pair with GPS position from NMEA    │                │
│   │  11. Query bathymetric chart at that spot│                │
│   │  12. LOG IT ALL — JSON + human markdown  │                │
│   └─────────────────────────────────────────┘                │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### The Data Flow (What Goes Where)

```
SOUNDER SCREEN (TZ Pro)
        │
        ▼
SCREENSHOT (PowerShell GDI+ capture of DISPLAY6)
        │
        ▼
CROP TO SOUNDER REGION (370×900 px — just the water column)
        │
        ▼
OPENCV ANALYSIS
        │
        ├──▶ Palette detection (this display's blue→cyan→yellow→orange→red)
        ├──▶ Background subtraction (filter the dark blue noise)
        ├──▶ Bottom detection (strongest horizontal return band)
        ├──▶ Depth scale OCR (Tesseract reads the numbers on the side)
        ├──▶ Fish returns (pixels > 180 RGB total = target)
        ├──▶ Thermoclines (horizontal bands above bottom)
        └──▶ Bottom type (return texture + intensity → hard/medium/soft/mud)
        │
        ▼
NMEA POSITION (from bridge, timestamp-matched)
        │
        ▼
BATHYMETRIC QUERY (numpy grid, 0.001° resolution = ~100m)
        │
        ▼
COMPARISON: sounder_depth - chart_depth = DELTA
        │
        ▼
IF |delta| > 1 fm: LOG ANOMALY (SQLite + QGIS export)
        │
        ▼
DAILY LOG: memory/observations/YYYY-MM-DD.jsonl
        │
        ▼
YOU CAN QUERY IT ANYTIME
```

---

## What You Get Out of It

### 1. Daily Markdown Summary (Human-Readable)
```
# Echogram Capture 0800_5547.312N_13141.778W
**Date:** July 18, 2026  **Time:** 08:00 AKDT

## Vessel
- Position: 55°47.312'N  131°41.778'W
- SOG 1.59 kn  COG 209°

## Analysis
Bottom detected at 57.2 fm (high confidence). 
10 thermal layers at 16.1, 26.1, 35.2 fm. 
557 echo returns in LF band across 5 zones. 
Vocabulary predicts: **chum**.
Mid-water (20-40 fm) mean intensity 91.2/255, peak 255/255.
**Largest return: 31.9 fm, 279,403 px², intensity 121.9**
```

### 2. Structured JSON (Machine-Readable, Searchable)
```json
{
  "ts": "2026-07-18T16:00:00+00:00",
  "position": {"lat": 55.78853, "lon": -131.69630},
  "vessel": {"sog": 1.59, "cog": 209},
  "sounder_analysis": {
    "depth_fm": 57.2,
    "bottom_type": "soft_mud",
    "fish_returns": {
      "count": 557,
      "density_per_100kpx": 1674.3,
      "avg_intensity": 91.2,
      "depth_range_fm": [20, 40],
      "largest_blob": {"depth_fm": 31.9, "area_px": 279403, "intensity": 121.9}
    },
    "thermoclines_fm": [16.1, 26.1, 35.2]
  },
  "chart_comparison": {
    "charted_fm": 67.3,
    "delta_fm": -10.1,
    "anomaly_logged": true
  }
}
```

### 3. Anomaly Database (Chart Corrections)
```sql
-- Every spot where reality ≠ chart
SELECT * FROM bathymetry_anomalies 
WHERE abs(delta_fm) > 2.0 
ORDER BY abs(delta_fm) DESC;
```
| Lat | Lon | Sounder fm | Chart fm | Delta | Date |
|-----|-----|------------|----------|-------|------|
| 55.786 | -131.696 | 57.2 | 67.3 | -10.1 | 2026-07-18 |
| 55.342 | -131.643 | 53.2 | 67.3 | -14.1 | 2026-07-15 |

### 4. QGIS-Ready Exports (For Your Chartplotter)
```csv
# bathymetry/qgis_corrections.csv
Longitude, Latitude, Depth
-131.696, 55.786, -97.3
```
Load into QGIS → overlay on your C-Map/Navionics → see exactly where the chart is wrong.

---

## Questions You Can Answer

### "Where were the chum holding yesterday?"
```bash
python agent.py --brief "chum yesterday"
# Or just grep the daily log:
grep -i chum memory/observations/2026-07-18.jsonl
```

### "Show me every spot where the bottom's 5+ fm different from the chart"
```bash
python anomaly_logger.py --export-csv --min-delta 5.0
# Opens in Excel/QGIS instantly
```

### "What's the charted depth at 55°30'N 132°00'W? Will my 48 fm gear hit bottom?"
```bash
python contour_query.py 55.5 -132.0
# → 67.3 fm charted. You have 19.3 fm clearance. Safe.
```

### "Compare this spot to the same date last year"
```bash
# The daily logs are permanent. Just diff two files:
diff memory/observations/2025-07-18.jsonl memory/observations/2026-07-18.jsonl
# Or ask the agent:
python agent.py "compare 55.78 -131.70 July 18 2025 vs 2026"
```

### "Export all my chum catches with sounder signatures for the season"
```bash
python catch_link.py --species chum --season 2026 --export-csv
# Columns: date, time, lat, lon, hook#, species, size, sounder_depth, 
#          fish_count, LF_intensity, HF_intensity, thermocline_depth, bottom_type
```

---

## Hardware You Need (Off-the-Shelf)

| Component | What We Use | Approx Cost | Notes |
|-----------|-------------|-------------|-------|
| **Laptop/PC** | AMD Ryzen AI 9 HX 370, 32 GB RAM, RTX 4050 | $1,500 | Any Win11 box works; GPU only for future VL models |
| **GPS** | u-blox NEO-M8N (or any NMEA 0183 source) | $40 | COM6 at 4800 baud on Eileen |
| **NMEA Bridge** | USB-Serial adapter + our `nmea_bridge.py` | $25 | Shared-mode critical — lets TZ Pro AND agent read GPS |
| **Sounder** | Furuno TZ Pro (you already have this) | — | Dual-band 50/200 kHz |
| **Display** | Dedicated monitor for TZ Pro (DISPLAY6) | — | Agent captures this specific display |
| **Storage** | 500 GB SSD minimum | $50 | Growing logs + 160 MB contour grid |

**Total new hardware:** ~$1,600 if starting from scratch. **Most boats already have the GPS, sounder, and a laptop.**

---

## Installation (The "Wire It Yourself" Way)

### 1. Get the Code
```powershell
git clone https://github.com/SuperInstance/tzpro-agent.git
cd tzpro-agent
```

### 2. Install Python Stuff
```powershell
pip install pillow numpy
# Tesseract for OCR (download from github.com/UB-Mannheim/tesseract/wiki)
```

### 3. Run the NMEA Bridge (from hermit-crab repo)
```powershell
# This shares your GPS with BOTH TZ Pro and the agent
cd ..\hermit-crab\nmea-bridge
python nmea_bridge.py --port COM6 --baud 4800
# Leave this running. It bridges COM6 → TCP :6006 (agent) + :6007 (TZ Pro)
```

### 4. Build the Bathymetric Grid (One Time, ~10 Minutes)
```powershell
cd ..\tzpro-agent
python bathy_contours.py
# Downloads/processes 10.5 GB NOAA soundings → 153 MB grid + 9 contour layers
# Only needs doing once per region (SE Alaska built in)
```

### 5. Test a Single Capture
```powershell
python capture.py --oneshot
# Should print JSON analysis to screen + save PNG + markdown
```

### 6. Start the Background Daemon
```powershell
python capture.py
# Runs forever: 30s sounder crops + 4min full frames
# Ctrl+C to stop
```

### 7. Make It Auto-Start at Boot (Windows Task Scheduler)
- Open Task Scheduler → Create Basic Task
- Trigger: "At log on"
- Action: `powershell.exe -Command "cd C:\path\to\tzpro-agent; python capture.py"`
- Run whether user logged on or not (for headless operation)

---

## Daily Workflow (What You Actually Do)

### Morning (Before Haul)
- Nothing. Agent's already running if you set up auto-start.
- Verify: dashboard at `http://localhost:8654` shows green lights.

### During the Day
- Fish. The agent watches the sounder.
- **Optional:** Say "hook 12 chum 60cm" into your phone when something notable comes up.
  - Future version will auto-transcribe and label the sounder frame.

### Evening / At the Dock
```powershell
# Quick health check
python agent.py --brief
# "Last 24h: 1,240 captures, 47 anomalies, 3 chum windows, 0 errors"

# Export corrections for your chartplotter
python anomaly_logger.py --export-csv --min-delta 1.0
# Opens bathymetry/qgis_corrections.csv — load into QGIS

# Or just ask questions
python agent.py "where was the best chum yesterday"
python agent.py "show me all spots > 5 fm off chart this week"
```

### End of Season
```
Your data directory now has:
memory/observations/2026-07-15.jsonl
memory/observations/2026-07-16.jsonl
...
memory/observations/2026-10-15.jsonl

That's your season. Searchable. Permanent. Yours.
```

---

## The Bigger Picture: Why This Exists

### The CoCapn Philosophy
This isn't a product you buy. It's a **system you build and own**.

- **Open source:** All code, all configs, all wiring guides. Free forever.
- **You're customer zero:** If it works on Eileen, it works for the fleet.
- **The installer is a human-in-the-loop:** You push the buttons the agent tells you to push. You read back the numbers it asks for. You learn your own boat's wiring.
- **The repo is the seed:** Hardware changes. Models change. The code persists.

### The Hierarchy on Board

```
CAPTAIN (Picard) — Casey
  │  Sets the mission. Makes the calls. Owns the outcomes.
  ▼
RIKER (Operations Officer) — This AI agent
  │  Maintains the machine. Integrates new sensors. 
  │  Decides which copilots to deploy. Sees the whole boat.
  ▼
TZ PRO AGENT (Tactical Copilot) — THIS REPO
  │  Blinders on. One job: watch the sounder. Perfect focus.
  │  Doesn't know about fuel, autopilot, crew schedule.
  ▼
FUTURE COPILOTS (Planned)
  ├── Autopilot Copilot — watches rudder/compass, learns to steer gentler
  ├── Engine Room Copilot — temps, fuel, RPM, vibration
  └── Catch Log Copilot — species, counts, position, rigged
```

**Key insight:** A copilot is a racehorse with blinders. One task, perfect focus. Riker is not a copilot — Riker is closer to the Captain than the crew. Riker connects the copilots, rewires the architecture, sees the whole machine.

---

## What's Coming (The Roadmap)

| Phase | What | Status | Why It Matters |
|-------|------|--------|----------------|
| **1-3** | Sounder capture + bathymetry + anomalies | ✅ Done | Foundation — you have this now |
| **4** | ZeroClaw agent loop — natural language queries | 🔧 In design | "Where were chum holding last Tuesday?" |
| **5** | Florence-2 vision model on sounder images | 📋 Planned | AI "reads" the echogram like a human |
| **6** | DAW dashboard — web replay + query | 📋 Planned | Scrub through the day like a video |
| **7** | Catch ↔ sounder correlation | 📋 Planned | "This sounder signature = this species/size" |
| **8** | Deck camera → sounder correlation | 📋 Planned | Camera sees the hook, sounder sees the depth, link them |

### The End Game
**A system that deploys itself onto any boat.** Interview the captain. Inventory the hardware. Search the web for missing pieces. Write the wiring guide. Train the copilots. Improve season over season.

**50 boats in one bay. One industry.** If it works for one fisherman, it works for all of them. From Ketchikan, you build a career installing systems without leaving your dock. But that's not the goal. The goal is to build something that installs itself.

---

## Troubleshooting (Common Gotchas)

| Symptom | Cause | Fix |
|---------|-------|-----|
| "No GPS data" | NMEA bridge not running | Start `nmea_bridge.py --port COM6 --baud 4800` |
| "TZ Pro loses GPS" | Bridge opened COM6 exclusive mode | Our bridge uses `FILE_SHARE_READ|WRITE` — must use our `nmea_bridge.py` |
| "Depth readings look wrong" | Palette detection failed | Check `config.py` — palette tuned for YOUR display |
| "Chart query returns None" | Outside contour grid ROI | Grid covers 54-59°N, 130-138°W. Expand in `bathy_contours.py` |
| "Anomalies all huge deltas" | Depth scale OCR misread | Verify Tesseract installed; check sounder range setting (60 fm fixed) |
| "Two analyzer.py processes" | Duplicate start | Check Task Scheduler — only one `capture.py` should run |
| "Permission denied writing captures" | Windows folder permissions | Run PowerShell as Admin once, or fix folder ACLs |

---

## File Map (What's Where)

```
tzpro-agent/
├── capture.py              # Main daemon — run this
├── capture_v3.py           # Newer capture with PNG+JSON output
├── capture_tray.py         # System tray icon + controls
├── sounder_analyzer.py     # OpenCV brain — reads the sounder
├── screenshot.py / .ps1    # Screen capture (PowerShell GDI+)
├── config.py               # YOUR SETTINGS — crop regions, thresholds, paths
├── contour_query.py        # "How deep is it here?" — fast numpy lookup
├── bathy_contours.py       # Build the grid (run once)
├── bathy_preprocess.py     # Scan NOAA soundings (run once)
├── anomaly_logger.py       # SQLite + QGIS export for chart diffs
├── agent.py                # Ask questions in plain English
├── agent_loop.py           # Background reasoning loop
├── catch_link.py           # Link catches to sounder data
├── catch_patterns.py       # Species signatures from sounder
├── memory/                 # YOUR DATA — never committed to git
│   ├── observations/       # Daily JSONL logs (permanent record)
│   ├── daily/              # Markdown summaries
│   └── index/              # Search index
├── bathymetry/             # Chart data (160 MB grid + contours)
│   ├── contours/           # 9 GeoJSON layers (5, 10, 20, 30, 48, 60, 80, 100, 150 fm)
│   ├── anomalies.db        # SQLite — reality vs chart
│   └── qgis_corrections.csv # Load this into QGIS
├── captures/v3/            # PNG screenshots organized by date/position
├   └── 2026-07-18_5546.779N_13141.210W/
│       ├── 0800_5547.312N_13141.778W.png
│       ├── 0800_5547.312N_13141.778W.json
│       └── 0800_5547.312N_13141.778W.md
└── README.md               # This file
```

---

## Philosophy (The Invariants)

These never change. They're the constitution.

1. **Open source. Everything.** Hardware guides, wiring templates, agent configs.
2. **Captain is customer zero.** Everything that works for him works for the fleet.
3. **The sounder is the only thing worth reading off the screen.** Lat/lon/SOG/COG come from NMEA.
4. **Copilots wear blinders.** One task, perfect focus. They don't know they're part of a larger system.
5. **The tool must disappear.** Every feature must pass the ignorability test.
6. **The repo is the seed.** Hardware changes. Models change. The repo persists.
7. **Don't fight the tide.** GPU contention is not a bug. Alternate. Fall back. Surf.
8. **Charts, not maps.** Alive, updated by every pass. Never finished.
9. **Keep pushing.** Perfect is the enemy of deployed.

---

## Captain's Writings (The "Why")
Seven documents that define this project. Read them to understand the soul:

1. **The Hundred Hooks** — Every hook is a measurement. The pattern = the intelligence.
2. **The Person You Forgot Was There** — The highest form of any tool: it disappears.
3. **Charts Not Maps** — A map is static. A chart is alive, updated by every pass.
4. **Ebb and Flow** — Compute has tides. Don't fight them. Surf them.
5. **Cognitive Photosynthesis** — The system is an orchestrated whole, not a pile of parts.
6. **The Reflection You Mistook for Depth** — Maximum activation ≠ correctness. Right tool for the job.
7. **Turbo Nemotron** — The invariant concept lives in the repo. Narrow scope, conservation budget.

---

## Get Help / Contribute

- **Issues:** GitHub Issues on `SuperInstance/tzpro-agent`
- **Discussions:** GitHub Discussions — ask questions, share setups
- **Wiring help:** `hermit-crab` repo has NMEA bridge, dashboard, schematics
- **Captain's log:** `FISHINGLOG_FOUNDING.md` in hermit-crab — the founding transcript

---

## License

**MIT** — Use it, modify it, sell installs of it, put it on 100 boats. Just keep the license file.

---

**Part of the CoCapn Ecosystem**  
🌐 [CoCapn.com](https://CoCapn.com) | 📊 [ActiveLedger.ai](https://ActiveLedger.ai) | 🎣 [FishingLog.ai](https://FishingLog.ai)

*Riker, Operations Officer, F/V EILEEN, Ketchikan Alaska*  
*First cast: July 15, 2026, 10:59 AKDT*
## Related

The cascade perception daemon now lives standalone at [SuperInstance/perception-cascade](https://github.com/SuperInstance/perception-cascade) — this repo keeps its local copy for the live vessel install.
