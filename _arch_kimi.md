# ōkimi — The Sounder Archivist
## A New Capture / Analysis Pipeline for the Dual-Band Echogram DAW

*The old system crunched a thin strip. The new one watches the whole scroll — both bands, 12 minutes of history, every ping. This is the difference between reading a single headline and reading the front page.*

> **ōkimi** (大君) — "Great Lord," the one who keeps the record. In old Japanese, the archivist who sees all, forgets nothing, and speaks only when there's something worth saying.

---

## Preamble: Why Burn It Down

The v1 pipeline (July 15) was built for a specific constraint: TZ Pro in a full chart+sounder layout where the sounder panel was a thin 370×900px strip on the right edge. That constraint is gone. TZ Pro is now full-screen dual-band sounder. We have 1920×1080 pixels of **pure scrolling echogram history** — two bands, each showing 12+ minutes of transducer pings, every column a new ping, a rolling filmstrip of everything that's passed beneath the keel.

The old pipeline was a **sensor**. This needs to be an **archivist**.

A sensor reads the current state: "depth = 53.2 fm, fish = 3656 pixels." An archivist reads the history: "over the last 12 minutes, the bottom rose from 55 fm to 48 fm, two thermoclines appeared and dissipated, a dense school passed through at 30-35 fm on both bands, the bottom type transitioned from hard to soft at 09:14."

These are fundamentally different operations. The old code assumed each capture was an independent measurement. It punched through with OpenCV thresholds, extracted numbers, logged them, and forgot. The new pipeline treats each capture as a **window into an ongoing scroll** — overlapping, sequential, narratable.

That changes everything: the cadence, the analysis depth, the output format, the storage strategy, the learning loop.

---

## 1. Capture Pipeline — "The Archivist's Desk"

### 1.1 Screen Geometry

TZ Pro is full-screen on DISPLAY6 (1920×1080 at X=1920, Y=0). In dual-band sounder mode:

```
┌─────────────────────────────────────────────────────────────┐
│  ┌────────────────────┐   │   ┌────────────────────┐       │
│  │                    │   │   │                    │       │
│  │    LOW FREQ        │   │   │    HIGH FREQ       │       │
│  │    (50 kHz)        │   │   │    (200 kHz)       │       │
│  │                    │   │   │                    │       │
│  │   Scrolling        │  w  │   Scrolling          │    t  │
│  │   echogram         │  h  │   echogram           │    o  │
│  │   ~12 min history  │  i  │   ~12 min history   │    o  │
│  │                    │  t  │                      │    l  │
│  │                    │  e  │                      │    b  │
│  │                    │     │                      │    a  │
│  │                    │     │                      │    r  │
│  └────────────────────┘     └──────────────────────┘       │
│       x~8 to ~945              x~950 to ~1890              │
│                                                             │
│                    Status / Data bar (bottom)               │
└─────────────────────────────────────────────────────────────┘
```

**Known dimensions (to calibrate via first capture):**

| Feature | Approx X range | Notes |
|---------|---------------|-------|
| Left band | 8 – 945 | ~937px wide, LF 50 kHz |
| Vertical divider | 945 – 950 | ~5px white line |
| Right band | 950 – 1890 | ~940px wide, HF 200 kHz |
| Status bar | 1000 – 1080 | Text data, depth scale info |
| Band depth scale | Right 15-20px of each band | Tick marks + numbers |

**Full capture**: 1920×1080, PNG, timestamped filename.

### 1.2 Cadence: Every 10 Minutes, Overlapping

At 10 minutes between captures and 12 minutes of visible history per band, each capture overlaps the previous one by **2 minutes** (12 - 10 = 2). This is deliberate:

| Property | Value | Why |
|----------|-------|-----|
| Capture interval | 10 min | Fast enough to catch behavior changes, slow enough to keep storage manageable |
| Visible history | ~12 min | Every capture overlaps the previous by 2 min |
| Overlap rate | ~17% | Enough for cross-fade continuity analysis |
| Captures per hour | 6 | 144/day, 4,320/month |
| Full frame size | ~800 KB PNG | Lossless, readable by vision models |
| Daily storage | ~115 MB raw | Compressible; see §5 |

**The 2-minute overlap is important.** It means:
- Every event is visible in at least two captures (sometimes three)
- We can verify detections across overlapping windows
- If analysis fails on one capture, the event lives in the next one
- Retroactive re-analysis (see §4) can diff old analysis vs new analysis on the same pixels

**Edge case — vessel at dock:** If the vessel is stationary (SOG < 0.5 kn), the echogram shows the same water column over and over. The overlap becomes 12 min of the same bottom. The system should detect this and either skip captures or tag them as "stationary" and reduce verbosity.

### 1.3 The NMEA Pin

Every capture must be timestamped and pinned to vessel position at the moment of capture. This is non-negotiable. A capture without position is a photo of the ocean floor with no location — interesting but useless.

**NMEA snapshot format (written alongside each capture):**

```json
{
  "capture_ts": "2026-07-17T09:15:00.000+00:00",
  "capture_file": "frame_20260717_091500.png",
  "position": { "lat": 55.78595, "lon": -131.527017 },
  "vessel": { "sog_kn": 6.2, "cog_deg": 180, "heading_deg": 178 },
  "nmea_raw_ts": "2026-07-17T09:14:59.500+00:00",
  "nmea_age_ms": 500,
  "hz": 10,
  "satellites": 12,
  "hdp": 0.8
}
```

The NMEA read must happen **immediately before or after** the capture — within 1 second. GPS at 10 Hz gives us sub-second precision. The vessel is moving; a 3-second delay at 6 kn is ~10 meters. That matters for contour correlation.

**Implementation constraint:** The `read_nmea()` call must succeed or the capture is still saved (with null position). Position is a best-effort pin, not a gate. A timestamped blind capture is better than no capture.

### 1.4 Crop + Archive

Each full frame is:
1. **Archived** to `captures/raw/` — full 1920×1080 PNG, permanent record
2. **Cropped into bands** for analysis:
   - `captures/bands/20260717_091500_LF.png` — Left band, ~937×900
   - `captures/bands/20260717_091500_HF.png` — Right band, ~940×900
3. **Band crops are stored** — these are what we analyze, display, and feed to vision models. The full frame is backup.

**Why keep both bands as separate files?**
- Vision models need square-ish inputs, not 1920-wide strips
- Each band has different visual characteristics (LF = bigger arches, wider cone; HF = finer detail, narrower beam)
- Future analysis may want to compare LF vs HF on the same capture
- Clean separation makes the band analysis pipeline independent

---

## 2. Analyzer Design — "Reading the Water Column"

### 2.1 The Fundamental Shift: From Thresholds to Pattern Recognition

The old analyzer used RGB thresholds. It worked because the sounder's blue palette maps signal intensity to color: dark blue = no return, cyan = weak, yellow = medium, orange/red = strong. But thresholds are brittle. They break when:
- The display brightness changes
- TZ Pro switches palettes
- Ambient light hits the screen
- The transducer frequency changes cone angle
- A fish is right against the bottom (counted as "bottom band")

**The new analyzer uses composition:**
1. **Structural analysis** — find edges, bands, regions (not pixels)
2. **Shape classification** — identify arches, blobs, streaks, clouds, thermoclines
3. **Depth zone segmentation** — divide water column into bands
4. **Text description** — express everything as readable prose, not just numbers

### 2.2 Depth Scale Detection

Each band has a depth scale on its right edge (~15-20px of tick marks and tiny numbers). This is the most critical structural element — without it, we can't map pixels to fathoms.

**Strategy: Edge-detection approach** (replace Tesseract OCR for the scale):

```
1. Crop the right 25px of each band
2. Convert to grayscale
3. Vertical edge detection (Sobel Y): tick marks create horizontal edges
4. Find periodic dark-light transitions → scale tick positions
5. Count tick clusters → number of depth step intervals
6. Calibrate: if 10 ticks → 0-100 fm at 10 fm/tick
7. Cross-reference with TZ Pro's status bar for confirmation
```

**Fallback:** If tick marks are ambiguous, read the bottom-most displayed number in the status bar (which shows current depth in large text) via simple OCR. Use that to calibrate the scale ratio.

**Confidence levels:**
- **High** — ticks detected at regular intervals, consistent with expected scale
- **Medium** — ticks detected but irregular; best-guess from number of intervals
- **Low** — no ticks detected; fall back to status bar OCR
- **Failed** — nothing readable; use previous calibrated scale if capture interval < 30 min

Scale calibration should persist and be validated per-capture. If the scale shifts (user zooms in/out), the system detects the mismatch and recalibrates.

### 2.3 Bottom Detection — The Return Band

The bottom return is the brightest continuous horizontal band in the echogram. It's not a line — it's a band of varying thickness (5-30px) where the signal saturates.

**New algorithm (replace per-column brightest-pixel scanning):**

```
1. Convert band to HSV (hue is more informative than RGB for return strength)
2. Threshold on saturation + value: strong returns = high saturation + high value
3. Find the lowest continuous horizontal ridge in the image
4. Trace the upper edge of the ridge (the "top of bottom")
5. Compute:
   - Mean bottom depth (pixels + scale → fm)
   - Bottom thickness (px: muddy = thick, rocky = thin)
   - Bottom roughness (pixel variance across the band)
   - Bottom intensity (hue: orange/red = hard, green/yellow = medium, blue/cyan = soft)
6. Classify bottom type:
   - "Hard/rocky" — thin band (< 8px), high intensity, rough top edge
   - "Hard-pan / gravel" — moderate band (8-15px), mixed intensity, smooth top
   - "Soft mud" — thick band (15-30px), medium/low intensity, diffuse
   - "Silt / very soft" — very thick band (> 30px), low intensity, vague edge
   - "Mixed" — varies across the band width
```

**Bottom continuity scoring:** How much of the bottom is visible?
- **Continuous (>90%)** — clean bottom track, high confidence
- **Partial (60-90%)** — some gaps (fish near bottom, aeration, noise)
- **Intermittent (<60%)** — weak return, deep water, transducer off bottom

**Crucial new capability: Bottom trend.** Over 12 minutes of scrolling history, the bottom line moves. It rises, falls, or holds steady. This is the most interesting single signal in the echogram. The analyzer should compute:

```
bottom_trend = {
  "direction": "rising" | "falling" | "steady" | "undulating",
  "rate_fm_per_min": 0.0,  // e.g., 0.3 fm/min rising
  "range_fm": [48.0, 55.0],  // min and max over window
  "total_change_fm": 7.0
}
```

### 2.4 Water Column Segmentation

Rather than scanning pixel-by-pixel for "fish returns", segment the water column into **zones** and describe each zone:

```
Zone 0: Surface layer (0-5 fm) — surface clutter, turbulence, aeration
Zone 1: Upper water column (5-20 fm) — bait, pelagics, first thermocline
Zone 2: Mid water column (20-40 fm) — target fish, schools, second thermocline
Zone 3: Near-bottom (40+ fm to bottom) — demersal fish, near-bottom schools
Zone 4: Bottom return band — the bottom itself
```

For each zone, extract:
- **Return density** (pixel coverage ratio)
- **Return intensity** (mean hue/saturation)
- **Pattern type(s)** — see §2.5
- **Confidence** — is there actually something here or is it noise?

**Zone boundaries are not fixed.** They adapt to the current bottom depth:
- If bottom is at 100 fm, "near-bottom" is the last 10% of that
- If bottom is at 20 fm in shallow water, there's no "mid column"
- Thermocline depths shift zone boundaries

### 2.5 Shape Classification — What Does the Return Look Like?

This is where the new pipeline diverges most from the old one. The old system counted pixels. The new one **describes shapes**. Shapes are what the Captain sees, what he talks about ("there's a cloud of chum at 35 fm"), and what maps to species behavior.

**Shape taxonomy:**

```
Arches    — Individual fish passing through the transducer cone.
             Classic fish arch: rising edge, peak, falling edge.
             Width = transit time through cone.
             Height = depth within cone.
             
Blobs     — Dense aggregations. No clear individual targets.
             Smooth edges = tight school (pelagic, feeding).
             Fuzzy edges = scattered school (transiting, dispersed).
             
Clouds    — Diffuse returns, low intensity, large area.
             Bait balls, plankton layers, debris.
             Low confidence = likely noise or thermocline.
             
Streaks   — Vertical or diagonal lines through multiple depth bands.
             Trawl gear, downrigger cables, mooring lines.
             Distinctive: same shape appears on LF and HF, vertical.
             
Thermo-   — Horizontal bands of consistent color across the full width.
clines       Sharp edge = strong thermocline (summer, stratified).
             Diffuse edge = weak thermocline (mixing, spring/fall).
             Multiple bands = complex thermal structure.
```

**Classification approach (OpenCV-first, vision model as upgrade):**

Phase 1 uses structural heuristics:
- **Arches:** Find connected components with a concave-up top edge (y increases then decreases over x). Width-to-height ratio > 2:1.
- **Blobs:** Find contiguous regions above intensity threshold. Measure convexity. Smooth boundary = tight school.
- **Clouds:** Low-intensity connected components, large area, non-uniform. Threshold well below fish intensity.
- **Streaks:** Vertical or diagonal connected components spanning > 20% of water column. Consistent x-range.
- **Thermoclines:** Horizontal bands with low cross-track color variance, present across > 60% of band width.

Phase 2 upgrades to vision model (Florence-2 or equivalent) for the full band, generating a caption that the heuristic classifier runs on top of.

**The key insight: Shapes are the vocabulary.** They're what the Captain recognizes. They're what gets correlated with catch reports. "Chum salmon" isn't a pixel signature — it's a "cloud of discrete arches at 30-40 fm, hovering 5-10 fm off the bottom, tight school, undulating." That's a shape vocabulary, not a threshold.

### 2.6 Description Architecture

The analyzer produces a structured description, not just numbers. Here's the internal data structure:

```python
{
  "capture_ts": "2026-07-17T09:15:00+00:00",
  "bands": {
    "LF": {
      "depth_scale": {"min_fm": 0, "max_fm": 100, "ticks": 10, "confidence": "high"},
      "bottom": {
        "depth_fm": 53.2,
        "type": "medium_hard",
        "thickness_px": 12,
        "roughness_fm": 0.4,
        "continuity_pct": 95,
        "trend": {"direction": "rising", "rate_fm_per_min": 0.2, "range_fm": [48, 55]}
      },
      "zones": [
        {"label": "surface", "depth_range_fm": [0, 5], "description": "light surface clutter, no targets"},
        {"label": "upper_column", "depth_range_fm": [5, 20], "description": "clear water column, no returns"},
        {"label": "mid_column", "depth_range_fm": [20, 40], "description": "medium density cloud, diffuse edges, depth 25-38 fm"},
        {"label": "near_bottom", "depth_range_fm": [40, 53], "description": "scattered small blobs, 2-5 fm off bottom, low density"}
      ],
      "shapes": [
        {"type": "cloud", "depth_fm": [25.0, 38.0], "intensity": "medium", "confidence": "medium"},
        {"type": "blob", "depth_fm": [45.0, 50.0], "intensity": "medium", "confidence": "low", "count_estimate": 3}
      ],
      "thermoclines": [
        {"depth_fm": 22.0, "strength": "weak", "thickness_fm": 3.0, "confidence": "high"}
      ],
      "text_summary": "LF band: bottom rises from 55 to 48 fm over 12-min window (hard to medium transition at ~09:10). Mid-column cloud of diffuse returns from 25-38 fm, moderate density. Weak thermocline at ~22 fm. Near-bottom zone shows 3 small blobs 2-5 fm up, likely individual fish. Surface zone clear."
    },
    "HF": {
      # Same structure as LF
      "text_summary": "HF band: finer detail confirms bottom transition. Mid-column returns show discrete arching targets within the cloud — suggests individual fish rather than bait. Near-bottom blobs more distinct: likely rockfish or flatfish."

    }
  },
  "cross_band": {
    "comparison": "LF shows broader cloud; HF resolves individual targets within it. Both bands agree on bottom depth within 1 fm. Thermocline visible on LF only.",
    "significant_match": true,
    "divergence_areas": ["thermocline visibility", "target resolution"]
  }
}
```

### 2.7 Confidence Architecture

Every derived value gets a confidence. The system must be honest about uncertainty — a bottom depth with "low" confidence should bubble up differently than one with "high" confidence.

| Feature | High confidence requires | Medium | Low |
|---------|------------------------|--------|-----|
| Bottom depth | Clean bottom band >80% continuous, scale calibrated | Bottom band 50-80% continuous, or scale estimated | Bottom band <50%, or depth scale unreadable |
| Shape type | Clear shape features, matches taxonomy unambiguously | Partial shape features, could be 2-3 types | Vague return, shape uncertain |
| Thermocline | Sharp band >60% width, consistent color | Fuzzy band >40% width, some shading | Subtle band, might be noise |
| Fish vs noise | Arches or tight blobs, clear edges | Diffuse blobs, could be plankton | Cloud returns, could be thermocline or surface clutter |

The confidence system cascades: low confidence on depth scale → low confidence on bottom depth → low confidence on fish depth range → low confidence on species matching. This is correct and should be explicit.

---

## 3. The Text Summary Schema — "Echogram Captions"

### 3.1 Why Text Summaries?

A text summary is the most flexible, searchable, and AI-compatible format for echogram analysis. It's what:
- Vision models output (captions)
- The Captain reads ("what did the sounder show at this spot?")
- The learning loop uses (descriptions that match against catch reports)
- Gets indexed by semantic search
- Gets appended when re-analyzed with better methods

**Numbers are rigid; text is extensible.** Adding a new field to a JSON schema requires migrating all existing records. Adding a sentence to a text summary changes nothing downstream — the old text still works, the new text is richer.

### 3.2 The Canonical Caption Format

Every capture produces one canonical text summary per band, plus one cross-band summary. These are the "captions" for that moment in time.

**Canonical format (LF example):**

```
LF echogram at 2026-07-17 09:15 AKDT
Position: 55.786°N, 131.527°W (SPEED 6.2 kn COG 180°)

Bottom: 53 fm, medium-hard, continuous. Rising trend over window (55→48 fm). 
Surface layer: clear.
Upper column (5-20 fm): clear, no returns.
Mid column (20-40 fm): moderate cloud of medium-intensity returns, depth 25-38 fm, diffuse edges. Contains possible individual arching targets.
Near-bottom (40-53 fm): 3 small blobs, 2-5 fm off bottom.
Thermocline: weak, ~22 fm.

Shapes: cloud (25-38 fm, medium intensity, medium confidence), 
        individual targets (3, near-bottom, low confidence).

Cross-band: HF confirms upper column cloud contains individual fish targets. 
            HF less clear on thermocline. Agreement on bottom depth within 1 fm.
```

**Why this format?**
- It reads like a Captain's log entry — natural language the Captain already uses
- It's self-contained: every summary includes position, speed, depth, and descriptions
- It's appendable: when re-analyzed, new observations append to the summary
- It's semantically searchable: "medium intensity cloud at 30 fm" finds all relevant captures
- It can be fed to an LLM for synthesis: "what did the LF band look like between 09:00 and 10:00 on July 17?"

### 3.3 Summary Generations

A text summary can exist in multiple generations:

| Generation | Source | Detail Level | When Created |
|-----------|--------|-------------|-------------|
| G1 | OpenCV heuristic analysis | Structural only — bottom depth, basic shape counts | Immediately on capture |
| G2 | Vision model caption (Florence-2) | Full band description — shapes, colors, patterns | ~2-3s later |
| G3 | Human correction (Captain edits) | Ground truth — corrected labels | On Captain review |
| G4 | Retroactive re-analysis | Improved analysis with better models | Anytime later |

The summary doc stores all generations with timestamps:

```json
{
  "capture_ts": "2026-07-17T09:15:00+00:00",
  "summaries": {
    "G1": {
      "ts": "2026-07-17T09:15:03+00:00",
      "source": "heuristic_v2",
      "algorithm": "okimi_analyzer_v1",
      "text": "LF echogram at 2026-07-17 09:15 AKDT..."
    },
    "G2": {
      "ts": "2026-07-17T09:15:06+00:00",
      "source": "florence_v2",
      "model": "florence-2-base-fp16",
      "text": "A scrolling sonar display showing low-frequency returns..."
    },
    "G3": {
      "ts": "2026-07-17T11:30:00+00:00",
      "source": "captain",
      "editor": "casey",
      "text": "LF echogram at 2026-07-17 09:15 AKDT - CORRECTED: chum school at 30 fm, ~40 fish, on the move northward..."
    }
  }
}
```

### 3.4 The Storage Layer

Text summaries go into a **collection** (one per band per capture) that's indexed by:
- **Timestamp** — captures sorted by time
- **Position** — geospatial bounding box search
- **Semantic content** — vector embedding of the summary text
- **Bottom depth range** — find all captures where bottom was 40-60 fm
- **Shape types present** — find all captures with "cloud" in mid column

**Storage options:**
- **SQLite FTS5** — full-text search, zero infrastructure, perfect for single-boat
- **File-based JSONL** — simplest, most portable, append-only appendable
- **TileDB / Parquet** — columnar, queryable, good for fleet aggregation later
- **vector DB (sqlite-vec / chroma)** — if semantic search matters (and it does)

**Recommendation:** SQLite FTS5 for the structured fields + flat file JSONL for the raw analysis data (every JSON analysis appended to a daily file). The text summaries live in both — SQLite for search, JSONL for history and re-analysis.

When re-analysis happens (G4), the new summary is appended to the JSONL and the SQLite record is updated (or versioned). The old summary is never deleted.

---

## 4. Multi-Track Correlation — "The DAW Takes Shape"

### 4.1 Track Overview

The system runs on a single axis: **time**. Every piece of data carries a timestamp. The DAW is just a big playlist sorted by wall clock:

```
 09:00    09:10    09:15    09:20    09:30    09:40    09:50    10:00
  │        │        │        │        │        │        │        │
  ▼        ▼        ▼        ▼        ▼        ▼        ▼        ▼
┌────────────────────────────────────────────────────────────────────┐
│ Track 1: Echogram captures  ◆      ◆      ◆      ◆      ◆      ◆│  ~10 min
├────────────────────────────────────────────────────────────────────┤
│ Track 2: NMEA position      ════════════════════════════════════│  continuous 1Hz
├────────────────────────────────────────────────────────────────────┤
│ Track 3: Analysis summaries     ■      ■      ■      ■      ■   │  per capture
├────────────────────────────────────────────────────────────────────┤
│ Track 4: Catch events                       ✦                      │  on report
├────────────────────────────────────────────────────────────────────┤
│ Track 5: Captain conversation    …  ─  ─  ─  ─  ─  ─  ─  …      │  as spoken
├────────────────────────────────────────────────────────────────────┤
│ Track 6: Species labels                 chum@30                    │  retroactive
└────────────────────────────────────────────────────────────────────┘
```

### 4.2 Track Alignment

All tracks align on **capture timestamps** as the frame boundary. NMEA data is continuous (1-10 Hz), so we snap nearest-NMEA to each capture. Catch events are discrete — they pin to the nearest capture or span a range of captures.

**The alignment operation:**

```python
def align_tracks(capture_ts: datetime, nmea_buffer, catch_log, analysis_history):
    """Return a dict of all tracks aligned to this capture timestamp."""
    return {
        "capture": capture_ts,
        "nmea": nearest_nmea(nmea_buffer, capture_ts, max_age_ms=1000),
        "analysis": analysis_for_capture(capture_ts, analysis_history),
        "catch_events": catch_events_within(catch_log, capture_ts - timedelta(minutes=30), capture_ts),
        "species_labels": labels_applied_to_window(capture_ts - timedelta(minutes=30), capture_ts),
    }
```

The max_age_ms matters. If NMEA data is > 1 second stale, the position is marked as "estimated" (interpolated from last known position + course + speed). This is the backup for NMEA dropout.

### 4.3 Catch Event Schema

When the Captain reports a catch, it enters the catch log:

```json
{
  "ts": "2026-07-17T09:45:00+00:00",
  "reported_by": "captain",
  "species": "chum_salmon",
  "count": 40,
  "depth_fm": 30,
  "method": "trolling",
  "position": {"lat": 55.790, "lon": -131.530},
  "notes": "clean fish, bright, on the move north",
  "linked_captures": [
    "2026-07-17T09:15:00+00:00",
    "2026-07-17T09:25:00+00:00",
    "2026-07-17T09:35:00+00:00",
    "2026-07-17T09:45:00+00:00"
  ]
}
```

The `linked_captures` field is critical. The system automatically links the catch to:
1. The capture closest to the catch time
2. All captures within the last 30 minutes (the "lead up" window)
3. Any captures with NMEA within the same position bounding box (±0.02°)

The Captain can add or remove links manually. This is the ground truth for the learning loop.

### 4.4 Retroactive Re-Analysis ("Going Back")

This is where the system shows its teeth. When the learning loop improves (new species signature, better model, corrected labels), every existing capture can be re-analyzed with the new knowledge.

**Trigger conditions:**
- **New species signature added** — scan all captures for similar shapes
- **Model upgraded** — G4 analysis with Florence-2 v2 on all existing captures
- **Captain corrects a label** — propagate the correction to similar past captures
- **Manual re-analysis request** — "Re-analyze July 15-17 for chum signatures"

**The re-analysis pipeline:**

```
1. Collect all captures in the target range (or all captures ever)
2. For each capture, run the new analysis method
3. Produce G4 (or G2 if no previous G2) text summary
4. Append new summary to the capture record
5. Re-run semantic search against species signatures
6. Add any new matches to the capture's labels
7. Log the re-analysis event
```

**Key constraint: Re-analysis never overwrites.** Old summaries stay. The full history of "what this looked like when we were less smart" is preserved. This creates a growth record — later, you can ask "how many of my old captures now show chum signatures that we missed the first time?" The answer is a measurement of how much better the system has become.

### 4.5 Label Propagation

When a catch event is logged, the system searches the **recent capture window** for analysis summaries that describe features matching the caught species. It proposes labels:

```
Catch: chum salmon, 30 fm, 40 fish, 09:45
Likely matching captures in window 09:15-09:45:
  - 09:15: "mid-column cloud, 25-38 fm, medium intensity, diffuse edges"  → MATCH (similar depth, aggregate shape)
  - 09:25: "mid-column cloud persisting, 25-40 fm"                        → MATCH
  - 09:35: "cloud condensing, 28-35 fm, tighter edges"                    → STRONG MATCH (shape evolved as school was caught)
  - 09:45: capture coincides with catch time                              → PINNED

Confidence per capture:
  - 09:15: 0.62 (moderate shape overlap, but more diffuse than expected)
  - 09:25: 0.71 (better overlap, similar depth band)
  - 09:35: 0.88 (tight match — shape evolution consistent with disturbance)
  - 09:45: 0.95 (pinned by time coincidence)
```

Labels are stored as an overlay — they don't modify the original analysis. They're a separate track:

```json
{
  "capture_ts": "2026-07-17T09:35:00+00:00",
  "labels": [
    {
      "species": "chum_salmon",
      "confidence": 0.88,
      "source": "catch_link_20260717_094500",
      "linked_catch_ts": "2026-07-17T09:45:00+00:00",
      "applied_by": "propagation_engine",
      "applied_ts": "2026-07-17T09:50:00+00:00"
    }
  ]
}
```

Multiple catch events can overlap on the same capture. That's fine — the confidence tracks each label independently. A capture with three overlapping chum catch labels at confidences 0.88, 0.76, and 0.82 is telling you "this looks like chum ground" with high ensemble confidence.

---

## 5. Storage Strategy — "What to Keep"

### 5.1 Storage Budget

| Data | Daily | Monthly | Season (4 mo) | Retention |
|------|-------|---------|---------------|-----------|
| Full frames (1920×1080 PNG) | ~115 MB | ~3.5 GB | ~14 GB | Keep full season, archive older |
| Band crops (2× ~940×900 PNG) | ~80 MB | ~2.4 GB | ~9.6 GB | Derived from full frames, can delete |
| Text summaries (canonical + generations) | ~50 KB | ~1.5 MB | ~6 MB | Permanent — these are the gold |
| NMEA snapshots (per capture) | ~50 KB | ~1.5 MB | ~6 MB | Permanent — pins every capture |
| Catch event log | Negligible | Negligible | Negligible | Permanent |
| Shape signatures / species library | < 1 MB | ~5 MB | ~20 MB | Permanent, grows with learning |
| Contour grid (bathymetry) | 153 MB | 153 MB | 153 MB | One-time, static |

**Realistic daily storage:** ~200 MB uncompressed, ~60 MB with PNG optimization (pngquant level 3).

**Seasonal total:** ~25 GB raw, ~8 GB optimized. On a 512 GB SSD, that's ~20 seasons of continuous operation.

### 5.2 Image Retention Policy

**Full frames:**
- Keep **all** for the current season
- At season end, compress to lossy WebP (quality 85, ~200 KB per frame)
- Archives stay on the boat's external drive
- Optionally upload thumbnails to cloud storage

**Band crops:**
- Keep only until the full-frame archive is written
- Can be regenerated from full frames at any time
- Delete oldest after 30 days if disk is tight
- **Exception:** If a crop has been labeled with a catch event, keep it permanently in a labeled_captures/ directory

**Why not keep everything at full quality forever?**
- 14 GB/season × 10 seasons = 140 GB of PNGs. That's fine.
- The bottleneck isn't disk — it's analysis throughput. Most old frames will never be looked at again.
- Text summaries are where the value concentrates. The images are backup truth.

### 5.3 Text Summary Store

The text summaries are the **primary asset**. They're what gets searched, analyzed, correlated, and queried.

**Storage architecture:**

```
memory/
  summaries/
    2026-07-17.jsonl        # Daily summaries: G1, G2, G3, G4 all in one file
      Format per line: {"capture_ts": "...", "band": "LF", "generation": "G1", ...}
    
  labels/
    2026-07-17.jsonl        # Species labels applied to captures
    
  catch/
    events.jsonl            # All catch events, ever
    
  nmea/
    2026-07-17.jsonl        # NMEA snapshots per capture
    
  species_library/
    signatures.json          # Feature vectors for known species
    vocabulary.json          # Text pattern → species mappings
```

**SQLite for search:**

```sql
-- Create the summary search index
CREATE VIRTUAL TABLE summary_fts USING fts5(
    capture_ts, band, generation, source, text,
    content='summaries', content_rowid='rowid'
);

-- Semantic search
SELECT capture_ts, band, text FROM summary_fts 
WHERE summary_fts MATCH '"chum" NEAR "30 fm"';

-- Range query
SELECT * FROM summaries 
WHERE capture_ts BETWEEN '2026-07-17T09:00' AND '2026-07-17T10:00'
AND band = 'LF';
```

### 5.4 The Question of a Vector Store

Text summaries are semantically rich. "Cloud at 30 fm" and "diffuse school near 30 fathoms" mean the same thing but share no keywords. FTS5 can't handle this — it needs exact token matches.

**For the MVP, skip the vector store.** FTS5 handles keyword search well enough. Semantic search is a nice-to-have enhancement for Phase 3.

**When adding vectors:**
- Embed the G1 and G2 text summaries (separately — G1 is structural, G2 is descriptive)
- Store embeddings in `sqlite-vec` (adds vector support to existing SQLite)
- Query: "find captures similar to this one" → embed the query text, cosine similarity against stored embeddings
- Use case: "Show me all captures that look like the one where we caught kings last week"

---

## 6. Vocabulary Building — "Teaching the System to Read"

### 6.1 The Problem

The system has no intrinsic understanding of what species look like on an echogram. It can describe shapes: "medium-intensity cloud, diffuse edges, depth 25-38 fm." It cannot say "that's chum salmon" because it has never learned what chum salmon look like on this display, at this transducer frequency, at this boat speed.

**The learning loop solves this through supervised signal from the Captain.**

### 6.2 The Signature Library

Every catch event generates a species signature:

```python
species_signature = {
    "species": "chum_salmon",
    "catch_ts": "2026-07-17T09:45:00+00:00",
    "position": {"lat": 55.790, "lon": -131.530},
    "depth_fm": 30,
    "linked_captures": ["09:15", "09:25", "09:35", "09:45"],
    
    "features": {
        "LF": {
            "shape_primary": "cloud",
            "shape_secondary": "arches_within_cloud",
            "depth_range_fm": [25, 38],
            "depth_range_relative_bottom": "mid_column",  # between 50-80% of bottom depth
            "intensity": "medium",
            "movement": "transiting",   # or "stationary", "feeding", "dispersing"
            "est_density": "moderate",
        },
        "HF": {
            "shape_primary": "individual_arches",
            "shape_secondary": None,
            "depth_range_fm": [27, 35],
            "depth_range_relative_bottom": "mid_column",
            "intensity": "medium_high",
            "movement": "transiting",
            "est_density": "moderate",
        }
    },
    
    "context": {
        "sog_kn": 6.2,
        "bottom_depth_fm": 53,
        "bottom_type": "medium_hard",
        "time_of_day": "morning",
        "season": "summer",
        "location": "ketchikan_outside"
    },
    
    "confidence_weight": 0.9,  # from Captain's reputation; starts at 0.5, increases with confirmation
}
```

Each signature is a **composite** of all linked captures. The first catch creates a rough draft. The second catch of the same species refines it. Over enough catches, the signature converges on the "platonic ideal" of that species on this equipment.

### 6.3 Similarity Matching

When a new capture comes in, its analysis is compared against the signature library:

```python
def score_similarity(capture_analysis, species_signature):
    """
    Returns a weighted similarity score 0.0–1.0.
    """
    score = 0.0
    weights = {
        "shape_primary": 0.30,
        "depth_range": 0.20,
        "depth_relative": 0.15,  # same zone relative to bottom
        "intensity": 0.10,
        "bottom_type": 0.10,    # species preference for bottom
        "movement_behavior": 0.10,
        "secondary_shape": 0.05,
    }
    
    for feature, weight in weights.items():
        similarity = compare_feature(
            capture_analysis[feature], 
            species_signature["features"][feature],
            strictness=getattr(capture_analysis, 'confidence', 'medium')
        )
        score += similarity * weight
    
    return score
```

The matching is done **per band separately** and then averaged. If LF and HF agree on a match, the confidence doubles.

### 6.4 Confidence Calibration

Confidence is not arbitrary. It must have real-world meaning:

| Confidence | Meaning | Threshold | Action |
|-----------|---------|-----------|--------|
| 0.00-0.30 | No match / noise | System says nothing |
| 0.31-0.50 | Weak similarity | Recorded but not surfaced |
| 0.51-0.70 | Possible match | Logged, shown in dashboard as "possible" |
| 0.71-0.85 | Likely match | Surfaces as prediction: "71% match to chum" |
| 0.86-0.95 | Strong match | Surfaces as alert: "Chum school confirmed pattern" |
| 0.96-1.00 | Near-certain | Sent as notification: "Chum on the sounder, drop gear?" |

Thresholds are tunable. The Captain might want higher activation energy ("don't tell me unless you're 85% sure") or lower ("show me everything above 50%"). This is a user setting.

### 6.5 The Bootstrapping Problem

The first catch of the season produces one signature. The second catch of a different species produces a second. For the first week, every match will be weak because the library has only 2-3 entries. Everything will look like "unidentified blob at X fm."

**Bootstrapping strategy:**

1. **Pre-seed with generic shapes:** "this is what a school looks like" (from literature, standard behavior). Not species-specific.
2. **Captain's first catches are gold.** Each one goes into the library with high weight. After 5 catches of the same species, the signature starts to stabilize.
3. **Sub-species clustering:** When multiple signatures for the same species have been collected, cluster them. If two "chum" signatures look very different, the system flags them: "I've got two distinct chum patterns — feeding vs transiting? Small vs large? Surface vs deep?"
4. **Negative feedback:** The Captain can mark a prediction as wrong. "That's not chum, that's coho." This generates a negative signature: "this shape + depth + location = NOT chum." The system learns to distinguish.

### 6.6 Vocabulary Evolution Over Time

```
Week 1:
  "Unidentified cloud at 25-38 fm"
  Species library: empty (no catches yet)
  
Week 2 (after 3 chum catches):
  "78% match to chum_salmon school (3 similar captures)"
  Species library: chum(3), coho(1)
  
Month 2 (after 30 catches across 5 species):
  "92% match to chum_salmon — feeding school, morning pattern"
  Species library: chum(12), coho(8), king(5), halibut(3), rockfish(2)
  System can now distinguish chum by: cloud shape, depth range, SOG, time of day
  
Season end:
  "94% match to chum_salmon — identical to July 17 school at 30 fm"
  Species library: 8 species, 50+ signatures, seasonal sub-types
  System can answer: "show me all chum schools this season by week"
```

### 6.7 The Unidentified Blob Category

The most honest output of the system: **"I don't know what that is."**

The system should have a deliberate "unidentified" category for returns that:
- Don't match any species signature
- Don't match any generic shape in the pre-seeded library
- Have low analysis confidence

These are **the learning opportunities**. Every unidentified blob that the Captain walks over and says "that's chum" strengthens the system. Every one he says "no idea, ignore it" teaches the system to decrease its sensitivity to that pattern.

The Captain should be able to review unidentified blobs on the dashboard — a browseable gallery of "hey, what's this?" shapes from the last 24 hours. It takes 5 seconds to label one. Over a month, 150 seconds of Captain-time = 150 labeled signatures.

---

## 7. Implementation Phasing — "What Burns First"

### 7.1 Phase 0: Rewrite Config (Day 1)

The current `config.py` encodes the thin-strip sensor geometry. Rewrite it:

- New capture regions (dual band, full frame)
- Remove old single-band geometry constants
- Add band split parameters (x_offset, width, calibration margins)
- Add capture cadence (10 min)
- Add depth scale parameters (tick detection, per-band calibration)

**Deliverable:** `config.py` with new geometry constants. Old constants deprecated but kept for reference.

**Risk:** None. Config file, no runtime changes.

### 7.2 Phase 1: Capture Pipeline (Days 1-2)

Replace the capture flow:

1. **New capture function** captures full 1920×1080 frame
2. **Crop function** splits into LF band and HF band
3. **NMEA snapshot** taken within 500ms of capture
4. **File naming** updated: `frame_YYYYMMDD_HHMMSS.png` + `LF_YYYYMMDD_HHMMSS.png` + `HF_YYYYMMDD_HHMMSS.png`
5. **Overlap tracking** — keep a rolling window of last capture timestamp, confirm 10-min cadence with 2-min tolerance
6. **Stationary detection** — if SOG < 0.5 for 3 consecutive captures, reduce cadence to 30 min or skip until vessel moves

**Deliverable:** `capture.py` v2 that captures and splits dual-band, writes NMEA snapshots, cadence 10 min.

**Risk:** Low. Screen capture mechanism is proven. The only new code is splitting and NMEA sync.

### 7.3 Phase 2: Heuristic Analyzer v2 (Days 2-4)

The big rewrite of `sounder_analyzer.py`:

1. **Depth scale detection** — tick-mark edge detection on right 25px of each band
2. **Bottom detection** — horizon ridge method (§2.3), not per-column brightest pixel
3. **Bottom trend** — sweep left-to-right across the 12-min window
4. **Water column segmentation** — dynamic zones based on bottom depth
5. **Shape classification** — arches, blobs, clouds, streaks, thermoclines (§2.5)
6. **G1 text summary generation** — structured description format (§3.2)
7. **Confidence scoring** — per-field confidence (§2.7)

**What stays from v1:** Color palette understanding (blue→cyan→yellow→orange→red), bottom type heuristics, thermocline detection basics. These were good — they just need to be structured differently.

**What gets deleted:** Per-column brightest-pixel scanning, fish-return pixel counting, RGB threshold-based density. These were band-aids for the thin-strip approach.

**Deliverable:** `okimi_analyzer.py` (new file, pure heuristic). Processes one band at a time, returns structured analysis + G1 text summary.

**Risk:** Moderate. Shape classification is new territory. The heuristics will miss some shapes and misclassify others. That's fine — G2 (vision model) catches what G1 misses.

### 7.4 Phase 3: Multi-Track Logger (Days 4-5)

1. **New log format** — `memory/summaries/YYYY-MM-DD.jsonl` for text summaries
2. **SQLite schema** for searchable summaries
3. **NMEA snapshots** persisted alongside captures
4. **Catch event log** — schema, interface, linking to captures
5. **Summary generation tracking** — G1/G2/G3/G4 versioning

**Deliverable:** `okimi_logger.py` — writes summaries, NMEA pins, catch events, manages SQLite search index.

**Risk:** Low. File-based logging is proven. The SQLite upgrade is a known pattern.

### 7.5 Phase 4: Vision Model Integration (Days 5-10)

When Florence-2 (or equivalent) runs on the RTX 4050:

1. **G2 caption generation** — feed band crop to model, get natural language caption
2. **G2 parsing** — extract structured info from the caption (model outputs "a school of fish at 30 meters" → structured shape classification)
3. **G1 + G2 fusion** — combine heuristic analysis and vision model caption. Where they agree, confidence is high. Where they disagree, flag for review.
4. **GPU scheduling** — accommodate the 6GB VRAM constraint with Ollama

**Deliverable:** `okimi_vision.py` — vision model interface, caption parser, G1+G2 fusion.

**Risk:** Moderate. GPU contention, model quality, caption parsing robustness. The fusion logic is new and will need tuning.

### 7.6 Phase 5: Catch Correlation (Days 10-14)

The learning loop:

1. **Species signature library** — signatures extracted from linked captures
2. **Similarity scoring** — match new captures against library
3. **Label propagation** — when catch logged, auto-label recent captures
4. **Bootstrapping** — manage the first week of weak matches
5. **Unidentified blob gallery** — dashboard feedback loop
6. **Retroactive re-analysis** — button to re-run all captures with new model

**Deliverable:** `okimi_learner.py` — signature management, scoring, label propagation. `okimi_reanalyze.py` — bulk re-analysis.

**Risk:** Moderate-low. The algorithms are straightforward. The uncertainty is how well similarity scoring works with heuristic-only analysis (G1). G2 (vision model) will make scoring much more reliable.

### 7.7 Phase 6: Captain Interface (Weeks 3-4)

The dashboard. Not the full DAW (that's the Phase 7 product) — just the views that make the system usable:

1. **Latest capture viewer** — see both bands side by side with analysis overlays
2. **Timeline scrub** — browse through the day's captures
3. **Catch log entry** — simple form: species, count, depth, notes
4. **Unidentified blob gallery** — scrollable, tappable for labeling
5. **Vocabulary display** — what the system has learned, confidence per species

This is a web dashboard served locally. Single-page app, no cloud dependency. Data from SQLite + image files on disk.

**Deliverable:** HTML/JS dashboard in a `dashboard/` directory.

**Risk:** Low-moderate. Building a web UI is known work. The challenge is making it feel good on a wheelhouse tablet.

### 7.8 Phase 7: The Full DAW (Weeks 4-8)

The multi-track timeline described in `v2_architecture.md`. This is the product — the thing that makes the system shine. But it builds on everything above.

**Sequence dependence:**
- Phase 0-3: Must be done first (foundation)
- Phase 4: Can start in parallel with Phase 3 (different file)
- Phase 5: Requires Phase 4 (needs G2 for good scoring)
- Phase 6: Requires Phase 0-3 (needs data to display)
- Phase 7: Requires Phase 0-6 (needs everything)

### 7.9 Phase Order Dependency Graph

```
Phase 0 (Config)
    │
    ▼
Phase 1 (Capture) ──┐
    │                │
    ▼                │
Phase 2 (Heuristic) ─┤
    │                │
    ▼                │
Phase 3 (Logger) ◄──┘
    │
    ├──────────────────┐
    ▼                  ▼
Phase 4 (Vision)   Phase 6 (Dashboard)
    │                  │
    ▼                  │
Phase 5 (Learning) ───┤
                      │
                      ▼
                  Phase 7 (DAW)
```

**The compound interest:** Phase 2 is where the most value per line of code lives. The heuristic analyzer immediately upgrades every capture from "53.2 fm, 3656 fish pixels" to a readable description of what the water column looked like. That compound return starts on Day 2 and keeps paying as every downstream phase feeds on richer input.

---

## Appendix: What Gets Renamed

The old v1 pipeline names encode the thin-strip sensor mindset:

| Old file | New/Optional | Reason |
|----------|-------------|--------|
| `sounder_analyzer.py` | `okimi_analyzer.py` | New algorithm, new philosophy |
| `capture.py` | `okimi_capture.py` | New capture flow |
| `logger.py` | `okimi_logger.py` | New log format |
| `forward_look.py` | Keep name | Still valid, works on same inputs |
| `anomaly_logger.py` | Keep + upgrade | Still valid, add band source field |
| `contour_query.py` | Keep name | No changes needed |

The old files should be kept but marked as deprecated. The system architecture is layered — the old analyzer can run in parallel as a baseline comparator. If the new heuristic misses something obvious, the old pixel-counting approach catches it.

---

## Final Thoughts: The Edge

The v1 pipeline was a thermometer. It poked the water, took a temperature, recorded it. It was useful — it told us the bottom was at 53.2 fm and there were fish pixels.

The ōkimi pipeline is a **naturalist**. It watches the environment, takes field notes, draws what it sees, compares notes with the Captain, and builds a field guide over time. The field guide gets better with every observation. The notes from July are revisited in September with August's knowledge.

**Here's the part that keeps me up at night:**

The old pipeline had one huge advantage. It was simple. It worked or it didn't. If the depth was wrong, you could look at the threshold and see why.

The new pipeline is complex. It describes shapes, builds confidence from multiple signals, layers text analyses, correlates across tracks. When it gets something wrong — and it will — the error chain is harder to trace. "Why did the system think this blob at 30 fm was chum instead of coho?" might take an hour to diagnose.

The hedge against this is the confidence system. Every field, every label, every match has a confidence score. Low confidence ≠ failure. Low confidence = "I'm guessing, don't trust me yet."

But here's the other side: the Captain doesn't care if the system is 100% right. He cares if it's useful 80% of the time on the 20% of captures that matter. A system that says "73% chance this is chum at 30 fm, similar to your catch last Tuesday" and is right 3 times out of 4 is **already more useful than any threshold-based pixel counter ever was**, because it speaks in fish, not in numbers.

The risk is worth the reward. Build the naturalist.

---

*ōkimi (大君) — the archivist who sees all and forgets nothing.*
*CoCapn Ecosystem — CoCapn.com / ActiveLedger.ai / FishingLog.ai*
*F/V EILEEN, July 17, 2026*
