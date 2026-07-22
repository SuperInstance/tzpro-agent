# tzpro-agent panel — three-panel day console

A second web app for tzpro-agent. The scrubber (port 8080) is a deep
playback/replay tool; **this panel (port 8081)** is the daily at-a-glance
console with the three live tiers of the system side by side.

## Running

From the repo root:

```powershell
python -m panel.serve
# custom port / workspace
python -m panel.serve --port 8081 --workspace C:\path\to\workspace
```

Then open <http://127.0.0.1:8081>.

## Panels

| # | What | Tier | Persistence |
|---|------|------|-------------|
| 1 | **M1 change log** — retained novel notes with coords + features | transient delta notes | Novel M1 notes persist; routine 1-min PNGs are GC'd at EOD by `cascade/retention.py:evening_final_read` |
| 2 | **M10 records** — canonical 10-min captures with embedded echograms and inline record JSON | canonical, day-stitched | PNGs kept; structured JSON in `cascade_out/records/` |
| 3 | **H1 + D1 briefings** — human MD + paired agentic JSON | daily artifacts | `.md` and `.json` next to each other in `cascade_out/briefings/` |

## Endpoints

| Path | Returns |
|------|---------|
| `GET /` | Single-file HTML app |
| `GET /api/day/<YYYY-MM-DD>` | Counts summary |
| `GET /api/day/<YYYY-MM-DD>/panel/1` | M1 notes for the day |
| `GET /api/day/<YYYY-MM-DD>/panel/2` | M10 records for the day |
| `GET /api/day/<YYYY-MM-DD>/panel/3` | Briefing metadata for the day (H1 + D1) |
| `GET /api/image/<capture_id>` | PNG bytes for a kept canonical frame |
| `GET /api/briefing/...md` | Briefing markdown body (raw text) |
| `GET /api/briefing/...json` | Parsed briefing JSON |
| `GET /api/record/<capture_id>` | Full record JSON by capture_id |
| `GET /api/stream` | SSE: `{kind: "tick", added, removed, ts}` whenever cascade_out/ changes |

## Live updates

Server-Sent Events on `/api/stream`. The panel backend polls the cascade
directories every 5 seconds (no fsnotify — works on Windows without
extra deps). On any add/remove the panel debounce-refreshes all three
panels for the current day.

## Reliability

- stdlib only (http.server, sqlite3, json, asyncio, threading) — no
  third-party deps, no build step, no node_modules.
- Same independence contract as the rest of the repo: the panel must
  boot even if cascade deps are missing (it reads the file tree, not
  the cascade package).
- All asset paths are absolute POSIX strings; no path assumptions beyond
  the cascade_out/ layout.

## Architecture decisions

- **PNG-vs-MD split:** M10 panel 2 shows the actual echogram; M1 panel 1
  has no image because those PNGs were deliberately deleted at EOD (the
  novel M1 text notes are sufficient signal).
- **One JSON per briefing:** the H1 `briefing_<ts>.json` and D1
  `day_<DATE>.json` exist so downstream agents don't have to reparse
  markdown. The MD is for humans.
- **Day picker via `<input type="date">`:** zero-dependency, native, works
  in kiosk/headless browsers.
- **TZ Pro second monitor lives in `cascade/capture_v3.py`:** this panel
  only consumes the output, never writes to it.

## Schedule

The D1 daily brief + end-of-day 1-min PNG GC fires automatically inside
`cascade/daemon.py`. The panel does not own any scheduled work — it's a
read-only browser into the cascade's outputs.
