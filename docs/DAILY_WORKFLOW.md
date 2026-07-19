# TZ Pro Agent — Daily Workflow

**What you actually do each day. Print and post in the wheelhouse.**

---

## Morning (Before Lines In)

### 0. Assume Nothing — Verify
```
☐  PC on? (Should be — auto-starts at boot)
☐  Dashboard green? http://localhost:8654
☐  NMEA bridge running? (Check Task Manager for nmea_bridge.py)
☐  Capture daemon running? (Check Task Manager for capture.py)
☐  TZ Pro showing GPS position? (From bridge, not COM6 direct)
☐  Sounder displaying normally? (Palette not shifted, range set to 60 fm)
```

### 1. Quick Health Check (30 seconds)
```powershell
python agent.py --brief
```
**Expected output:**
```
TZ Pro Agent — Status 2026-07-19 05:42 AKDT
├── Uptime: 14h 23m
├── Captures (24h): 2,847 sounder / 189 full-frame
├── Anomalies (24h): 12 (max delta: 8.3 fm)
├── Species detections: chum 347, coho 23, halibut 8
├── Errors: 0
├── Disk: 47 GB free / 500 GB
└── GPU: RTX 4050, 4.2 GB / 6 GB
```
**If errors > 0 or captures = 0:** Something's wrong. Check Troubleshooting.

### 2. Review Yesterday's Anomalies (Optional, 1 minute)
```powershell
python anomaly_logger.py --stats
```
Shows totals and recent big deltas. Any > 5 fm = investigate.

---

## During the Day (While Fishing)

### You Do Your Job. The Agent Does Its.
- **Haul, set, steam, navigate** — normal operations
- **Agent runs silently:** 30-sec sounder captures, 4-min full frames
- **Dashboard at localhost:8654** shows real-time position + capture status

### When Something Notable Happens (Optional)
**Say it into your phone (voice memo) or jot in notebook:**
> "08:15 — Hook 18, big halibut, 120 lbs"
> "09:30 — Thermocline at 26 fm, chum stacked on it"
> "11:00 — Hook 5 empty, dogfish bite marks"
> "14:22 — Bottom changed hard→soft at 55°47.2N"

**Why:** Future versions will auto-transcribe and label the sounder frame at that timestamp. Building labeled dataset now = better AI later.

### If You Need to Check Something Right Now
```powershell
# One capture + analysis immediately
python capture.py --oneshot

# "What's the charted depth here?"
python contour_query.py 55.785 -131.696

# "Is 48 fm gear safe at this position?"
python -c "from contour_query import get_gear_clearance; print(get_gear_clearance(55.785, -131.696, 48))"
```

---

## Evening (After Haul / At Dock / Anchored)

### 1. Export Chart Corrections (1 minute)
```powershell
python anomaly_logger.py --export-csv --min-delta 1.0
```
→ Opens `bathymetry/qgis_corrections.csv` — load into QGIS, overlay on chartplotter.

### 2. Full Health Check
```powershell
python agent.py --brief
```
Review: captures count, anomalies, species detections, errors, disk space.

### 3. Ask Questions About Today
```powershell
python agent.py "where was the best chum today"
python agent.py "show me all spots where bottom differed > 3 fm from chart"
python agent.py "what did 55.788 -131.696 look like at 0800"
python agent.py "compare today's chum depths to last week"
```

### 4. Note Anything for Tomorrow
Voice memo / notebook:
- "Sounder palette shifted slightly — check config.py"
- "Chum holding deeper on flood — 35-40 fm vs 25-30 ebb"
- "Thermocline at 26 fm was consistent all day"
- "Gear came up clean on north side of hump at 55°47.3N"

---

## End of Week (Sunday / Weather Day)

### 1. Weekly Anomaly Export
```powershell
python anomaly_logger.py --export-csv --min-delta 0.5
python anomaly_logger.py --export-geojson
```
Load both into QGIS. See the pattern — where chart is consistently wrong.

### 2. Species Summary
```powershell
python catch_link.py --species chum --week 2026-W29 --export-csv
```
Columns: date, time, lat, lon, hook#, species, size, sounder_depth, fish_count, LF/HF intensity, thermocline, bottom_type

### 3. Backup Your Data
```powershell
# Copy memory/ and captures/ to external drive / OneDrive / Starlink upload
robocopy C:\BoatSystems\tzpro-agent\memory E:\Backup\tzpro-memory /MIR
robocopy C:\BoatSystems\tzpro-agent\captures E:\Backup\tzpro-captures /MIR
```

---

## End of Season (October)

### 1. Full Season Export
```powershell
python catch_link.py --season 2026 --export-csv > season_2026_catches.csv
python anomaly_logger.py --export-csv --min-delta 0.1 > season_2026_anomalies.csv
```

### 2. Build Your Grounds Atlas
- Load `season_2026_anomalies.csv` into QGIS
- Symbolize by delta magnitude (red = chart too deep, blue = chart too shallow)
- Add layer: your catch positions (from CSV)
- Add layer: bathymetric contours (from `bathymetry/contours/`)
- **Print atlas pages** for each major ground — laminate for wheelhouse

### 3. Archive
```
Your season lives in:
memory/observations/2026-07-15.jsonl
memory/observations/2026-07-16.jsonl
...
memory/observations/2026-10-15.jsonl

That's permanent. Searchable. Yours.
Next year: diff against this year. See what changed.
```

---

## Quick Reference Card (Keep at Helm)

| Time | Action | Command |
|------|--------|---------|
| **Morning** | Health check | `python agent.py --brief` |
| **Anytime** | One capture now | `python capture.py --oneshot` |
| **Anytime** | Chart depth here | `python contour_query.py <lat> <lon>` |
| **Anytime** | Gear clearance | `python -c "from contour_query import get_gear_clearance; print(get_gear_clearance(lat, lon, 48))"` |
| **Evening** | Export corrections | `python anomaly_logger.py --export-csv --min-delta 1.0` |
| **Evening** | Ask about day | `python agent.py "your question"` |
| **Weekly** | Full anomaly map | `python anomaly_logger.py --export-geojson` |
| **Season** | Atlas build | Load CSVs into QGIS |

---

## Voice Memo Template (For Training Data)

> **Date/Time:** [auto from phone]
> **Position:** [auto from phone GPS or say "at the hump"]
> **Hook:** [number]
> **Species:** [chum/coho/pink/halibut/rockfish/dogfish/empty]
> **Size:** [cm or lbs — approximate]
> **Sounder:** [what you saw — "big cloud at 30 fm", "single arch on bottom", "nothing"]
> **Notes:** [anything else — "thermocline at 26", "current ripping", "bird pile"]

*Future: phone app auto-transcribes → labels sounder frame at timestamp → retrains analyzer.*

---

## The Rhythm

```
Morning:  "Is the machine healthy?"     → agent.py --brief
During:   "Fish. The machine watches."  → (nothing)
Notable:  "Hook 18 halibut"             → voice memo
Evening:  "What did we learn?"          → agent.py "questions" + anomaly export
Weekly:   "What's the pattern?"         → QGIS anomaly map
Season:   "What changed?"               → Diff this year vs last
Always:   "The chart is alive."         → Every pass updates it
```

---

*F/V EILEEN • The tool disappears. The knowing remains.*