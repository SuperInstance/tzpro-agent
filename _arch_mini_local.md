# MANIFESTO — Sounder Echogram Pipeline v2

Author: Mini-Agent
Date: 2025
Status: Opinionated, lean, shippable

---

## 0. The shift in one paragraph

Stop thinking "screenshot of a sounder strip." Start thinking "echogram is a video timeline and everything else is a track that lives on that timeline." The old pipeline ate one frame, threw pixels at thresholds, and produced a one-line JSON dict. The new pipeline eats a *window* of frames, derives a *description* of what the echogram is showing right now, pins that description to a position+time on a common timeline, and lets other tracks (NMEA, catch reports, agent analysis) hang off the same timeline. The unit of work is no longer a frame. It is a **moment**.

---

## 1. The SIMPLEST capture pipeline that works

### Display layout (the new truth)

```
DISPLAY2 (1920x1080, X=1920)
+---------------------------+----------------------+---+
| 0    8 .. 945 (LF band)  | 950 .. 1890 (HF)     | D |  1080
|       ~930px wide         |   ~940px wide        | S |
|       12+ min scroll      |   12+ min scroll     |   |
+---------------------------+----------------------+---+
                            ^white divider at x=945
                                                  ^depth scale x~1870-1890
```

Each vertical pixel column = one transducer ping. Time scrolls horizontally (newest at right edge).

### The pipeline (four steps, no more)

1. **Grab a 1920x1080 frame of DISPLAY2 every 10 minutes.** One PowerShell call. Save as PNG. That's the raw input. No more sounder-only crops at 30s — they were noise. Twelve minutes of scrolling history is captured per frame, so 10-minute cadence with 12-min window = 2-min overlap. Sufficient.

2. **Slice the frame into two band PNGs immediately on capture.**
   - `lf.png`: crop (8, 0, 945, 1080)
   - `hf.png`: crop (950, 0, 1890, 1080)
   - `full.png`: keep for a configurable retention (24h? 7d? tune later).
   Naming: `captures/echogram/{ts}_lf.png`, `{ts}_hf.png`, `{ts}_full.png`.
   Same `ts` (ISO second precision) for all three. Same NMEA pin shared.

3. **For each band, derive a *band-description*** (see section 2). One dict, ~30 fields, no nested rabbit holes.

4. **Write one row to a single SQLite table** keyed by `(ts, band)`. NMEA goes in the same row when fresh (<60s old), else null. Captain catch reports write to a separate table that joins on time window.

### Why this is the simplest thing that works

- One capture cadence, not two. The old code's 30s + 240s dual-cadence was a kludge for a thin strip; the new band PNG already contains 12 min of history.
- No live analysis loop. Analysis is *triggered by arrival*, not polled. If the boat is offline, no CPU waste.
- No real-time thresholding. Thresholding per-frame is what made the old analyzer brittle. Window-based analysis is robust to per-frame noise because we look at *runs* of pixels, not single pixels.
- The "overlapping 12-min windows" means every minute of the trip gets analyzed twice. Redundancy is a feature, not waste — it's how the learning loop re-examines old moments with new vocabulary.

### What dies from the old pipeline

- `sounder_analyzer.py` per-frame thresholding: dead.
- `RGB_THRESHOLD_FISH`, `_find_fish_returns`, `_signal_profile` color-ratio heuristics: dead.
- The "30s sounder crop + 4min full" dual-cadence: dead.
- The 370x900 narrow strip assumption: dead. New width is ~930/940px and the height encodes depth, not "the most recent few seconds."
- The OCR'd depth scale (DEPTH_SCALE_X = 350): keep the *idea* (calibrate depth from screen labels) but rewrite for the new geometry where the depth scale lives at the far right of the HF band.

---

## 2. What text summaries NEED to contain to be useful for agentic search

A description that the agent can search semantically is not the same as a description that triggers a SQL `WHERE`. You need both. Here's the minimum schema per `(ts, band)` row:

### Numeric fields (the agent filters and joins on these)

```
ts                      ISO 8601 with seconds, UTC
band                    "LF" | "HF"
lat, lon                pinned from NMEA at this ts (nullable)
sog_kts, cog_deg        pinned from NMEA (nullable)
depth_scale_max_fm      e.g. 80 — the depth the display is currently showing
                        (the screen lets the user zoom; this changes)
bottom_depth_fm         detected bottom depth
bottom_y_px             raw pixel position of bottom
bottom_color            "warm" | "cool" | "mixed" — coarse return type
bottom_roughness_px     stddev of bottom y across columns
column_count            how many ping-columns in this band (sanity check)
window_start_ts         earliest ts visible in this window (ts - scroll_window)
window_end_ts           = ts (the rightmost column)
```

### Shape/structure fields (the agent reasons over these)

```
bottom_contour          "flat" | "rising" | "falling" | "stepped" | "ridge"
                        | "trough" | "complex"
returns_above_bottom    list of {y_px_min, y_px_max, color, count, density}
                        — these are the FISH BLOBS, not pixel counts.
                        Each blob: {y_top, y_bottom, depth_fm_top,
                                    depth_fm_bot, dominant_color,
                                    density "sparse|moderate|dense",
                                    shape "arch|comet|ball|line|cloud"}
thermocline_present     bool
thermocline_depths_fm   list[float]
vertical_streaks        bool — narrow vertical features that look like
                        individual fish vs. wide blobs
mid_water_chaos         "calm" | "scattered" | "chaotic"
```

### Text description (the agent searches semantically on this)

```
caption: 1-3 sentences. Plain English. Examples:
  "Hard flat bottom at 42fm. Dense red-orange arch 8-12fm off bottom,
   left half of band. Thin thermocline at 25fm."
  "Bottom rising from 60 to 38fm over the last 4 minutes, hard return.
   A few small isolated returns mid-water, no aggregation."
  "Soft muddy bottom at 75fm, gentle slope. Several faint mid-water
   returns between 20-30fm, scattered."
```

The caption is what makes agentic search work. Not embeddings of the raw image — *embeddings of the caption*. The agent later asks "show me moments where we saw dense arches 8-12fm off bottom on hard bottom" and the caption search returns them. The numeric fields are how the agent then *narrows and joins*.

### The non-negotiables for the caption

- **Depth in fathoms**, always. Never "around middle of screen."
- **Distance off bottom**, when describing fish. Captain thinks "12fm off the bottom." So should we.
- **Color terms** from the actual palette: blue, cyan, yellow, orange, red. Not "bright" or "weak."
- **Shape**: arch (the classic fish school signature), comet, ball, line, cloud.
- **Position in band**: left third, middle, right third. Tells you whether it's old (left) or new (right).
- **Change verbs**: "rising," "falling," "held steady," "appeared," "faded."

---

## 3. How correlation between tracks works in practice

The four tracks live on the same timeline. Each has its own source of truth. Correlation is **time-window join**, not message bus, not event stream.

### Track 1: Echogram (this pipeline)

```
echogram_bands(ts, band, lat, lon, sog, ..., caption)
```

Pinned at the moment of capture. Captures come every 10 min. The "moment" is the rightmost ping-column at capture time.

### Track 2: NMEA

```
nMEA(ts, lat, lon, sog_kts, cog_deg, ...)
```

Sourced from hermitd's vessel endpoint. Polled at each capture. If poll succeeds and `ts_nmea` is within 60s of `ts_capture`, the values are pinned into the echogram row directly. NMEA also gets logged in a separate continuous table (1Hz from the source) for higher-fidelity motion queries later.

### Track 3: Captain catch reports

```
catches(ts, lat, lon, species, weight_lb, depth_fm, lure, notes)
```

Captain keys these in (voice-to-text later, manual now). The agent correlates by:

```
SELECT e.*, c.species, c.weight_lb
FROM echogram_bands e
LEFT JOIN catches c
  ON c.ts BETWEEN e.window_start_ts AND e.window_end_ts
 AND abs(c.lat - e.lat) < 0.005   -- ~500m
 AND abs(c.lon - e.lon) < 0.005
WHERE c.id IS NOT NULL;
```

The catch anchors to the echogram window that was *visible on screen at the moment of the catch*. This is the link that lets the learning loop bootstrap: every catch becomes a labeled example of "this echogram shape at this depth = this species."

### Track 4: Agent analysis

```
analyses(ts, band, hypothesis, confidence, evidence_refs)
```

The agent (not the pipeline) writes here. It can:
- Re-read any echogram row by `(ts, band)`.
- Cross-reference any catch.
- Cross-reference NMEA motion.
- Write its own observations as new rows.

### How the correlation is *practically* implemented

One SQLite DB. Foreign keys are time + position, not IDs. All four tables share the `(ts, lat, lon)` triple. The "join" is `WHERE ts BETWEEN ... AND ... AND hypot(...) < epsilon`. Indexes on `(ts)` and `(lat, lon)`. No ORM. Raw SQL. This is not negotiable — at 4-6 captures/hour across multi-day trips, the dataset is small enough that SQLite is faster than the cognitive overhead of an ORM, and easier to retroactively re-query when the agent learns new questions to ask.

### Position drift and the moving boat

The boat moves. A 10-minute capture covers real distance. The "pin" stored with the echogram row is the position at capture time. The window_start position is interpolated from NMEA track history (linear between known fixes is fine at 1Hz). When you query "what was under us when we caught that fish," you interpolate the boat position to the catch's exact ts.

---

## 4. What NOT to build — premature

These are the sirens. Resist.

- **Real-time streaming pipeline.** The display already scrolls. We capture windows. No need for sub-second latency. 10-min cadence is the entire sampling theory we need; faster just burns disk.
- **CNN / vision model on raw pixels.** Florence-2 and friends are seductive but: (a) they don't reason about echogram physics, (b) the labels don't exist yet, (c) captions from a small model on the cropped PNG + depth scale + bottom detection are 90% as useful for 5% of the complexity. When the vocabulary stabilizes after 50+ catch-linked rows, *then* think about a learned classifier.
- **Per-frame fish blob detection in OpenCV.** The old code's per-frame thresholding was the wrong unit. Blobs are *runs across many pings* — they need window-level analysis, not single-frame thresholding.
- **Message bus / Redis / Kafka.** SQLite + a cron-style trigger is enough. One boat. One capture cadence. No fan-out.
- **Microservices for "echogram-ingest," "vision-service," "agent-brain."** One Python process. Files in, SQLite out, agent queries when it wants. The Captain is the only operator. Latency budget is human minutes, not milliseconds.
- **A "real" web UI before the data is right.** Read from `sqlite3` CLI before you build a dashboard. Every minute on the UI is a minute not on the schema.
- **Auto-calibration of the depth scale via OCR every frame.** Calibrate once per session (when the screen's depth zoom changes), cache, and forget. Re-OCRing 1080px of scale numbers every 10 minutes wastes CPU and creates new failure modes.
- **Multi-band fusion logic** (combining LF and HF into one "best" interpretation). The two bands tell you different things. Keep them separate. The agent reasons about both. Don't pre-fuse and lose information.
- **Spatial indexing with PostGIS / R-tree.** Premature. A `lat BETWEEN x AND y` predicate on a few thousand rows is fine. When you actually have a million rows and the queries get slow, add R-tree. Not before.
- **Captain-facing real-time alerts.** Not until the false-positive rate is known from weeks of data. Premature alerts erode trust faster than no alerts.

---

## 5. Build order — what compounds first

The order matters. Each step makes the next step useful or possible.

### Phase 1: Capture + slice + raw archive (1 day)

- Rewrite `screenshot.py` for the new geometry (full-frame DISPLAY2, slice into LF/HF bands).
- Drop the old `capture.py` dual-cadence. Replace with one 10-minute timer.
- Archive `captures/echogram/{ts}_{lf,hf,full}.png` plus a `{ts}.json` sidecar with NMEA pinned at capture.
- **Compounds**: you now have a filmstrip. Even with no analysis, you can scroll back to "what did the sounder look like when we caught that one?"

### Phase 2: Bottom + scale + band-description schema (1-2 days)

- Implement the band-description dict from section 2 in a new `band_describer.py`.
- One schema, one SQLite table `echogram_bands(ts, band, ...)`.
- Keep the old depth-scale OCR idea but rewrite for new geometry. One-time calibration per session.
- **Compounds**: the agent can now answer "show me hard bottom >40fm" from SQL alone.

### Phase 3: Window-level blob detection (2-3 days)

- Across the 12-min window visible in each band PNG, identify "runs" of similar color and shape. Not per-frame.
- Output: `returns_above_bottom` list per row.
- The hard part: distinguishing *school* (wide, sustained) from *individual fish* (narrow, intermittent) from *noise* (sparse, scattered).
- **Compounds**: the caption now has actual fish descriptions, not "brightness in region X."

### Phase 4: Captain catch entry + join (1 day)

- Minimal CLI: `report_catch.py --species X --depth Y --weight Z` writes to `catches` table.
- Or: a tiny TUI/inline prompt at end of session. Don't build a web app.
- Add the join query from section 3 as `catch_linker.py`.
- **Compounds**: every catch labels a 10-minute echogram window. The labeled dataset starts growing on day one.

### Phase 5: Caption generation + first vocabulary (2-3 days)

- A small template-based caption generator from the band-description dict. Rule-based, not ML. E.g.:
  - "Hard {bottom_contour} bottom at {bottom_depth_fm}fm."
  - "{density} {dominant_color} {shape} {y_top}-{y_bot}fm, {position}."
- Store caption in `echogram_bands.caption`.
- **Compounds**: agent can now do semantic search over moments.

### Phase 6: Agent loop + retroactive re-analysis (ongoing)

- Agent reads `echogram_bands`, joins `catches`, hypothesizes "this shape at this depth on this bottom = this species with confidence X."
- Writes hypotheses to `analyses` table.
- When a new hypothesis is confirmed, **re-runs the caption generator over historical echogram rows** with the new vocabulary. This is the learning loop closing.
- **Compounds**: every catch makes the system better at describing past echograms. The archive compounds in value over time.

### What comes after Phase 6 (and only after)

- Vision model fine-tune, IF the rule-based captions hit a ceiling.
- Fleet synthesis (multi-vessel patterns).
- Real-time alerts (when false-positive rate is known to be acceptable).

---

## 6. The storage schema that makes retroactive re-analysis possible

This is the most important section. If you get this wrong, you can't re-analyze, and the learning loop dies.

### The principle

**The raw PNG and the NMEA pin are immutable.** The band-description (numeric + shape fields + caption) is **regenerable**. Schema must support regeneration without touching raw data.

### Tables (SQLite, one DB)

```sql
-- Raw captures. Append-only. Never UPDATE.
CREATE TABLE captures (
    ts          TEXT PRIMARY KEY,       -- ISO 8601 with seconds
    full_path   TEXT NOT NULL,
    lf_path     TEXT NOT NULL,
    hf_path     TEXT NOT NULL,
    lat         REAL,                   -- pinned NMEA at capture
    lon         REAL,
    sog_kts     REAL,
    cog_deg     REAL,
    nmea_age_s  INTEGER,                -- how stale was the NMEA read
    captured_at TEXT NOT NULL           -- wall-clock at capture
);

-- NMEA track. 1Hz from source, polled separately.
CREATE TABLE nmea_track (
    ts          TEXT PRIMARY KEY,
    lat         REAL NOT NULL,
    lon         REAL NOT NULL,
    sog_kts     REAL,
    cog_deg     REAL
);
CREATE INDEX idx_nmea_ts ON nmea_track(ts);

-- Band description. Regenerable. Has schema_version.
CREATE TABLE echogram_bands (
    ts              TEXT NOT NULL,
    band            TEXT NOT NULL,      -- 'LF' or 'HF'
    schema_version  INTEGER NOT NULL,   -- increments when describer changes
    capture_ts      TEXT NOT NULL,
    lat             REAL,
    lon             REAL,
    sog_kts         REAL,
    depth_scale_max_fm REAL,
    bottom_depth_fm REAL,
    bottom_y_px     INTEGER,
    bottom_color    TEXT,
    bottom_contour  TEXT,
    bottom_roughness_px REAL,
    returns_above_bottom TEXT,          -- JSON blob: list of blobs
    thermocline_present INTEGER,
    thermocline_depths_fm TEXT,         -- JSON list
    caption         TEXT,               -- the searchable text
    described_at    TEXT NOT NULL,
    PRIMARY KEY (ts, band, schema_version)
);
CREATE INDEX idx_bands_ts ON echogram_bands(ts);
CREATE INDEX idx_bands_latlon ON echogram_bands(lat, lon);
CREATE INDEX idx_bands_caption ON echogram_bands(caption);

-- Captain catch reports.
CREATE TABLE catches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    lat         REAL,
    lon         REAL,
    species     TEXT NOT NULL,
    weight_lb   REAL,
    depth_fm    REAL,
    lure        TEXT,
    notes       TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX idx_catches_ts ON catches(ts);
CREATE INDEX idx_catches_species ON catches(species);

-- Agent analyses. Append-only. References other rows by ts+band.
CREATE TABLE analyses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    band            TEXT,
    hypothesis      TEXT NOT NULL,
    confidence      REAL,
    evidence_refs   TEXT,               -- JSON: list of {table, ts, band}
    superseded_by   INTEGER,            -- points to newer analysis id
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_analyses_ts ON analyses(ts);
```

### Why `schema_version` matters

When the describer gets smarter (Phase 6: "I learned that arches on hard bottom at 8-12fm off bottom in 40fm of water tend to be lake trout"), you regenerate captions for *historical* rows. You do NOT overwrite the old rows. You INSERT new rows with `schema_version + 1`. Now you can query: "what did the old describer say about this moment vs. the new one?" This is how you debug the learning loop and audit what the system used to believe.

### Why raw PNGs are immutable

PNG files in `captures/echogram/` are never edited, never moved, never re-encoded. If disk fills up, oldest are deleted by a retention job — but never modified. This guarantees that *any* future re-analysis can re-derive the band-description from the original pixels. The PNGs are the ground truth. Everything else is commentary.

### Why JSON-blob fields where used

`returns_above_bottom` and `thermocline_depths_fm` are lists of variable-length, heterogeneous records. The schema design tradeoff: normalize them into child tables (more joins, more rigid) or store as JSON text (less queryable but flexible during iteration). **Choose JSON during prototyping** (first 30 days). Promote to child tables only when you find yourself writing the same JOIN repeatedly. Premature normalization kills iteration speed.

### Disk budget

1920x1080 PNG, 12 captures/hour, 24h retention = ~70 captures/day. At ~1MB each, ~70MB/day. LF+HF slices ~400KB each, so ~50MB/day in slices. Full frames compress to JPEG at ~200KB, dropping to ~15MB/day. A week of full-resolution retention = 500MB. A month of just slices = 1.5GB. SQLite stays tiny. This is not a disk problem.

---

## 7. The minimal working stack (the actual code we write)

```
screenshot.py      -- DISPLAY2 capture, slice to LF/HF/full, sidecar JSON
band_describer.py  -- one PNG in, one band-description dict out
captioner.py       -- dict in, caption string out
storage.py         -- SQLite tables above, insert helpers, query helpers
catch_cli.py       -- minimal catch report entry
catch_linker.py    -- join catches <-> echogram windows
run_loop.py        -- the timer (was capture.py); 10-min cadence
```

Replace these old files:
- `capture.py` -> `run_loop.py` (one cadence, not two)
- `sounder_analyzer.py` -> `band_describer.py` (window-level, not frame-level)
- `screenshot.py` -> rewrite for new geometry, add slicing
- `config.py` -> update display constants to new LF/HF layout

Keep:
- `anomaly_logger.py` (the schema is fine; re-pipe inputs)
- `bathy_contours.py`, `contour_query.py` (still useful for contour cross-checks)
- `logger.py` (general utilities; repurpose for `storage.py` or fold in)

---

## 8. The single test that proves it works

```
1. Captain goes fishing for 4 hours.
2. Pipeline captures 24 windows, slices them, describes them.
3. Captain reports 5 catches via catch_cli.py.
4. catch_linker.py joins each catch to the visible echogram window.
5. Agent queries: "show me all moments where we saw dense arches
   8-12fm off bottom in 35-50fm of water on hard bottom."
6. Result: a list of (ts, band, caption) plus which catches fell in
   those windows.
7. Captain looks at one of those moments. "Yeah, that's exactly what
   it looked like when we caught those lakers."
```

If step 7 makes the Captain nod, the pipeline works. Everything else is optimization.

---

## 9. What this manifesto is NOT

- Not a research paper.
- Not a feature checklist.
- Not a pitch for ML.
- Not an apology for SQLite.

It's a contract with the future: when the agent gets smarter, the archive still answers. When the describer changes, history isn't lost. When the Captain asks a new question, the schema already supports it.

Build the filmstrip first. Then teach it to talk. Then teach it to listen.