# TZ Pro Sounder Echogram Capture & Analysis Pipeline v2.0
## Architecture Document — Dual-Band Full-Screen Echogram System

**Author:** Kimi K3 Architecture Sub-Agent  
**Date:** 2026-07-17  
**Vessel:** F/V EILEEN, Ketchikan, Alaska  
**Status:** Founding-day pivot — the old thin strip is dead, long live the dual-band scroll  

---

## 0. THE SHIFT — Why This Document Exists

The old pipeline was a periscope: a 370×900px slit cut from the right edge of the screen, captured every 30 seconds, analyzed by brute OpenCV thresholds, logged as JSONL. It worked. It proved the concept. But it was reading the sounder like a man reading a newspaper through a mail slot.

Today the second monitor changed. It is no longer a navigation dashboard with a sounder widget. It is a **dedicated full-screen dual-band scrolling echogram**:

- **Monitor:** DISPLAY6, 1920×1080, offset (1920, 0)
- **Left Band:** x ≈ 8–945, low frequency, ~930px wide, 12+ minutes of scroll history
- **Divider:** x = 945, white vertical line
- **Right Band:** x ≈ 950–1890, high frequency, ~940px wide, 12+ minutes of scroll history
- **Depth Scale:** x ≈ 1870–1890, the vertical fathom ruler

Each vertical column is one ping. The full width is rolling time. This is not a screenshot anymore. It is a **time-series sensor** disguised as an image. The architecture must treat it that way.

This document is the blueprint for that treatment.

---

## 1. FIRST PRINCIPLES — K3 Thinking

Three layers govern every decision here:

1. **The water does not care about your abstraction.** The signal is messy, palette-tuned, display-dependent, and full of ghosts. The system must be empirical first, elegant second.
2. **A capture without context is a postcard, not evidence.** Every frame must be welded to position, motion, time, and eventually outcome. The correlation graph is as important as the image.
3. **Learning is retroactive or it is not learning.** The agent does not get smarter only about future frames. It must be able to look back at yesterday's "unidentified blob" and rename it "chum salmon" once the Captain tells it what happened.

If a design choice violates any of these three principles, it is wrong.

---

## 2. THE DAW TRACK PARADIGM

Stop thinking like a monitoring system. Start thinking like a digital audio workstation. The fishing day is a multi-track session:

| Track | Name | Source | Cadence | Role |
|-------|------|--------|---------|------|
| **T1** | Echogram Capture | DISPLAY6 full-screen | Every 10 min, overlapping windows | The raw song |
| **T2** | NMEA Position/SOG | hermitd / vessel endpoint | Continuous, sampled at capture | The map grid |
| **T3** | Captain Catch Reports | Voice/text/supervised input | Event-driven | The ground truth labels |
| **T4** | Agent Text Analysis | Local vision + summarizer | Per capture + retroactive | The vocabulary engine |

The magic is not any single track. The magic is the crossfade between them. A good echogram description is meaningless until you know where the boat was, how fast it was moving, and what came up on the gear ten minutes later.

This paradigm gives us four concrete contracts:

- **T1 stores images**, but indexes them as time windows, not files.
- **T2 stores vessel state snapshots**, frozen at the instant of capture.
- **T3 stores catch events**, with species, count, depth, and a link back to recent windows.
- **T4 stores searchable text summaries**, rewritten whenever the vocabulary improves.

---

## 3. CAPTURE PIPELINE — Full-Frame, Dual-Band, NMEA-Synced

### 3.1 What to Capture

The old code captured a thin strip. The new code captures the **full 1920×1080 frame** of DISPLAY6 every **10 minutes**. Why 10 minutes?

- 12+ minutes of history are visible on screen.
- A 10-minute cadence gives ~2 minutes of overlap between consecutive frames, preventing events from falling into the seam.
- Disk cost: ~180 KB/frame PNG × 6 frames/hour = ~1 MB/hour. Trivial.
- The full frame is the archival master. Never throw it away.

Old config replacement:

```python
# config.py — new dual-band layout
DISPLAY6_OFFSET_X = 1920
DISPLAY6_OFFSET_Y = 0
DISPLAY6_WIDTH = 1920
DISPLAY6_HEIGHT = 1080

# Bands
BAND_LEFT_X1, BAND_LEFT_X2 = 8, 945
BAND_RIGHT_X1, BAND_RIGHT_X2 = 950, 1890
BAND_DIVIDER_X = 945
DEPTH_SCALE_X1, DEPTH_SCALE_X2 = 1870, 1890

# Cadence
ECHOGRAM_INTERVAL_SEC = 600      # 10 minutes
ECHOGRAM_OVERLAP_SEC = 120       # 2 min safety margin
```

### 3.2 Crop Strategy

From every full frame, derive three children:

1. **`{ts}_full.png`** — the raw 1920×1080 archival frame.
2. **`{ts}_lf.png`** — left band crop, low frequency, 937×1080.
3. **`{ts}_hf.png`** — right band crop, high frequency, 940×1080.
4. **`{ts}_scale.png`** — depth scale strip, 20×1080, for OCR.

Store the full frame and the band crops. Discard nothing except intermediate scratch. The band crops are what the analyzer eats. The full frame is what the human replay uses.

```python
# screenshot.py — new dual-band crop helpers
def crop_left_band(full_path: Path) -> Path:
    return crop_region(full_path, (BAND_LEFT_X1, 0, BAND_LEFT_X2, DISPLAY6_HEIGHT), tag="lf")

def crop_right_band(full_path: Path) -> Path:
    return crop_region(full_path, (BAND_RIGHT_X1, 0, BAND_RIGHT_X2, DISPLAY6_HEIGHT), tag="hf")

def crop_depth_scale(full_path: Path) -> Path:
    return crop_region(full_path, (DEPTH_SCALE_X1, 0, DEPTH_SCALE_X2, DISPLAY6_HEIGHT), tag="scale")
```

### 3.3 NMEA Sync

The current `read_nmea()` in `capture.py` hits `http://127.0.0.1:8654/vessel`. Keep that. But freeze the sample **at the exact instant the screenshot is triggered**, not when analysis finishes. PowerShell capture takes ~1–2 seconds. NMEA can drift. Stamp the metadata with the capture timestamp, not the log timestamp.

Proposed contract:

```python
@dataclass
class VesselSnapshot:
    ts_capture: datetime          # when the screenshot fired
    ts_read: datetime             # when NMEA was sampled
    lat: float | None
    lon: float | None
    sog_kts: float | None
    cog_deg: float | None
    source: str = "hermitd/vessel"
```

Store one snapshot per capture, embedded in the frame's metadata file.

### 3.4 Capture Loop Rewrite

The old dual-cadence loop (30s sounder + 4min full) becomes a single-cadence loop:

```python
async def echogram_loop():
    while True:
        now = time.time()
        if now - _last_capture >= ECHOGRAM_INTERVAL_SEC:
            vessel = sample_vessel_state()
            full_path = capture_full()
            if full_path:
                stamp = datetime.now(timezone.utc)
                lf = crop_left_band(full_path)
                hf = crop_right_band(full_path)
                scale = crop_depth_scale(full_path)
                meta = build_capture_metadata(full_path, lf, hf, scale, vessel, stamp)
                await analyze_and_log(meta)
                _last_capture = now
        await asyncio.sleep(5)
```

No more sounder-only captures. The full frame is the primitive. Band crops are derivatives. Analysis is always dual-band.

---

## 4. ANALYZER — Reading the Scroll

The old `sounder_analyzer.py` treated the image as a static panel. The new analyzer treats each band as a **space-time matrix**: x = time, y = depth, color = return intensity. The goal is to extract structure, not just count bright pixels.

### 4.1 Depth Scale Calibration

The depth scale strip (x ≈ 1870–1890) is the only source of absolute depth. The old code used Tesseract on a 20px crop. Continue, but make it robust:

1. **OCR the scale strip** with Tesseract `--psm 6 digits`.
2. **Validate** that readings are monotonically increasing top-to-bottom.
3. **Interpolate** a pixel-y → fathom mapping across the full 1080px height.
4. **Cache** the calibration per session; re-OCR only if readings look wrong.
5. **Fallback** to the previous valid calibration, not a hard-coded 80 fm.

If the scale reads `[0, 20, 40, 60, 80]` at pixel rows `[0, 270, 540, 810, 1080]`, then depth at any y is a linear interpolation. Store this mapping with the frame metadata.

### 4.2 Bottom Ridge Detection

The bottom is not a line; it is a **ridge** — a high-intensity manifold that may slope, split, or disappear under hard returns. Per band:

1. For each column x, scan bottom-up for the first sustained strong return (RGB total > `RGB_THRESHOLD_STRONG`, or local maxima above `RGB_THRESHOLD_FISH` over a vertical window).
2. Apply a **temporal consistency filter**: the bottom should not jump 50 fm between adjacent pings unless the boat is literally falling off a ledge. Median-filter across ~20 columns.
3. Classify bottom **hardness** by color and **roughness** by vertical variance of the ridge.
4. Detect **bottom multiples** — faint ghost ridges below the true bottom, repeating at regular depth intervals. Do not count them as structure.

Output per band:

```json
{
  "bottom_ridge": {
    "pixel_y": [540, 541, 539, ...],
    "depth_fm": [42.0, 42.1, 41.9, ...],
    "mean_depth_fm": 42.0,
    "hardness": "hard",
    "hardness_score": 0.87,
    "roughness_px": 4.2,
    "confidence": "high",
    "multiples_detected": false
  }
}
```

### 4.3 Fish School Classification — Blob, Arch, Cloud

This is the heart of the new analyzer. The old code counted bright pixels and called it "fish." The new code classifies **shapes**:

| Shape | Visual Signature | Biological Interpretation |
|-------|------------------|---------------------------|
| **Blob** | Compact, dense, rounded mass | Bait ball, dense school holding tight |
| **Arch** | Curved upside-down U, often individual or small group | Single fish or pod passing through the beam |
| **Cloud** | Diffuse, scattered, low intensity | Plankton, scattered fish, thermally mixed layer |
| **Layer** | Horizontal band, uniform | Thermocline, density interface, or deep scattering layer |
| **Wisp** | Thin vertical streak | Surface clutter, bubbles, or transient target |

Detection pipeline per band:

1. **Background suppression** — remove the dark blue baseline using the palette model.
2. **Segmentation** — connected-component analysis on pixels above `RGB_THRESHOLD_FISH`.
3. **Feature extraction** for each component:
   - Bounding box (width in pings, height in fm)
   - Aspect ratio
   - Solidity
   - Mean intensity and color
   - Vertical centroid depth
   - Distance above bottom ridge
4. **Shape classifier** — rule-based first, learned later:
   - `arch`: convex hull shaped like an inverted U, height > width, isolated.
   - `blob`: compact, high solidity, roughly circular, intense.
   - `cloud`: low solidity, diffuse, large area, low intensity.
   - `layer`: horizontal elongation, low vertical variance, spans many pings.
   - `wisp`: very narrow, vertical, near surface.

Output per detected object:

```json
{
  "returns": [
    {
      "id": "lf_0037",
      "band": "lf",
      "shape": "blob",
      "bbox_pings": [120, 145],
      "bbox_depth_fm": [28.0, 35.0],
      "centroid_depth_fm": 31.5,
      "height_above_bottom_fm": 10.5,
      "intensity_avg": 218,
      "intensity_max": 255,
      "dominant_color": "orange",
      "solidity": 0.82,
      "confidence": 0.71,
      "label": "unidentified_blob"
    }
  ]
}
```

### 4.4 Water Column Stratification

Between surface and bottom, the water column has structure. The analyzer should report:

- **Surface blanking zone** — top ~5–10% of the image where the transducer noise lives.
- **Mixed layer depth** — depth where return texture first changes.
- **Thermocline/density interfaces** — horizontal bands of elevated return, detected by row-wise variance and brightness.
- **Deep scattering layer** — persistent weak returns above bottom, especially at dawn/dusk.

This is not just ecology. It is **context** for interpreting fish returns**. A blob at 30 fm means something different in a stratified column than in a well-mixed one.

### 4.5 Dual-Band Fusion

The same water column is shown in LF and HF. The analyzer should **fuse** them:

- LF sees deeper and through bubbles better. HF sees finer detail.
- If a blob appears in both bands at the same depth range, confidence increases.
- If HF shows arches inside an LF blob, call it a school of individual fish.
- If LF shows a cloud HF misses, it may be deep or thermally masked.

Fusion output:

```json
{
  "fused_objects": [
    {
      "object_ids": ["lf_0037", "hf_0041"],
      "shape": "blob_with_internal_arches",
      "depth_fm": [28.0, 35.0],
      "confidence": 0.84,
      "interpretation": "dense school, likely individual fish visible in HF"
    }
  ]
}
```

---

## 5. TEXT SUMMARY SCHEMA — The Captain's Log Entry

Every echogram capture becomes a **text entry** written in the voice of a competent deckhand reporting to the Captain. This text is the searchable, LLM-readable distillation of the image.

### 5.1 Schema

```json
{
  "entry_id": "eg_20260717_101500",
  "ts_capture": "2026-07-17T10:15:00+00:00",
  "ts_local": "2026-07-17T02:15:00-08:00",
  "vessel": {
    "lat": 55.7859,
    "lon": -131.5270,
    "sog_kts": 2.3,
    "cog_deg": 265
  },
  "window": {
    "duration_sec": 600,
    "overlap_prev_sec": 120,
    "bands": ["lf", "hf"]
  },
  "water_column": {
    "surface_blank_fm": 3.0,
    "mixed_layer_depth_fm": 12.0,
    "thermoclines": ["weak layer at 18 fm"],
    "stratification": "moderate"
  },
  "bottom": {
    "mean_depth_fm": 42.0,
    "range_fm": [40.5, 43.0],
    "type": "hard_rock",
    "roughness": "low",
    "confidence": "high"
  },
  "returns": [
    {
      "shape": "blob",
      "depth_fm": [28, 35],
      "band": "both",
      "color": "orange",
      "intensity": "strong",
      "count_estimate": "school",
      "label": "unidentified_blob",
      "confidence": 0.71
    }
  ],
  "summary_text": "Low frequency and high frequency bands show a hard bottom at 42 fathoms, fairly flat. Strong orange blob from 28 to 35 fathoms, both bands, roughly school-sized. No sharp thermocline. Vessel moving 2.3 kts at 265°. Labels pending.",
  "tags": ["hard_bottom", "orange_blob", "28-35fm", "lf", "hf", "school_sized"],
  "raw_files": {
    "full": "eg_20260717_101500_full.png",
    "lf": "eg_20260717_101500_lf.png",
    "hf": "eg_20260717_101500_hf.png",
    "scale": "eg_20260717_101500_scale.png"
  },
  "derived_from": null,
  "reanalysis_version": 1
}
```

### 5.2 Text Generation

The `summary_text` is generated by a lightweight template engine, not an LLM. Why? Speed, determinism, and cost. The agent runs on a boat with intermittent power. Every frame does not need a $0.002 API call.

Template rules:

- Lead with bottom: depth, type, roughness.
- Then returns: shape, depth range, band, color, intensity.
- Then water column: stratification, thermoclines.
- End with vessel motion.
- Keep it under 150 words. A log entry should be scannable.

LLM summarization is deferred to **retroactive passes** (see Section 6) or on-demand queries.

### 5.3 Tags

Tags are the search index. They must be normalized. Proposed vocabulary:

- Depth buckets: `0-10fm`, `10-20fm`, ..., `90-100fm`, `100fm+`
- Shape: `arch`, `blob`, `cloud`, `layer`, `wisp`, `ridge`, `multiple`
- Color/intensity: `blue`, `cyan`, `yellow`, `orange`, `red`, `weak`, `medium`, `strong`
- Band: `lf`, `hf`, `both`
- Bottom: `hard`, `medium`, `soft`, `mud`, `rock`, `rough`, `flat`
- Status: `labeled`, `unidentified`, `reanalysis_pending`

These tags power the Captain's query interface: *"Show me orange blobs at 30-40 fm over hard bottom from last week."*

---

## 6. MULTI-TRACK CORRELATION — Time, Space, and Retroaction

### 6.1 Temporal Alignment

All four tracks share a common timeline. Every event has a UTC timestamp. Align by nearest timestamp, not by assumption.

```
Timeline (UTC)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
10:15:00  T1  Echogram capture window A begins
10:15:02  T2  Vessel snapshot: lat/lon/SOG/COG
10:19:30  T3  Captain reports: "6 coho, 35 fm"
10:20:00  T1  Echogram capture window B begins (overlap 120s with A)
10:24:00  T4  Agent reanalysis: window A relabeled "coho, conf 0.61"
```

### 6.2 Catch Event Linking

When the Captain reports a catch, the system links it to the **nearest prior echogram windows**. Not one window — a window of windows. Use a lookback of up to 30 minutes and a spatial radius based on SOG (e.g., a boat moving 2 kts covers 1 nm in 30 min).

Catch event schema:

```json
{
  "event_id": "catch_20260717_101930",
  "ts_report": "2026-07-17T10:19:30+00:00",
  "ts_catch_est": "2026-07-17T10:14:00+00:00",
  "species": "coho",
  "count": 6,
  "depth_fm": 35,
  "gear": "trolling",
  "position": {"lat": 55.7861, "lon": -131.5273},
  "linked_entries": ["eg_20260717_101500", "eg_20260717_100500"],
  "link_method": "spatiotemporal_nearest"
}
```

### 6.3 Label Propagation

A catch report is a **weak label** for all linked echogram entries. The system does not assume every object in the window is a coho. It assigns a propagated label with low confidence and lets the vocabulary engine refine it.

```json
{
  "label": "coho_salmon",
  "source": "captain_report",
  "confidence": 0.35,
  "propagation_radius_nm": 0.8,
  "propagation_time_min": 25
}
```

### 6.4 Retroactive Re-Analysis

This is the recursive heart of the system. Whenever one of these happens:

- The Captain supplies a new label.
- The vocabulary engine learns a new pattern.
- The analyzer shape classifier is updated.
- The depth scale calibration is corrected.

...the system queues affected past entries for re-analysis. Re-analysis produces:

1. A new `summary_text`.
2. Updated `returns` with new labels/confidences.
3. A new `reanalysis_version`.
4. A `derived_from` pointer to the prior entry (never overwrite; append to history).

Storage is **immutable**. Old entries stay. New entries reference them. This gives the Captain an audit trail: *"On day 1 you called this unidentified. On day 5 you called it chum. Why?"*

### 6.5 Query Engine

The correlation data enables questions like:

- *"What did the sounder look like 10 minutes before we hit that coho school?"*
- *"Show me all hard-bottom 40-fm windows where orange blobs appeared and we later caught fish."*
- *"Has the vocabulary ever labeled something at 30-40 fm as chum with confidence > 0.7?"*

Use SQLite for structured correlation queries, not JSONL grep. More on storage in Section 8.

---

## 7. VOCABULARY BUILDING — From "Unidentified Blob" to "Chum Salmon, Conf 0.73"

### 7.1 The Vocabulary as a Graph

The vocabulary is not a list. It is a **conditional probability graph**:

```
[visual signature] --confidence--> [biological hypothesis] --outcome--> [species label]
```

Example nodes and edges:

- `orange_blob_28_35fm_hard_bottom` → `dense_school` → `chum_salmon` (conf 0.73)
- `arches_scattered_15_25fm` → `individual_fish` → `coho_salmon` (conf 0.51)
- `cloud_diffuse_5_15fm` → `bait_or_plankton` → `no_label` (conf 0.22)

### 7.2 Learning Loop

1. **Initial state:** Every detected object is `unidentified_blob` / `unidentified_arch` / etc.
2. **Captain reports a catch:** Linked objects get a weak species label.
3. **Accumulation:** Over days, the system counts co-occurrences of visual signatures and reported species.
4. **Thresholding:** When a signature → species pair exceeds a confidence threshold (start at 0.6, tune by species), it graduates from `unidentified_*` to a named label.
5. **Retroaction:** Named labels are applied backward to matching historical objects, with decaying confidence based on age.

### 7.3 Confidence Model

Confidence is not the CNN softmax. It is a **fishing-specific score** that weights:

- Visual classifier confidence (0–1)
- Number of confirming catch reports (n)
- Spatial/temporal proximity to catch (closer = higher)
- Consistency across bands (both bands = higher)
- Seasonal prior (some species run at predictable times)

Proposed formula (iterative):

```
conf = visual_conf × (1 - exp(-n/3)) × band_bonus × proximity_decay
```

Where `band_bonus` is 1.15 if both bands agree (capped at 1.0), and `proximity_decay` falls off with distance in space/time from the catch report.

### 7.4 Vocabulary Schema

```json
{
  "pattern_id": "pat_orange_blob_28_35_hard",
  "created": "2026-07-20T08:00:00+00:00",
  "last_updated": "2026-07-22T18:00:00+00:00",
  "visual_signature": {
    "shapes": ["blob"],
    "depth_fm": [28, 35],
    "colors": ["orange", "red"],
    "bottom_types": ["hard", "medium"],
    "bands": ["lf", "hf"]
  },
  "species_hypotheses": [
    {"species": "chum_salmon", "confidence": 0.73, "n_reports": 5},
    {"species": "coho_salmon", "confidence": 0.18, "n_reports": 1}
  ],
  "evidence_entries": ["eg_20260717_101500", "eg_20260718_093000", ...]
}
```

### 7.5 Counterfactual Learning

Not every report is positive. The Captain also reports **skunks** — empty gear, no fish. Skunks are negative labels. If a visual signature frequently appears before skunks, its confidence in all species hypotheses should drop. The system must learn what **not** to call fish.

---

## 8. STORAGE — Images, Text, NMEA, Catch Events

### 8.1 Directory Layout

```
workspace/
├── captures/
│   └── 2026/
│       └── 07/
│           └── 17/
│               ├── eg_20260717_101500_full.png      # archival master
│               ├── eg_20260717_101500_lf.png        # left band
│               ├── eg_20260717_101500_hf.png        # right band
│               ├── eg_20260717_101500_scale.png     # depth scale
│               └── eg_20260717_101500_meta.json     # capture metadata
├── memory/
│   ├── index/
│   │   ├── echogram_entries.jsonl                   # searchable summaries
│   │   ├── vocabulary.jsonl                         # learned patterns
│   │   └── reanalysis_log.jsonl                     # retroaction audit
│   ├── daily/
│   │   └── 2026-07-17.md                            # human-readable digest
│   └── observations/                                # legacy JSONL (keep)
└── bathymetry/
    └── anomalies.db                                 # existing SQLite
```

### 8.2 Image Downsampling

Full frames are ~180 KB PNG. Band crops are similar. At 6 frames/hour × 12 hours/day × 180 KB × 3 files = ~40 MB/day. Over a 90-day season = ~3.6 GB. Acceptable for a local SSD.

Still, create a **thumbnail** for fast preview: 480×270 JPEG, ~30 KB.

Do **not** downsample the analytical crops. The depth scale OCR and shape classifier need native resolution.

### 8.3 Searchable Text

The `echogram_entries.jsonl` is the primary search index. Each line is a structured entry with tags and summary. SQLite is better for complex correlation queries. Proposed tables:

```sql
CREATE TABLE echogram_entries (
    entry_id TEXT PRIMARY KEY,
    ts_capture TEXT NOT NULL,
    lat REAL,
    lon REAL,
    sog_kts REAL,
    cog_deg REAL,
    bottom_mean_depth_fm REAL,
    bottom_type TEXT,
    summary_text TEXT,
    tags TEXT,                    -- JSON array
    raw_files TEXT,               -- JSON object
    reanalysis_version INTEGER DEFAULT 1,
    derived_from TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE returns (
    return_id TEXT PRIMARY KEY,
    entry_id TEXT NOT NULL,
    band TEXT,
    shape TEXT,
    depth_min_fm REAL,
    depth_max_fm REAL,
    centroid_depth_fm REAL,
    color TEXT,
    intensity TEXT,
    label TEXT,
    confidence REAL,
    FOREIGN KEY (entry_id) REFERENCES echogram_entries(entry_id)
);

CREATE TABLE catch_events (
    event_id TEXT PRIMARY KEY,
    ts_report TEXT NOT NULL,
    ts_catch_est TEXT,
    species TEXT,
    count INTEGER,
    depth_fm REAL,
    gear TEXT,
    lat REAL,
    lon REAL,
    linked_entries TEXT,          -- JSON array
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE vocabulary_patterns (
    pattern_id TEXT PRIMARY KEY,
    visual_signature TEXT,        -- JSON
    species_hypotheses TEXT,      -- JSON
    evidence_entries TEXT,        -- JSON
    created_at TEXT,
    updated_at TEXT
);
```

### 8.4 NMEA Snapshots

NMEA is continuous, but we only need snapshots at capture time. Store them embedded in the frame metadata and also in a dedicated table for fast vessel-state queries.

```sql
CREATE TABLE vessel_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    ts_capture TEXT NOT NULL,
    ts_read TEXT,
    lat REAL,
    lon REAL,
    sog_kts REAL,
    cog_deg REAL,
    source TEXT
);
```

### 8.5 Retention Policy

- Keep full-resolution archival frames for **one season**.
- After the season, compress older frames to lossy WebP at 90% quality.
- Never delete the JSONL/SQLite entries — text is cheap and forever.
- Reanalysis history is permanent.

---

## 9. IMPLEMENTATION ROADMAP — Build First, Defer Later

### 9.1 Phase A: New Capture Primitive (Week 1)

**Build first.** Without this, nothing else matters.

- [ ] Update `config.py` with dual-band layout and 10-minute cadence.
- [ ] Rewrite `screenshot.py` with `crop_left_band()`, `crop_right_band()`, `crop_depth_scale()`.
- [ ] Rewrite `capture.py` loop to single 10-minute full-frame cadence.
- [ ] Ensure NMEA snapshot is taken at capture trigger time.
- [ ] Save `{ts}_full.png`, `{ts}_lf.png`, `{ts}_hf.png`, `{ts}_scale.png`, `{ts}_meta.json`.
- [ ] Basic sanity check: can we reliably capture 6 frames/hour without missing?

### 9.2 Phase B: Dual-Band Analyzer (Week 2)

**Build second.** This turns images into structured observations.

- [ ] Calibrate depth scale from `scale.png` with validation and fallback.
- [ ] Implement bottom ridge detection per band with temporal smoothing.
- [ ] Implement connected-component segmentation for returns.
- [ ] Implement shape classifier (blob/arch/cloud/layer/wisp) — rule-based v1.
- [ ] Implement dual-band fusion.
- [ ] Output new analysis schema to JSON.

### 9.3 Phase C: Captain's Log Text & Storage (Week 3)

**Build third.** This makes the data searchable and human-readable.

- [ ] Implement text summary generator from analysis schema.
- [ ] Define normalized tag vocabulary.
- [ ] Create `echogram_entries.jsonl` and SQLite schema.
- [ ] Port old `logger.py` to write entries + tags.
- [ ] Generate daily markdown digest.

### 9.4 Phase D: Multi-Track Correlation (Week 4)

**Build fourth.** This connects echograms to the real world.

- [ ] Implement catch event input (CLI or simple voice/text webhook).
- [ ] Implement spatiotemporal linking of catches to echogram entries.
- [ ] Implement label propagation with weak confidence.
- [ ] Implement retroactive re-analysis queue.
- [ ] Add query interface: "show entries near catch X" / "entries with tag Y before catch Z".

### 9.5 Phase E: Vocabulary Engine (Month 2)

**Build fifth.** This is where the system starts to learn.

- [ ] Accumulate signature → species co-occurrence counts.
- [ ] Implement confidence scoring with band bonus and proximity decay.
- [ ] Graduate patterns from `unidentified_*` to named species labels.
- [ ] Apply retroactive re-labeling.
- [ ] Handle skunks / negative labels.

### 9.6 Phase F: Advanced Vision (Month 3+)

**Defer.** Do not reach for Florence-2 or a custom CNN until the rule-based pipeline is solid and the Captain has labeled enough data.

- [ ] Train or fine-tune a small classifier on accumulated labeled crops.
- [ ] Add Florence-2 / local VL model for on-demand deep description.
- [ ] Add anomaly detection comparing sounder bottom to chart contours (this already exists; rewire to new schema).
- [ ] Build web DAW-style replay dashboard.

### 9.7 Phase G: Autonomous Deployment (Long Term)

**Defer indefinitely.** This is the vision, not the next ticket.

- [ ] Self-installation guide generation.
- [ ] Cross-vessel model transfer.
- [ ] Fleet-scale aggregation.

---

## 10. RISK AND EDGE CASES

### 10.1 The Display Changes Again

TZ Pro layouts change. Transducer settings change. The depth scale might move. The white divider might shift. The system must detect these changes and alert, not silently fail.

**Mitigation:** Add a layout calibration capture on startup. Verify the divider is at x=945, the depth scale strip contains numbers, and the bands contain non-uniform signal. If checks fail, fall back to manual coordinate input and log a warning.

### 10.2 NMEA Drops Out

The NMEA bridge is already battle-tested, but GPS can lose fix. If `lat/lon/SOG` are missing at capture time, still capture the image. Mark the entry as `position_missing`. Do not throw away the frame.

### 10.3 The Captain Forgets to Report

Catch reports are sparse and noisy. The vocabulary engine must tolerate missing labels. Use positive reports when available; do not assume absence of report means absence of fish.

### 10.4 Day/Night and Tide Artifacts

Thermoclines strengthen. Bioluminescence or plankton blooms create false clouds. Tide changes move the bottom ridge. The system must learn **seasonal priors** and not overfit to a single day.

### 10.5 GPU Ebb and Flow

If Florence-2 or another GPU model is added later, it will contend with other boat systems. Follow the existing philosophy: **surf the tide**. Queue heavy inference during low-load periods. Fall back to CPU rule-based analysis if GPU is busy.

---

## 11. THE INVARIANTS REVISITED

This new architecture does not violate the project's existing invariants. It reinforces them:

1. **Open source.** All new modules are plain Python, SQLite, PNG, JSON.
2. **Captain is customer zero.** Every feature is built for his actual display and his actual fishing day.
3. **The sounder is the only thing worth reading off the screen.** We still read NMEA for everything else.
4. **Copilots wear blinders.** This document is for the sounder copilot only.
5. **The tool must disappear.** Ten-minute capture, searchable logs, retroactive learning — the Captain does not operate it; it operates around him.
6. **The repo is the seed.** The schema and vocabulary persist across seasons.
7. **Don't fight the tide.** Rule-based first, learned second, GPU last.
8. **Charts, not maps.** Every pass updates the vocabulary. The chart is never finished.
9. **Keep pushing.** Build Phase A this week. Deploy before it is perfect.

---

## 12. CLOSING — What This Actually Builds

The old system asked: *"What does the sounder look like right now?"*

The new system asks: *"What does this water teach us over time?"*

It is not a screenshot tool. It is a **fishing memory**. It watches the scroll, reads the ridge, classifies the shapes, links them to position and catch, and slowly learns to name the things the Captain already sees but cannot always explain.

The goal is not to replace the Captain's eye. The goal is to give that eye a searchable, retroactive, vocabulary-building prosthetic — until the day the system says *"solid orange blob, 30-40 fm, LF → chum salmon, conf: 0.73"* and the Captain nods and says *"yep."*

That is the sounder copilot. That is what we build.

---

*End of architecture document.*
*Next action: implement Phase A.*
