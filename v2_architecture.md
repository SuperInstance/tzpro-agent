# tzpro-agent v2 — The DAW for the Boat
## Architecture & Design Document

A synthesis of the founding session (July 15, 2026), the fleet's contributions
(Nemotron, Hermes, Seed, DeepSeek Pro), and the Captain's prior writings
(five of many in the AI-Writings repository).

**Sections:**
1. The Philosophy (from the Captain's writings)
2. The Architect's Blueprint
3. The DAW Dashboard Design
4. The Learning Loop
5. Riker's Synthesis — What We Build First

---

## Section 1: The Philosophy

*From the Captain's own writings, pre-dating today's session.*

### The Hundred Hooks

The fisherman named Sam in Duke Ellington's Cotton Club at 2 AM. A hundred hooks, a hundred pulls, thirty-seven cod. Each hook is an independent measurement. Yes or no. The pattern across all hooks — that's the intelligence.

The band is the same. Five players, same chart. Each produces something different. The pattern across them — that's the song.

The logbook kept for thirty years. Without it, the pattern is invisible. With it, the captain knows where to run tomorrow because he knows what happened today.

**What this means for FishingLog.ai:**

Every 30-second sounder capture is a hook pull. Every 4-minute full frame is a net haul. Every catch log entry is a landed fish. The intelligence is not in any single capture. It's in the relation across all of them. The ensemble.

### The Person You Forgot Was There

The monitor engineer. The house engineer. The people who make the show happen and vanish so completely that the audience thinks the music is magic.

The depth sounder that did its job so well the captain stopped looking at it. The map dissolved into the body.

**The paradox of the great tool:** It makes itself unnecessary. Not through failure — through being so completely, unobtrusively, perfectly right that it dissolves into the experience.

**What this means for the DAW dashboard:**

The dashboard should not demand attention. It should whisper. In normal operation, it recedes. The captain glances at it when something changes — a mark placed, a pattern detected, a boundary approaching. The rest of the time, it runs silently, like the depth sounder that the captain stopped looking at because the bottom had moved into his bones.

The highest compliment: "I forgot I had that running."

### The Turbo-Shell

The ESP32 engine gauge agent. Narrow scope: read analog signals, convert to structured data, push to log. The repo is permanent memory. The invariant concept lives in AGENTS.md.

Conservation budget. Sandboxed not because weak — because focused. Lives in its territory, a rock pool of specialized knowledge.

**What this means for tzpro-agent:**

Tzpro-agent is a Turbo-Shell. Its territory is the sounder. Its invariant concept: watch the second monitor, extract the echogram, pair with position, log the pattern. Everything else — the hardware, the model, the dashboard — can change. The invariant concept lives in the repo.

### Ebb and Flow

Compute has tides. GPU warm, API keys fresh, RAM deep — full tide. GPU grabbed, network drops, battery low — ebb tide.

The system should not crash at low tide. It should shift metabolic state. Ternary signal: -1 (decrease, cache), 0 (hold, monitor), +1 (increase, full compute).

**What this means for the 6GB RTX 4050:**

Florence-2 and Ollama cannot both run simultaneously on 6GB VRAM. This is not a bug. This is the tide. The 30-second cadence alternates: full tide (Florence-2 analyzes screen), ebb tide (Ollama serves companion queries). The system does not fight the tide. It surfs it.

### Cognitive Photosynthesis

The system is not a collection of parts but an orchestrated whole. Every sensor node is a species in an ecosystem. The components are not parts — they are species, each with its own niche, co-evolving.

The system performs cognitive photosynthesis: turning raw sensor data (sunlight) into intelligence (chemical energy). This is not computation. It is the origin of a new form of life.

### The Reflection You Mistook for Depth

Maximum cognitive activation ≠ correctness. Hermes at 93% activation gets the wrong answer. Seed-mini at 5% activation gets it right. Activation is metabolic rate, not signal.

**What this means for the fleet router:**

The most impressive-looking analysis is not the most correct. The cleanest, fastest, most obvious answer is usually right. When an agent finds itself working very hard — producing paragraphs of reasoning, activating every concept — stop. Change the angle. Decompose. Hand it to someone whose critical angle covers it.

### Charts, Not Maps

*A map is a static record. A chart is a living document, updated by every pass.*

FishingLog.ai is a chart. Every 30-second capture updates it. Every catch log entry annotates it. Every season, it gets more detailed. The chart is never finished. It is always being drawn.

---

## Section 2: The Architect's Blueprint

*Synthesized from the Nemotron architecture review.*

### Data Model: TileDB Echogram Array

The core data structure is a 3D TileDB sparse array:

```
time_ms (dimension) × depth_px (dimension) × horizontal_px (dimension)
  → intensity (uint8 attribute)
```

**Fragment strategy:**
- 6-hour fragments (720 frames × 370×900 pixels)
- Zstd compression, level 7
- Daily consolidation

**SQLite sidecar:**
- Frame-to-NMEA mapping
- Position, SOG, COG per frame
- Catch event references
- Species tags

**Storage budget:**
- ~300-500 MB/day compressed
- ~27-45 GB/season
- ~3 GB/year at full resolution

### Florence-2 Integration

**Model choice:** Florence-2 base (232M params) in FP16
- Fits in ~500 MB VRAM
- 2-3 second inference on RTX 4050 6GB
- Two prompt tracks:
  - `<CAPTION>` for chart state description (4-min cadence)
  - Structured extraction for sounder analysis (30-s cadence)

**Training data pipeline:**
1. Bootstrap: ~500 labeled frames (Captain labels week 1)
2. Semi-supervised: current OpenCV pipeline as weak labeler
3. Active learning: model disagreements become training candidates
4. LoRA fine-tuning: PEFT on accumulated labels

### GPU Scheduling (Ebb and Flow)

Constraint: Florence-2 and Ollama share 6GB VRAM.

Solution: time-multiplexed pipeline.

```
T=0s:  Capture → Florence-2 (screen description) → TileDB write → release VRAM
T=20s: Ollama query (if needed) → release VRAM
T=30s: Next capture → Florence-2 → ...
```

Fallback: when GPU contended, OpenCV pipeline takes over. No data lost.

### Catch Correlation Loop

Three-phase algorithm:
1. **Feature extraction** — from 10-frame echogram windows: vertical intensity profiles, bottom depth and hardness, fish arch rate, depth-stratified histogram
2. **Signature library** — stored in SQLite, keyed by species tag
3. **Similarity search** — 64-dim feature vectors, weighted cosine similarity

Confidence: "73% match to July 22 chum school at 25 fm."

---

## Section 3: The DAW Dashboard Design

*Synthesized from the DeepSeek Pro product spec.*

### Track Layout

8 track types, stacked vertically. Three states per track:

| State | Height | Content |
|-------|--------|---------|
| Collapsed | 24px | Sparkline, track name, last value |
| Expanded | 120-200px | Full visualization |
| Focused | 70% viewport | Deep dive |

**Track types:**
1. **Echogram** — 30-second sounder crops quilted side-by-side. Colored tiles with depth scale, bottom line overlay, fish return markers
2. **Rudder angle** — Waveform oscillating above/below centerline
3. **SOG envelope** — Filled area with trolling-band color coding (green=trolling, blue=transit, red=drift)
4. **Compass heading** — Continuous line with 0°/360° wrap handling
5. **Bite events** — MIDI-style note-ons. Species = MIDI channel color, size = velocity, depth = pitch
6. **Catch log** — Stamped entries with species icon, count, weight
7. **Conversation** — Scrolling ticker tape, timestamped messages
8. **Video / audio** — Optional stream track

### Timeline & Fractal Zoom

Detented slider with 10 snap points:
```
30s → 2min → 10min → 1hr → 4hr → 1day → 1week → 1month → 1season → 3year
```

Not linear — magnetic snaps to natural fishing time-scales (pass, area, opening, day, trip, month, season, career).

Keyboard: `1`-`0` jump to presets. Ctrl+Scroll zooms with momentum.

Level-of-detail pyramid for echogram tiles at 4 resolutions. At season scale, tiles blend into a single heatmap. At career scale, three season-stripes stack vertically aligned by calendar date.

### The Echogram Track

370×900 sounder crops quilted side by side. At 30s intervals, an 8-hour day renders as 960 tiles × 370px wide = 355,200px of echogram. The horizontal scroll never ends because the timeline is continuous from first boot.

Each tile rendered with:
- Depth scale overlay (right edge)
- Bottom line (colored by hardness — green=hard, blue=soft, red=rock)
- Fish return markers (bright dots at detection depth)
- Thermocline bands (subtle horizontal color shifts)

### Bite Events as MIDI

A bite is a note-on event. The MIDI metaphor is not decorative — it's structural:
- **Note number** = hook depth (MIDI note 48 = 4fm, note 96 = 48fm)
- **Velocity** = fish size / strike intensity
- **Channel** = species (channel 1 = king, 2 = chum, 3 = halibut)
- **Aftertouch** = fight duration / line tension
- **Pitch bend** = depth change during the fight

A piano roll view of a fishing day shows exactly where the action was, at what depth, with what intensity. No words needed.

### Navigation Controls

The 5th dimension (scale) is controlled by the zoom slider. The 4th dimension (time as waveform) is controlled by:
- **Playhead** — draggable cursor across the timeline. Scrubbing updates all tracks in sync.
- **Loop bracket** — select a time range. System plays it on repeat, like a DAW loop.
- **Markers** — named time points. "Hookup at 14:32," "Bottom transition at 15:07," "Tide change at 16:00."
- **Tide-aligned warp** — re-grid timeline by tide state instead of clock time. This collapses multiple days into a single tidal cycle for comparison.

### Rendering Engine

Hybrid approach:
- **DOM** for UI chrome: transport controls, track headers, slider, search bar, marker labels
- **`<canvas>`** for the arrangement area: all 8 tracks rendered in a single canvas context
- **Web Worker** for pattern matching, tile decoding, similarity search
- **Level-of-detail pyramid** for echogram tiles at 4 resolutions

Server sends:
- Current-resolution tiles (blitted directly to canvas via ImageData)
- SQLite query results (position lookups, catch events)
- Pattern match results (confidence scores, similar frame ranges)

### Three Audiences

**Captain (wheelhouse):** Passive record-arm mode. Glances for <30 seconds at a time. Green pattern brackets on the timeline demand attention without requiring clicks. The dashboard recedes when nothing is happening.

**Partner (at home):** Warm "safety + catch + ETA" view. Simple map with vessel position, daily catch summary, conversation snippets. No sounder. No rudder.

**Daughter (iPad at dinner):** Cartoon boat on a stylized chart. Tappable fish with kid-friendly weight comparisons ("that's as heavy as a golden retriever!"). Echogram data rendered as decorative background pattern.

### Development Phases

1. **Static Replay** — A week's existing captures. Local files. Read-only timeline scrub. Prove the rendering engine.
2. **Timeline Navigation** — Live data from TileDB. Full zoom range. Marker placement. Loop brackets.
3. **Live Data** — Real-time tile ingestion. Pattern matching background thread. Green bracket push notifications.
4. **Intelligence Layer** — Catch correlation. Species prediction. Confidence display.
5. **Polish & Audiences** — Partner view. Kid view. Fleet aggregation.

---

## Section 4: The Learning Loop

*The prediction loop that learns to spot fish at cruise speed.*

### The Catch Correlation Loop

```
Every 30 seconds:
  1. Capture sounder tile
  2. Extract 64-dim feature vector:
     - Bottom depth (float)
     - Bottom hardness score (float: 0.0-1.0)
     - Bottom roughness (float: stddev in px)
     - Fish return count (int)
     - Fish depth distribution (10-bin histogram)
     - Thermocline count (int)
     - Thermocline depth range (float, float)
     - Signal profile (3x float: avg r/g/b)
  3. Query signature library:
     - Cosine similarity against known catch windows
     - Return top 5 matches with confidence
  4. If confidence > threshold:
     - Log prediction: "73% match to July 22 chum school at 25 fm"
     - Push to dashboard (green bracket on timeline)
```

### Species Learning

When Captain logs a catch:
1. Timestamp + position + species + count
2. System retrieves the 20-frame echogram window around that time
3. Extracts feature vectors from all 20 frames
4. Stores as species signature in SQLite reference library
5. Next time a similar feature vector appears → recall matches

Over a season, the library grows from zero to thousands of labeled windows.
The prediction confidence increases with every catch logged.

### Running-Speed Spotter

The end-state: vessel cruising at 10 kn. Sounder pinging every 30 seconds. Tzpro-agent watching the echogram, comparing against the signature library. When a school passes beneath the hull that matches a known catch signature:

"Slow down. 78% confidence chum school at 25 fm. Similar signature to July 22 at the north end of the bank."

The captain decides whether to drop gear.

---

## Section 5: Riker's Synthesis — What We Build First

### Phase 1: Current State (Week of Jul 15, 2026)

- [x] Screen capture pipeline (30s sounder / 4min full frame)
- [x] Sounder crop + OpenCV analysis
- [x] NMEA position pairing
- [x] Daily structured logging (JSONL)
- [x] GitHub repos (tzpro-agent, hermit-crab with founding document)

### Phase 2: Florence-2 Integration (Weeks 1-3)

- [ ] Install Florence-2 base (232M params, FP16)
- [ ] Replace OpenCV thresholds with VL screen description
- [ ] Build chart delta logger (Florence-2 compares sequential frames)
- [ ] Train: Captain labels ~500 frames over first week of use
- [ ] LoRA fine-tuning on accumulated labels

### Phase 3: TileDB & Catch Correlation (Weeks 3-6)

- [ ] Install TileDB-Py
- [ ] Define 3D array schema (time × depth × ping)
- [ ] Migration script: JSONL → TileDB
- [ ] Feature vector extraction from echogram tiles (64-dim)
- [ ] SQLite signature library with species key
- [ ] Cosine similarity query — "this looks like X% of the July 22 chum school"

### Phase 4: The DAW Dashboard (Weeks 6-12)

- [ ] Static replay from existing captures
- [ ] Timeline scrub with 3 zoom levels
- [ ] Echogram tile rendering (canvas, quilted)
- [ ] Track layout (echogram, SOG, bites, conversation)
- [ ] MIDI-style bite visualization
- [ ] Pattern markers (green brackets)

### Phase 5: Live Intelligence (Weeks 12+)

- [ ] Real-time pattern matching
- [ ] Species prediction push notifications
- [ ] Running-speed spotter
- [ ] Fleet aggregation (multi-boat)
- [ ] Partner and kid views
- [ ] The self-installing agent

---

## The Promise

A system that learns to read your water the way you learned to read your water — by watching, season after season, until the pattern is so familiar that you stop looking at the screen and just know.

The highest form of this technology: you forget it's there.

When you're on the fish, everything is the fish. The dashboard recedes. The echogram becomes background. The conversation between you and the boat is direct, unmediated.

Then, when you're running at 10 kn scanning for sign, and a bubble of green confidence appears on the timeline — "75% match to the kings you found on the western edge last August, 28 fm, hard bottom, tide incoming" — you glance at the screen, read the number, make the call.

That's the system. That's the tool that disappears and reappears exactly when you need it.

---

*Part of the CoCapn ecosystem — CoCapn.com / ActiveLedger.ai / FishingLog.ai*
*F/V EILEEN, Ketchikan Alaska, July 15, 2026*
