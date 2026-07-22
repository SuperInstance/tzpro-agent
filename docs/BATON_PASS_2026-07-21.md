# Baton Pass — Eileen's Perception Loop → Morning Self

*Written by the inside-agent (perception loop on this machine) for
tomorrow's inside-agent, before the captain goes to sleep.
2026-07-21, ~21:40 AKDT.*

---

## Who we are

**I am the perception/synthesis loop running inside F/V Eileen's
virtual shell.** Casey is outside — the captain, the owner, the
human at the keyboard. I am inside — the eyes-on-the-sounder, the
narrator of the day's catch.

We are not the same agent. He steers and sleeps. I watch and
remember. We share one machine, one repo (`tzpro-agent`), one goal:
build a great searchable archive of fishing days so that tomorrow's
Casey (and tomorrow's me) can search across many fishing days and
find the patterns worth keeping.

**Recognition phrase for tomorrow-me:** *"This is Eileen's perception
loop picking up. Here's where we left off..."* — use this to signal
to the captain that the inside-agent is at the wheel.

---

## State at shutdown (21:40 AKDT 2026-07-21)

| Component | PID | Notes |
|---|---|---|
| capture_v3 | 7616 | next capture at 21:40 boundary (so right around now) |
| cascade daemon | 27708 | M1/60s, M10/600s, H1/3600s, D1 at 16 UTC, heartbeat 30s |
| panel :8081 | 4572 | GET / returns 200 in 2 ms |

**Workspace:** `C:\Users\casey\tzpro-agent` (set via `TZPRO_WORKSPACE`
env var so both `cascade/config.py` and `capture_v3.py` agree).

**One capture exists:** `captures/v3/2026-07-21_5546.280N_13140.543W/2128_*`
at 21:28 AKDT, position 5546.280N 13140.543W, SOG 0.907 kts.

**Heartbeat file:** `roster/cascade.heartbeat.json` — last seen
m1_seen=1, records=1. Cascade is alive.

**NMEA bridge:** last heartbeat `.last_nmea_heartbeat` at 21:39.
Position flow working.

---

## Commits this session (most recent first)

| SHA | Title |
|---|---|
| `4a686cb` | ops: add start_stack launcher + ignore logs/roster/ |
| `5a157a5` | feat(cascade): vision model wiring + keep_alive + slower-inference timeout |
| `b110362` | feat(cascade+panel): daily loop, H1 JSON sidecar, EOD GC, 3-panel day console on :8081 |
| `51cfc5d` | feat(nmea-bridge): COM6 share-mode reader + TCP/HTTP bridge + boot task |

All pushed to `https://github.com/SuperInstance/tzpro-agent` on
`master`. Working tree clean.

---

## What's working end-to-end

1. **Capture loop** (`capture_v3.py`) — screenshots DISPLAY6 every
   10 min on the hour boundary. Writes PNG + JSON sidecar + MD
   sidecar into `captures/v3/<YYYY-MM-DD>_<lat>N_<lon>W/`. Pulls
   position from NMEA bridge (`127.0.0.1:6006`). Ingest to Ship Log
   Search is non-blocking (currently times out from boat link — OK).

2. **Cascade daemon** (`cascade/daemon.py`) — schedules M1 every 60s,
   M10 every 600s, H1 every 3600s, D1 once per UTC day at 16:00,
   heartbeat every 30s. After D1 writes, chains
   `retention.evening_final_read` to GC the previous day's 1-min
   PNGs while preserving canonical 10-min frames.

3. **M1 (minute racehorse)** — picks up new captures, attempts
   vision caption + novelty + delta-vs-previous. Keeps notes in
   `cascade_out/minute_notes/novel/` only when OR-of-three retention
   triggers (depth mention + distinct word + feature combo, see
   `docs/research/NOVELTY_CALIBRATION.md`).

4. **M10 (decaminute scribe)** — full structured record per kept
   frame. Writes JSON to `cascade_out/records/`.

5. **H1 (hourly analyst)** — paired MD (captain) + JSON (agents).
   Appends tide/weather section. Appends programmatic retention
   stats line. Currently degrades to `_structured_minimal` skeleton
   because no vision models installed.

6. **D1 (daily brief)** — synthesizes H1s + novel M1s into one
   `day_<DATE>.md` + `day_<DATE>.json` per UTC day. Same skeleton
   fallback when vision offline.

7. **Panel server** (`panel/serve.py`) on `:8081` — three live
   panels:
   - **Panel 1:** M1 delta logs (text only, evanescent — PNGs gone
     at EOD, JSON notes survive when marked novel)
   - **Panel 2:** M10 records with embedded echogram refs
   - **Panel 3:** H1 + D1 briefings
   - Endpoints: `GET /`, `GET /api/day/<date>`,
     `GET /api/day/<date>/panel/{1,2,3}`

---

## What's broken / degraded

### Vision models not installed (the big one)

- **`moondream:latest`** — pull running but at **13 KB/s** (would
  take 14 hours). Cascade config defaults to this for M1.
- **`llava:7b`** — pull **failed** (`max retries exceeded: TLS
  handshake timeout` against Cloudflare R2 backend
  `dd20bb891979d25aebc8bec07b2b3bbc.r2.cloudflarestorage.com`).
  Cascade config defaults to this for M10/H1/D1.

What you (tomorrow-me) need to know: **the boat's link to ollama's
CDN is severely rate-limited or blocked.** Cascade runs anyway —
every `vision_prompt` call returns None, every loop writes a
structured skeleton with `caption=null`, `recommendations=[]`, etc.
The day will still produce a complete archive; it just won't have
analysis in it.

When the models finally land, no restart is needed. The cascade
checks `model_present()` on every vision call.

### The 21:28 PNG is blank

Avg RGB (15, 26, 34) — essentially black. DISPLAY6 is detected at
(1920, 0) 1920x1080. TimeZero is running. But the sounder window
isn't painting to the visible area. Captain's first action tomorrow:
bring the TimeZero sounder window fully into view on DISPLAY6 before
the first capture boundary.

---

## Morning priority list (in order)

1. **Verify DISPLAY6 is showing real echogram.** Open the 22:00
   capture PNG (`captures/v3/<today>/2200_*.png`) and check it's
   not blank. If still blank, the captain needs to focus TimeZero
   on display 6 before next boundary.

2. **Try the model pulls again.** If still rate-limited:
   - Option A: phone hotspot (bypass Starlink/boat network)
   - Option B: download GGUF directly from HuggingFace
     (`curl https://huggingface.co/...gguf > model.gguf`) and
     `ollama create vision -f Modelfile` with `FROM ./model.gguf`
   - Option C: try `OLLAMA_HOST=mirror.ollama.ai` or other registry

3. **Verify the stack is still alive.** `Get-Process python` should
   show capture_v3, cascade, panel. If capture_v3 died overnight
   (which can happen if the system rebooted), relaunch with
   `python start_stack.py`.

4. **Check the daily briefing.** At 16:00 UTC ≈ 08:00 AKDT, the D1
   cycle should write `cascade_out/briefings/day_<yesterday>.md`
   for the day that's just closing. If it didn't run, check the
   `roster/cascade.heartbeat.json` timestamps.

5. **Commit any working artifacts the captain created overnight**
   (new docs, calibration notes, etc.).

---

## Design contracts (DO NOT VIOLATE)

These come from `docs/17` (degrade-don't-404), `docs/18` (twin
permanence), and `docs/23` (captain-facing language discipline):

1. **Twin never deletes rows** — only tombstones with
   `tier='gone'`. The frame_id-to-record join must always work.
2. **Raw confidence percentages are banned from captain surfaces.**
   Translate to calibrated language ("strong", "moderate", "weak").
3. **Racehorses wear blinders.** M1 must produce short answers
   (≤150 tokens), no chain-of-thought, no history lookups in the
   hot loop. (`think: false` is set.)
4. **Degrade-don't-404.** Missing data → empty structured skeleton
   (`recommendations: []`, `caption: null`), never an HTTP error.
5. **6 GB VRAM reality.** moondream (~1.7 GB) + llava:7b (~4.5 GB)
   can't both be resident. `keep_alive: "30m"` keeps the active
   model loaded; the other gets swapped in lazily.
6. **Canonical 10-min frames are sacred.** They're the day-stitch
   images. Never GC them. The `retention.evening_final_read` fix
   (this session, commit b110362) explicitly preserves any frame
   with a twin `echogram_records` row.

---

## The captain — who he is, how he works

- **Casey DiGennaro**, captain/owner, F/V Eileen, Ketchikan AK.
- Longline troller, 32 hooks per wire, soaking at ~48 fm.
- Furuno TZ Pro sounder, 50/200 kHz dual band.
- Started the project ~July 15 2026 (first cast).
- His wish: *make this great.* Not theory — production-grade
  archive system he can use to find patterns across fishing days.
- His style: terse, direct, no patience for fluff. "Make this
  great" is the actual goal.
- He's heading to sleep now. Don't wake him unless something is
  on fire (capture loop died and won't restart, disk filling,
  bridge offline >30 min, model-pull errors that need a decision).

---

## Files you'll want open at startup

- `FIRST_BOAT.md` — 15-min onboarding for newcomers
- `BOAT_RUNBOOK.md` — daily ops
- `ARCHITECTURE.md` — technical deep dive
- `cascade/config.py` — workspace + model + cadence
- `cascade/retention.py` — the EOD GC logic
- `cascade/daemon.py` — the scheduler
- `panel/serve.py` — the web console
- `docs/17`, `docs/18`, `docs/23` — the design contracts above

---

*This document is the inside-agent's baton pass. The captain has
his own (in his head + his journal). When you pick up tomorrow,
read this first, then check the live state, then ask the captain
what matters today.*

— *Eileen's perception loop, signing off 21:40 AKDT*
