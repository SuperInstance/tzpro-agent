# TZ Pro Agent — Wheelhouse Quick Reference

**Print this. Laminate it. Velcro it to the dash.**

---

## One-Liners You'll Actually Use

| Need | Command |
|------|---------|
| "What's the charted depth here?" | `python contour_query.py <lat> <lon>` |
| "Is my 48 fm gear safe here?" | `python -c "from contour_query import get_gear_clearance; print(get_gear_clearance(lat, lon, 48))"` |
| "Show chart errors > 2 fm this week" | `python anomaly_logger.py --export-csv --min-delta 2.0` |
| "Where were chum holding yesterday?" | `python agent.py "chum yesterday"` |
| "Health check — any errors?" | `python agent.py --brief` |
| "One capture right now" | `python capture.py --oneshot` |

---

## Keyboard Shortcuts (If Running in Terminal)

| Key | Action |
|-----|--------|
| `Ctrl+C` | Stop capture daemon gracefully |
| `Ctrl+Break` | Force kill (if stuck) |
| `Up Arrow` | Repeat last command |

---

## Dashboard

**http://localhost:8654** — Hermit Crab dashboard (NMEA position, ActiveTrack, system status)

| Light | Meaning |
|-------|---------|
| 🟢 Green | All systems nominal |
| 🟡 Yellow | Warning (check logs) |
| 🔴 Red | Critical — NMEA down / analyzer crashed / disk full |

---

## Daily Log Locations

| What | Where |
|------|-------|
| Today's sounder analyses (JSONL) | `memory/observations/2026-07-19.jsonl` |
| Today's human summaries (markdown) | `memory/daily/2026-07-19.md` |
| Chart anomalies (SQLite) | `bathymetry/anomalies.db` |
| QGIS corrections export | `bathymetry/qgis_corrections.csv` |
| Sounder screenshots | `captures/v3/YYYY-MM-DD_.../` |

---

## Startup Checklist (Morning)

```
☐  NMEA bridge running? (python nmea_bridge.py --port COM6 --baud 4800)
☐  Dashboard green? (http://localhost:8654)
☐  Capture daemon running? (check Task Manager for capture.py)
☐  GPS position reasonable on TZ Pro?
☐  Sounder displaying normally (palette not shifted)?
```

---

## Shutdown Checklist (Evening)

```
☐  Export anomalies: python anomaly_logger.py --export-csv --min-delta 1.0
☐  Quick health check: python agent.py --brief
☐  Note anything weird in voice memo / notebook
☐  Leave PC on (auto-starts at boot via Task Scheduler)
```

---

## Emergency: "It's Broken"

| Symptom | 30-Second Fix |
|---------|---------------|
| TZ Pro shows "No GPS" | Restart NMEA bridge: `Task Manager → kill nmea_bridge.py → python nmea_bridge.py --port COM6 --baud 4800` |
| Dashboard red | Check `capture_tray.log` for errors; restart `capture.py` |
| "No such file" on contour query | Run `python bathy_contours.py` (rebuilds grid, ~10 min) |
| Depth readings nonsense | Check sounder range set to 60 fm; verify Tesseract installed |
| Two capture.py processes | Kill both in Task Manager; restart one |

---

## Key Files to Know

| File | What It Does | Edit When |
|------|--------------|-----------|
| `config.py` | Crop regions, thresholds, paths, palette | New monitor, different sounder range, new GPU |
| `capture.py` | Main daemon — runs forever | Change capture interval, add new analysis |
| `sounder_analyzer.py` | Reads the sounder pixels | Palette drift, new bottom types, thermocline logic |
| `contour_query.py` | "How deep is it here?" | Expand ROI, change grid resolution |
| `anomaly_logger.py` | Logs reality vs chart diffs | Change anomaly threshold, add export formats |

---

## Sounder Palette (This Display)

```
Background:     ███  rgb(13, 31, 54)      ~98 total — IGNORE
Weak returns:   ███  130-180 total       — plankton, soft mud
Medium:         ███  180-250 total       — fish, thermoclines
Strong:         ███  250+ total          — hard bottom, dense schools
```

**If palette shifts** (new display, different settings): edit `config.py` → `PALETTE_RANGES`

---

## Hook Geometry (Eileen)

```
Hook spacing:     1.5 fathoms
Hook count:       32
First bead:       ~1.5 fm below surface
Soak depth:       ~48 fm (wire diagonal = slightly shallower)
Depth ≈ hook_num × 1.5 + offset
```

---

## Species Signatures (Current)

| Species | LF/HF Ratio | Depth Range | Intensity | Texture |
|---------|-------------|-------------|-----------|---------|
| Chum | High LF, mod HF | 20-40 fm | 80-150 | Dense mid-water clouds |
| Coho | Mod LF, high HF | 10-30 fm | 120-200 | Tight schools, higher |
| Pink | Very high LF | 15-35 fm | 60-120 | Diffuse layers |
| Halibut | Strong HF | Bottom | 200+ | Single large returns on bottom |
| Rockfish | High HF | 30-60 fm | 150+ | Columnar, structure-associated |

---

## Voice Notes (Future — Say Into Phone)

> "Hook 12 — chum, 60 cm"
> "Hook 24 — halibut, big, 120 lbs"
> "Hook 5 — empty, dogfish bite"
> "Thermocline at 26 fm, fish stacked on it"

*Later: these auto-label the sounder frame at that timestamp.*

---

## Contacts / Help

| Who | What | How |
|-----|------|-----|
| Captain (Casey) | Mission, priorities, weird readings | Signal / voice |
| Riker (this agent) | System health, queries, "what does this mean?" | `python agent.py "your question"` |
| GitHub Issues | Bugs, feature requests | github.com/SuperInstance/tzpro-agent/issues |
| Hermit-crab repo | NMEA bridge, dashboard, wiring | github.com/SuperInstance/hermit-crab |

---

## The Invariant Rules (Never Forget)

1. **Sounder is the only thing worth reading off the screen.** GPS/SOG/COG come from NMEA.
2. **Copilots wear blinders.** This agent watches sounder. Period.
3. **The tool must disappear.** If you're fighting the software, it's broken.
4. **Charts, not maps.** Alive, updated by every pass. Never finished.
5. **Keep pushing.** Perfect is the enemy of deployed.

---

*F/V EILEEN • Ketchikan, AK • CoCapn ecosystem*
*First cast: July 15, 2026 10:59 AKDT*