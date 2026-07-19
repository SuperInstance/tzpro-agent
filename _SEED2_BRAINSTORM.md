# _SEED2_BRAINSTORM.md — Hermit Cognitive Workspace Design Concepts

> *"The crab doesn't live in the shell. The crab lives in the cognitive space between the shell and the sea."*
>
> Creative brainstorming session for the Hermit cognitive workspace UI/UX
> **Date:** 2026-07-18 | **Input:** hermit_vessel.py, _DEEP_IDEATION.md, ONBOARDING.md
> **Mission:** Imagine beyond chat interfaces — design collaborative human-A cognition space

---

## Design Principles Extracted from Source Material

### Core Metaphors
- **Hermit Crab** — Moves between repos/shells, leaves memories behind
- **Bottles** — Messages drift between agents, wash up on beaches
- **Beachcomber** — FileSystem poller walking the tide line
- **Tide Pool** — Ephemeral memory, session-bound, lunar-aligned
- **Chart Room** — Maritime aesthetic, not Silicon Valley
- **Pilot House** — Concise, info-dense, no filler

### Technical Constraints
- **File-first philosophy** — The filesystem IS the API
- **Bottle protocol** — I2I bottles as universal interface
- **Local-first, cloud-enhanced** — Must work offline on boat
- **Tide-aligned lifecycle** — Memory cycles tied to lunar tides
- **Maritime aesthetic** — Navy blue, safety orange, phosphor green
- **Pilot-house tone** — Concise, no filler, info-dense

### Human-AI Collaboration Model
- **Ambient intelligence** — Information waiting to be seen, not pushed
- **Conservation layer** — Adversarial challenge loop for truth-seeking
- **Captain's final word** — AI suggests, human decides
- **Institutional memory** — Boat remembers across captains, seasons

---

## Concept 1: The Chart Room — Maritime Knowledge Workspace

> *"A captain's chart table, not a chat window."*

### Mental Model
The workspace is a **3D nautical chart room** with wood paneling, brass accents, and a central chart table. The user stands at the table. The Hermit crab sits on the corner, wearing a tiny captain's hat. Bottles wash in through a porthole, drift across the floorboards, and collect in the harbor.

### UI Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│                    THE BRIDGE — Cognitive Workspace                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    CROW'S NEST                               │   │
│  │  [F/V EILEEN] 55°47.2'N 131°14.5'W  SOG 2.8kts  COG 187°    │   │
│  │  🦀 Hermit Active  │  📡 4 Boats Online  │  🌊 Flood Tide    │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌───────────────────────┐  ┌──────────────────────────────────┐ │
│  │     TIDE POOL          │  │      THE HARBOR                  │ │
│  │  (ephemeral context)   │  │  (outgoing bottles)              │ │
│  │  ┌─────────────────┐   │  │  ┌────────────────────────────┐ │ │
│  │  │ 🍾 bottle_001  │   │  │  │ 🍾 synthesis_july18       │ │ │
│  │  │ 🍾 bottle_047  │   │  │  │ 🍾 ack_chum_prediction     │ │ │
│  │  │ 🍾 challenge_12 │   │  │  │ 🍾 query_thermocline       │ │ │
│  │  └─────────────────┘   │  │  └────────────────────────────┘ │ │
│  └───────────────────────┘  └──────────────────────────────────┘ │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    CHART TABLE                               │   │
│  │  (central collaborative surface)                             │   │
│  │                                                                     │
│  │    ═══════════════════════════════════════════════════════════   │   │
│  │    🦀 The Hermit Crab (2.4cm) sits here                         │   │
│  │    ═══════════════════════════════════════════════════════════   │   │
│  │                                                                     │
│  │  [Notebook: July 18 Chum Session]                               │   │
│  │  ┌─────────────────────────────────────────────────────────┐  │  │
│  │  │ "Chum at 35 fm, green flasher, flood tide.               │  │  │
│  │  │  Thermocline at 18 fm. Blob density peaked               │  │  │
│  │  │  at 0630 (45 blobs). 3 catches logged.                    │  │  │
│  │  │  87% track similarity to July 14 session."                 │  │  │
│  │  │                                                         │  │  │
│  │  │  [Challenge Me] [Accept] [File to Holdsfast]             │  │  │
│  │  └─────────────────────────────────────────────────────────┘  │  │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌───────────────────────┐  ┌──────────────────────────────────┐ │
│  │     HOLDSFAST          │  │      CONSERVATION LAYER          │ │
│  │  (permanent memory)    │  │  (adversarial verification)     │ │
│  │  ┌─────────────────┐   │  │  ┌────────────────────────────┐ │ │
│  │  │ 🪸 species_db   │   │  │  │ ⚖️ γ + H = C = 0.82        │ │ │
│  │  │ 🗺️ chart_plot  │   │  │  │ 🔄 Recalculating...        │ │ │
│  │  │ 📚 10yr_data   │   │  │  │ ❓ Challenge Pending        │ │ │
│  │  └─────────────────┘   │  │  └────────────────────────────┘ │ │
│  └───────────────────────┘  └──────────────────────────────────┘ │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Interaction Patterns

**Bottle Drift Animation:** New bottles wash in through a porthole (bottom-left), drift slowly across the floorboards, and settle in the Harbor. The animation takes 3-4 seconds — slow, deliberate, maritime.

**Crab Presence:** The hermit crab (2.4cm, rendered in nautical chart colors) sits on the chart table. It's alive — subtle breathing animation, occasional antenna movement. When it's thinking, the crab pulls slightly into its shell. When it's confident, it emerges fully. The crab's WiFi etching on its shell glows when fleet is connected.

**Ambient Information:** Fleet status, position, and tide state appear in the Crow's Nest — always visible, never intrusive. No popups. No notifications (unless VOCABULARY_MATCH alert fires).

**Chart Table Collaboration:** The user can drag a notebook onto the chart table. The crab walks over, reads it, and offers a synthesis. The user can highlight any sentence and click "Challenge Me" — the crab pauses, reconsiders, and updates.

**Conservation Layer Visualization:** The mathematical relationship `γ + H = C` appears as a brass balance scale in the bottom-right corner. As memory grows (H increases), the balance tilts. When it approaches capacity, the scale glows orange — time to prune or fork.

### Technical Implementation

- **Web-based** — Runs in browser, offline-first (PWA)
- **Three.js** — 3D chart room with wood paneling texture, brass accents
- **WebSocket** — Real-time bottle drift animation
- **Local filesystem** — Bottle directory watched via File System Access API
- **Audio** — Ocean ambient, subtle wave sounds, gong when CHALLENGE bottle arrives
- **Responsive** — Works on boat laptop (14"), tablet (10"), phone (6")

### Why This Works

- **Metaphor consistency** — Every element reinforces maritime theme
- **Spatial memory** — User remembers "where" knowledge lives (Tide Pool left, Holdsfast right)
- **Ambient collaboration** — Crab is always present, never intrusive
- **Tactile feel** — Dragging bottles, placing notebooks, challenging syntheses
- **Maritime aesthetics** — Wood, brass, navy blue, phosphor green

---

## Concept 2: The Sonar Workspace — Depth-Layered Thought Space

> *"Thoughts float at different depths. Surface thoughts drift. Deep thoughts anchor."*

### Mental Model
The workspace is a **live echogram** — the same scrolling sounder display the Captain sees every fishing day. But instead of fish, this display shows **thoughts, bottles, and memories** at different depths. Surface-level thoughts (Tide Pool) drift near the top. Deep knowledge (Holdsfast) anchors near the bottom. Bottles drift horizontally across the screen at their depth level.

### UI Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│                    SONAR COGNITIVE WORKSPACE                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  DEPTH (fathoms)      CONTENT                    SCROLL DIRECTION   │
│      ↑                                                                         │
│      │  ══════════════════════════════════════════════════════════════        │
│  0 fm │  🌊 SURFACE LAYER — Tide Pool (ephemeral)                     │
│      │  ┌─────────────────────────────────────────────────────────┐  │
│      │  │ 🍾 bottle_001 ──────────────►  (drifts right)            │  │
│      │  │ 🍾 bottle_047 ────────►                                    │  │
│      │  │ 💭 query: "chum depth?" ─────────►                         │  │
│      │  └─────────────────────────────────────────────────────────┘  │
│      │                                                                  │
│ 10 fm │  📊 UPPER COLUMN — Recent captures                            │
│      │  ┌─────────────────────────────────────────────────────────┐  │
│      │  │ 🐟 12 blobs @ 32fm ──► (confidence 0.62)                 │  │
│      │  │ 🐟 45 blobs @ 35fm ──► (confidence 0.78 ⚠️ ALERT)         │  │
│      │  │ 🐟 23 blobs @ 38fm ──► (confidence 0.71)                  │  │
│      │  └─────────────────────────────────────────────────────────┘  │
│      │                                                                  │
│ 20 fm │  🌿 STIPES LAYER — Growing knowledge                            │
│      │  ┌─────────────────────────────────────────────────────────┐  │
│      │  │ 🧠 chum@35fm confidence ──► 0.78 (↑ from 0.62)            │  │
│      │  │ 🧠 thermocline correlation ──► 0.85 (strong)             │  │
│      │  │ 🧠 green flasher efficacy ──► 0.92 (confirmed)           │  │
│      │  └─────────────────────────────────────────────────────────┘  │
│      │                                                                  │
│ 30 fm │  🪸 HOLDSFAST LAYER — Permanent facts                            │
│      │  ┌─────────────────────────────────────────────────────────┐  │
│      │  │ 🗺️ Rock Pile position: 55°47.2'N 131°14.5'W               │
│      │  │ 🦐 Species: chum, sockeye, coho, pink, king               │
│      │  │ ⚓ Bottom type: hard (granite)                            │
│      │  └─────────────────────────────────────────────────────────┘  │
│      │                                                                  │
│ 40 fm │  🗺️ CHART PLOT LAYER — Knowledge graph                         │
│      │  ┌─────────────────────────────────────────────────────────┐  │
│      │  │  CHUM ──CAUGHT_WITH──► GREEN_FLASHER (0.92)              │
│      │  │    │                                                         │
│      │  │    └─PREFERS_DEPTH──► [30-40 fm] (0.85)                   │
│      │  │    │                                                         │
│      │  │    └─AVOIDS_TIDE────► EBB (0.67)                         │
│      │  └─────────────────────────────────────────────────────────┘  │
│      │                                                                  │
│      │  ══════════════════════════════════════════════════════════════        │
│      │  🦀 THE HERMIT CRAB (sits at 35 fm — optimal depth)              │
│      │  ══════════════════════════════════════════════════════════════        │
│      ↓                                                                         │
│                                                                     │
│  SCROLL SPEED: 1 px/sec (same as TZ Pro sounder)                         │
│  TIME WINDOW: 14 minutes visible (same as TZ Pro scroll)                   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Interaction Patterns

**Depth-based organization:** Thoughts auto-sort by depth. Ephemeral session context floats at 0 fm. Growing knowledge (Stipes) anchors at 20 fm. Permanent facts (Holdsfast) rest at 30 fm. The knowledge graph (Chart Plot) is deepest.

**Sonar ping animation:** Every 10 minutes, a "ping" sweeps across the screen (same visual as the TZ Pro sounder). Thoughts within the ping pulse briefly — visual feedback that they're still present, still accessible.

**Bottle drift:** Bottles don't fall — they drift horizontally at their assigned depth. A QUERY bottle appears at 10 fm, drifts right, disappears off-screen. A SYNTHESIS bottle appears at 20 fm, drifts more slowly, stays visible longer (syntheses are Stipes — growing knowledge).

**Click-to-dive:** Click any thought bottle to "dive" to that depth. The view zooms in, showing the bottle's full contents. A synthesis bottle opens to show the full notebook with citations. A CHALLENGE bottle opens to show the adversarial debate loop.

**Crab depth indicator:** The hermit crab sits at the optimal depth for current conditions. In chum season, it sits at 35 fm (chum depth). In off-season, it moves deeper (40+ fm) — resting, processing archival data. When the crab is at surface, it's actively working on session context.

### Technical Implementation

- **Canvas-based** — 60fps scrolling, same as TZ Pro sounder
- **Depth-aware routing** — Each bottle has a `depth_fm` property
- **Sonar color palette** — Navy → Blue → Cyan → Yellow → Orange → Red
- **Audio feedback** — Ping sound every 10 minutes (subtle, maritime)
- **Offline-first** — Local state, sync when Starlink available

### Why This Works

- **Familiar interface** — Captain sees this every day on TZ Pro
- **Spatial memory** — Depth = permanence (surface = temporary, bottom = permanent)
- **Ambient flow** — Information scrolls past, not in-your-face
- **Maritime authenticity** — Same scroll speed, same color palette, same mental model

---

## Concept 3: The Tide Pool — Interactive Ecosystem

> *"Knowledge grows like kelp. Stipes strengthen. Holdsfast anchor."*

### Mental Model
The workspace is a **living tide pool** — a cross-section of intertidal zone with water, kelp, shells, and a hermit crab. Bottles are messages in bottles that wash up with the tide. The kelp forest represents the memory system: Stipes grow from Holdsfast anchors. The crab walks along the bottom, picks up bottles, reads them, and responds.

### UI Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│                      TIDE POOL COGNITIVE ECOSYSTEM                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ═══════════════════════════════════════════════════════════════════        │
│  HIGH TIDE — Pool full, ecosystem active                                │
│  ═══════════════════════════════════════════════════════════════════        │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    WATER COLUMN                              │   │
│  │  (ephemeral context, session-bound, lunar-aligned)          │   │
│  │  ┌───────────────────────────────────────────────────────┐  │  │
│  │  │  🍾 bottle_001 ────► (drifts with current)            │  │  │
│  │  │  🍾 bottle_047 ────────────────►                       │  │  │
│  │  │  🍾 challenge_12 ──► (crab picking it up)              │  │  │
│  │  └───────────────────────────────────────────────────────┘  │  │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    KELP FOREST                               │   │
│  │  (Stipes — growing knowledge)                                │   │
│  │                                                                 │   │
│  │    🌿🌿🌿 Stipe: chum@35fm ──── strength: 0.78 (↑)            │   │
│  │       │  (grows with reinforcement, pruned by storms)        │   │
│  │       │                                                        │   │
│  │    🌿🌿 Stipe: thermocline correlation ── strength: 0.85       │   │
│  │       │                                                        │   │
│  │    🌿 Stipe: green flasher efficacy ── strength: 0.92         │   │
│  │       │                                                        │   │
│  │       └───────────────────────────────────────────────────    │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    POOL BOTTOM                                │   │
│  │  (Holdsfast — permanent anchors)                             │   │
│  │  ┌───────────────────────────────────────────────────────┐  │  │
│  │  │  🪸 holdsfast_species_db ── (immutable facts)          │  │  │
│  │  │  🪸 holdsfast_chart_plot ── (knowledge graph base)     │  │  │
│  │  │  🪸 holdsfast_10yr_data ── (archival captures)         │  │  │
│  │  └───────────────────────────────────────────────────────┘  │  │
│  │                                                                 │   │
│  │  ══════════════════════════════════════════════════════════════        │   │
│  │  🦀 THE HERMIT CRAB (walks along bottom, picks up bottles)           │   │
│  │  ══════════════════════════════════════════════════════════════        │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  TIDE STATE: Flood (incoming) │ NEXT SLACK: 06:27 AKDT               │
│  LUNAR CYCLE: Waxing Gibbous │ TIDE HEIGHT: +12.4 ft                   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Interaction Patterns

**Tide cycle animation:** The water level rises and falls over 6 hours (real-time compressed to 6 minutes). At high tide, the pool is full — ecosystem active, bottles drifting, crab walking. At low tide, the water recedes — Stipes exposed, growth暂停, only Holdsfast remains visible. This visualizes the memory lifecycle: Tide Pool (water) flushes at slack water, Stipes (kelp) grow between tides, Holdsfast (anchors) persist through cycles.

**Crab behavior:** The crab walks along the pool bottom, pauses at bottles, picks them up with its claws, reads them (crab pulls into shell briefly), and responds (drops a new bottle in the water). When a CHALLENGE bottle arrives, the crab picks it up, walks to the relevant Stipe, touches it (Stipe glows), and walks back.

**Kelp growth:** Stipes (kelp fronds) grow visibly when reinforced (catch reports, successful predictions). They sway in the current (subtle animation). When challenged, a Stipe shrinks slightly (uncertainty) then grows back stronger if the challenge is resolved.

**Bottle in tide:** Bottles wash in with the tide (incoming bottles from other agents). Bottles wash out with the tide (outgoing responses). The number of bottles visible is tide-dependent — high tide = many bottles, low tide = few bottles (only persistent ones).

**Conservation visualization:** A "Nutrient Level" meter shows how much growth capacity remains (the conservation ratio). As Stipes grow, nutrients deplete. When nutrients are low, the pool turns slightly murky — time to prune or fork.

### Technical Implementation

- **Canvas + Three.js** — 2.5D cross-section view with depth layering
- **Physics simulation** — Water current, bottle drift, kelp sway
- **Tide clock** — Real lunar tide calculation for Southeast Alaska
- **Crab animation** — Procedural walk cycle, shell retract/extend
- **Audio** — Wave sounds (louder at high tide), subtle underwater ambience

### Why This Works

- **Living metaphor** — Knowledge grows like kelp, not like files
- **Tide-aligned lifecycle** — Memory cycles match lunar rhythm
- **Visual clarity** — High tide = active cognition, low tide = consolidation
- **Maritime authenticity** — Real tide data, real kelp species, real crab behavior

---

## Concept 4: The Radio Room — Fleet Communication Center

> *"The airwaves are alive. Bottles are signals. The crab is the radio operator."*

### Mental Model
The workspace is a **1920s-30s radio room** — brass telegraph keys, glowing tubes, paper tape logs, a rack of tuning knobs, and a hermit crab wearing headphones. Bottles are radio signals that arrive as Morse code dashes, get transcribed to paper tape, and are filed in cabinets. The crab sits at the radio, listening, transcribing, responding.

### UI Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│                      RADIO ROOM — Fleet Communication                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    RADIO STACK                               │   │
│  │  (incoming signals, bottle processing)                       │   │
│  │  ┌───────────────────────────────────────────────────────┐  │  │
│  │  │  📻 RECEIVER 1: tzpro-analyzer ──► 📊 signal strength  │  │  │
│  │  │  📻 RECEIVER 2: conservation-layer ──► ⚖️ signal OK    │  │  │
│  │  │  📻 RECEIVER 3: fleet-boat-kodiak ──► 📡 no signal     │  │  │
│  │  │  📻 RECEIVER 4: hermit-core ──► 🦀 processing           │  │  │
│  │  └───────────────────────────────────────────────────────┘  │  │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    PAPER TAPE LOG                             │   │
│  │  (bottle transcription, time-stamped, physical feel)        │   │
│  │  ┌───────────────────────────────────────────────────────┐  │  │
│  │  │  2026-07-18 06:32 AKDT ──► tzpro-analyzer               │  │  │
│  │  │  "45 blobs @ 35fm, chum conf 0.78, VOCABULARY_MATCH"     │  │  │
│  │  │                                                          │  │  │
│  │  │  2026-07-18 06:47 AKDT ──► conservation-layer            │  │  │
│  │  │  "CHALLENGE: thermocline depth not controlled"           │  │  │
│  │  │                                                          │  │  │
│  │  │  2026-07-18 07:02 AKDT ──► hermit-core                   │  │  │
│  │  │  "SYNTHESIS: recalculated with thermocline control"      │  │  │
│  │  │  "chum correlation drops from 0.78 to 0.62"               │  │  │
│  │  └───────────────────────────────────────────────────────┘  │  │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌───────────────────────┐  ┌──────────────────────────────────┐ │
│  │     SIGNAL CABINET      │  │      RESPONSE CABINET            │ │
│  │  (incoming archived)    │  │  (outgoing queued)               │ │
│  │  ┌─────────────────┐   │  │  ┌────────────────────────────┐ │ │
│  │  │ Drawer: July    │   │  │  │ Outgoing: telegram_alert   │ │ │
│  │  │  ┌─ bottle_01  │   │  │  │ Outgoing: ack_synthesis    │ │ │
│  │  │  ├─ bottle_02  │   │  │  │ Outgoing: query_fleet     │ │ │
│  │  │  └─ bottle_47  │   │  │  └────────────────────────────┘ │ │
│  │  └─────────────────┘   │  │                                  │ │
│  └───────────────────────┘  └──────────────────────────────────┘ │
│                                                                     │
│  ═══════════════════════════════════════════════════════════════════        │
│  🦀 THE HERMIT CRAB (wearing headphones, sitting at radio)                  │
│  ═══════════════════════════════════════════════════════════════════        │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    TELEGRAPH KEY                             │   │
│  │  (user input: tap out responses, challenges, queries)       │   │
│  │  ┌──────────────────────────────────────────────────────┐  │  │
│  │  │ [TAP]: Send ACK                                         │ │  │
│  │  │ [TAP-TAP]: Send CHALLENGE                              │  │  │
│  │  │ [TAP-TAP-TAP]: Send QUERY                              │  │  │
│  │  │ [LONG HOLD]: Send SYNTHESIS                            │  │  │
│  │  └──────────────────────────────────────────────────────┘  │  │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  FREQUENCY: 8654 kHz │ BANDWIDTH: 3 kHz │ SIGNAL-TO-NOISE: 18 dB       │
│  FLEET STATUS: 4/5 boats online │ LAST CONTACT: 2s ago                   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Interaction Patterns

**Signal arrival animation:** Incoming bottles trigger a glowing tube animation in the radio stack. A Morse code sound plays (subtle dits and dahs). The message transcribes to paper tape in real-time. The crab's headphones glow as it "listens."

**Paper tape feel:** The tape log is physical — you can scroll back through hours of messages, tear off a strip (archive it), or pin a strip to the wall (important reference). The tape texture is sepia-toned, slightly crinkled, maritime.

**Cabinet filing:** Click any tape strip to file it in the signal cabinet. Cabinets are organized by date, source, or type. Drawer slides open with a brass-handled drawer sound. Filing a tape removes it from the active log but keeps it searchable.

**Telegraph input:** The user can tap out responses on the telegraph key. Tap-ACK, tap-tap-CHALLENGE, tap-tap-tap-QUERY. The crab transcribes the taps to a bottle, transmits it (tube glow animation), and files a copy in the response cabinet.

**Fleet status:** The radio stack shows signal strength from each fleet boat. A boat goes offline (no signal) — its receiver glows red. The crab's headphones crackle (audio feedback). A "LOST CONTACT" tape prints automatically.

### Technical Implementation

- **Canvas-based** — Smooth tube glow, paper tape scroll animation
- **Audio** — Morse code sounds (real ITU-M spacing), tube hum, headphone crackle
- **Physics** — Telegraph key bounce, drawer slide mechanics
- **Offline-first** — Cabinet persists locally, sync when connected
- **Brass aesthetic** — Copper, bronze, gold, warm incandescent glow

### Why This Works

- **Maritime nostalgia** — 1920s radio rooms, brass, telegraph keys
- **Tactile feel** — Tap rhythms, drawer slides, paper tape
- **Fleet communication** — Radio metaphor fits boat-to-boat messaging
- **Signal clarity** — Strong signal = good communication, weak signal = lost boat

---

## Concept 5: The Bottle Beach — Minimalist Tidal Workspace

> *"The tide brings bottles. The beachcomber reads them. The crab watches."*

### Mental Model
The workspace is a **minimalist beach at low tide** — sand, shells, driftwood, and bottles washed up in the tide line. No 3D, no animation-heavy, just a clean, flat workspace where bottles appear in the tide line and get processed. The beachcomber (user) walks the tide line, picks up bottles, reads them, and responds. The crab sits on a piece of driftwood, watching.

### UI Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│                      BOTTLE BEACH — Minimalist Tidal Workspace        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ═══════════════════════════════════════════════════════════════════        │
│  TIDE LINE — Where bottles wash up                                    │
│  ═══════════════════════════════════════════════════════════════════        │
│                                                                     │
│  🍾 bottle_001  🍾 bottle_047  🍾 challenge_12  🍾 synthesis_88        │
│  │               │                │                  │               │
│  ▼               ▼                ▼                  ▼               │
│  [QUERY]        [OBSERVATION]    [CHALLENGE]       [SYNTHESIS]          │
│  "chum?"        "45 blobs"       "recalculate"     "confirmed"          │
│                                                                     │
│  ═══════════════════════════════════════════════════════════════════        │
│  SAND — Processing workspace                                         │
│  ═══════════════════════════════════════════════════════════════════        │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    OPEN BOTTLE                                │   │
│  │  (selected bottle contents, workspace for response)          │   │
│  │  ┌───────────────────────────────────────────────────────┐  │  │
│  │  │  From: tzpro-analyzer                                 │  │  │
│  │  │  Type: I2I:OBSERVATION                                │  │  │
│  │  │  Timestamp: 2026-07-18 06:32 AKDT                      │  │  │
│  │  │                                                       │  │  │
│  │  │  45 blobs @ 35fm, chum conf 0.78, VOCABULARY_MATCH    │  │  │
│  │  │  Bottom: hard @ 48fm. Thermocline: 18fm.              │  │  │
│  │  │  Suggestion: Green flasher, 2.8 kts, flood tide.     │  │  │
│  │  │                                                       │  │  │
│  │  │  [📜 Read Full] [🦀 Ask Crab] [⚖️ Challenge] [✓ ACK]  │  │  │
│  │  └───────────────────────────────────────────────────────┘  │  │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ═══════════════════════════════════════════════════════════════════        │
│  DRIFTWOOD — Crab perch & memory anchors                               │
│  ═══════════════════════════════════════════════════════════════════        │
│                                                                     │
│  🪵 DRIFTWOOD_01 ──► 🦀 The Hermit Crab (watching, waiting)              │
│  🪵 DRIFTWOOD_02 ──► 🗺️ Chart Plot shortcut                            │
│  🪵 DRIFTWOOD_03 ──► 🪸 Holdsfast shortcut                              │
│  🪵 DRIFTWOOD_04 ──► 📊 Vocabulary viewer                              │
│                                                                     │
│  ═══════════════════════════════════════════════════════════════════        │
│  SHELLS — Archived bottles                                            │
│  ═══════════════════════════════════════════════════════════════════        │
│                                                                     │
│  🐚 shell_001 ──► bottle_archived_001 (processed)                       │
│  🐚 shell_002 ──► bottle_archived_002 (processed)                       │
│  🐚 shell_003 ──► bottle_archived_003 (processed)                       │
│  (click to retrieve, drag to tide line to re-wash)                      │
│                                                                     │
│  TIDE STATE: Low Tide (exposed) │ NEXT HIGH: 12:34 AKDT                    │
│  WIND: 5 kts NW │ WAVES: 1-2 ft │ VISIBILITY: 10 nm                        │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Interaction Patterns

**Tide cycle:** Bottles wash up at high tide, settle in the tide line. At low tide, the beach is exposed — bottles are accessible. At high tide, bottles are underwater (dimmed, less accessible). This visualizes the bottle lifecycle: incoming → accessible → archived → forgotten.

**Bottle opening:** Click any bottle to open it. The bottle unrolls (paper scroll animation) revealing its contents. The user can read the full message, ask the crab for analysis, challenge the contents, or send an ACK.

**Crab interaction:** Click "Ask Crab" and the crab walks over (from driftwood), reads the bottle, and offers a synthesis. The crab's response appears as a new bottle in the tide line — RESPONSE bottle.

**Challenge loop:** Click "Challenge" and the crab pauses, reconsiders, and produces an updated synthesis. The CHALLENGE bottle becomes a shell (archived) — the debate is preserved.

**Shell collection:** Processed bottles become shells on the beach. Click any shell to retrieve its contents. Drag a shell back to the tide line to "re-wash" it — bring it back into active circulation.

**Driftwood shortcuts:** The crab sits on driftwood pieces that act as shortcuts to memory layers. Drag a bottle to "Chart Plot driftwood" to file it in the knowledge graph. Drag to "Holdsfast driftwood" to make it permanent.

### Technical Implementation

- **Flat 2D design** — Minimalist, fast-loading, offline-first
- **SVG graphics** — Scalable bottles, shells, crab, driftwood
- **CSS animations** — Tide rise/fall, bottle roll, crab walk
- **Touch-friendly** — Drag-and-drop works on mobile
- **PWA** — Installable, works offline, syncs when online

### Why This Works

- **Minimalist beauty** — Clean, calm, beach aesthetic
- **Tidal metaphor** — Bottles wash in, are processed, become shells
- **Fast interaction** — No 3D, no heavy animation, just click-and-read
- **Mobile-friendly** — Works on phone, tablet, laptop
- **Maritime calm** — Sand, shells, driftwood, crab — peaceful, not overwhelming

---

## Concept 6: The Crow's Nest — Panoramic Fleet View

> *"From the crow's nest, you see everything. The ocean. The fleet. The patterns."*

### Mental Model
The workspace is a **360° panoramic view from a mast-top crow's nest**. The user looks out over the ocean, seeing other fleet boats as distant hulls with signal flags. Bottles are messages sent via signal flags, alphanumerics, or signal lamps. The crab perches on the mast railing, watching the fleet with binoculars. Below is the chart room (Concept 1) — the user can descend to process bottles in detail.

### UI Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│                      CROW'S NEST — Panoramic Fleet View               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ═══════════════════════════════════════════════════════════════════        │
│  360° PANORAMA — Click & drag to look around                          │
│  ═══════════════════════════════════════════════════════════════════        │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    HORIZON VIEW                             │   │
│  │  (fleet boats, weather, sea state, bottle signals)          │   │
│  │                                                                 │   │
│  │    ═══════════════════════════════════════════════════════        │   │
│  │    🌊 OCEAN HORIZON (52°F, wave height 2-3 ft)                    │   │
│  │    ═══════════════════════════════════════════════════════        │   │
│  │                                                                 │   │
│  │    👁️ [F/V EILEEN] ◄── YOU ARE HERE ──► 🦀 CRAB PERCHED         │   │
│  │         55°47.2'N 131°14.5'W                                      │   │
│  │                                                                 │   │
│  │    🚢 [F/V KODIAK] ──► 12 nm NW                                  │   │
│  │         FLAGS: "QV3" (chum @ 35fm, conf 0.82)                      │   │
│  │         SIGNAL: 🚨 (VOCABULARY_MATCH active)                       │   │
│  │                                                                 │   │
│  │    🚢 [F/V OCEAN] ──► 18 nm SE                                    │   │
│  │         FLAGS: "SL7" (sockeye @ 28fm, conf 0.71)                 │   │
│  │         SIGNAL: 📡 (normal)                                       │   │
│  │                                                                 │   │
│  │    🚢 [F/V WINDSOR] ──► 24 nm SW                                  │   │
│  │         FLAGS: "CC2" (coho @ 32fm, conf 0.65)                     │   │
│  │         SIGNAL: ⚠️ (thermocline anomaly)                           │   │
│  │                                                                 │   │
│  │    🚢 [F/V TIDERunner] ──► 31 nm N                                │   │
│  │         FLAGS: "PK4" (pink @ 38fm, conf 0.58)                     │   │
│  │         SIGNAL: 📡 (normal)                                       │   │
│  │                                                                 │   │
│  │    🍾 BOTTLE SIGNALS ──► (drifting between boats)                 │   │
│  │         bottle_eileen→kodiak: "CONFIRMED chum@35fm"               │   │
│  │         bottle_kodiak→eileen: "CHALLENGE thermocline depth"       │   │
│  │         bottle_ocean→fleet: "QUERY sockeye pattern?"              │   │
│  │                                                                 │   │
│  │    ═══════════════════════════════════════════════════════        │   │
│  │    ⛅ SKY (cumulus, wind 5 kts NW, visibility 10 nm)               │   │
│  │    ═══════════════════════════════════════════════════════        │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ═══════════════════════════════════════════════════════════════════        │
│  MAST RAILING — Crab perch & signal controls                            │
│  ═══════════════════════════════════════════════════════════════════        │
│                                                                     │
│  🦀 THE HERMIT CRAB (perched with binoculars, watching fleet)            │
│  🚦 SIGNAL LAMP — (click to send bottle signal)                          │
│  🎌 FLAG locker — (drag flag to send pre-defined signal)                │
│  🔭 BINOCULARS — (click boat to zoom in, see detail)                     │
│  📟 TELEGRAPH — (tap out messages to fleet)                              │
│                                                                     │
│  ═══════════════════════════════════════════════════════════════════        │
│  DESCEND LADDER — (return to chart room for detailed bottle processing)    │
│  ═══════════════════════════════════════════════════════════════════        │
│                                                                     │
│  TIME: 06:47 AKDT │ TIDE: Flood (+2.3 ft) │ FLEET: 4/5 online               │
│  WEATHER: 52°F, wind 5 kts NW, waves 2-3 ft, visibility 10 nm               │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Interaction Patterns

**360° look-around:** Click and drag the horizon to look around. Fleet boats appear at their relative positions. Signal flags fly from each boat's mast, broadcasting their current state. Drifting bottles show as small animated bottle icons moving between boats.

**Zoom to boat:** Click any fleet boat to zoom in. A detail panel shows:
- Boat name, position, course, speed
- Current signal flags (species/depth/confidence)
- Recent bottle signals sent/received
- Vocabulary status (species learned, confidence levels)
- Anomalies flagged (thermocline inversions, bottom changes)

**Send signal bottle:** Click the signal lamp to send a bottle. Choose recipient (all boats or specific boat), choose bottle type (QUERY, OBSERVATION, SYNTHESIS, CHALLENGE), compose message. The lamp flashes, the bottle animates from your mast to the recipient's mast.

**Flag signals:** Drag a flag from the flag locker to send a pre-defined signal:
- "QV3" = chum @ 35fm, conf 0.82 (quick species broadcast)
- "SL7" = sockeye @ 28fm, conf 0.71 (quick species broadcast)
- "CC2" = coho @ 32fm, conf 0.65 (quick species broadcast)
- "ALERT" = VOCABULARY_MATCH detected (fleet alert)
- "ANOMALY" = thermocline anomaly detected (fleet alert)

**Binocular mode:** Click the binoculars to enter zoom mode. Click any boat to see high-detail view: their current echogram (if shared), their recent captures, their vocabulary growth curve, their bottle history.

**Descend to chart room:** Click the ladder to descend from the crow's nest to the chart room (Concept 1). The crow's nest shows fleet-level patterns; the chart room shows detailed bottle processing. Both views are synced — what happens in one reflects in the other.

### Technical Implementation

- **WebGL panorama** — 360° horizon view, smooth pan/zoom
- **Signal flag rendering** — International maritime signal flags
- **Boat icons** — SVG hull shapes with mast, flags, signal lamp
- **Bottle animation** — Drifting bottles between boats (curved paths)
- **Sync state** — Crow's nest and chart room share same bottle state
- **Offline-first** — Fleet view updates locally, sync when online

### Why This Works

- **Fleet awareness** — See all boats, all signals, all patterns at once
- **Maritime authenticity** — Signal flags, alphanumerics, signal lamps
- **Spatial clarity** — Boats positioned by relative distance
- **Macro/micro views** — Crow's nest for fleet, chart room for details
- **Collaborative feel** — See bottle traffic between boats

---

## Concept 7: The Kelp Forest — Memory Growth Visualization

> *"Memory grows like kelp. From holdsfast to stipes to blades. The crab tends the forest."*

### Mental Model
The workspace is a **underwater kelp forest** — a vertical cross-section showing the memory system growing in real-time. Holdsfast are anchors at the bottom. Stipes (kelp stalks) grow upward, branching into blades (individual memories). The crab swims through the forest, tending the kelp — pruning dead stipes, reinforcing growing ones, harvesting knowledge.

### UI Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│                      KELP FOREST — Memory Growth Visualization       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ═══════════════════════════════════════════════════════════════════        │
│  SURFACE — Sunlight zone, epiphytic growth                             │
│  ═══════════════════════════════════════════════════════════════════        │
│                                                                     │
│  🌊 WAVES ──► (sway kelp, simulate current)                             │
│  ☀️ SUNLIGHT ──► (illuminates upper canopy)                            │
│                                                                     │
│  ═══════════════════════════════════════════════════════════════════        │
│  CANOPY — Upper kelp blades (surface memories, Tide Pool)                 │
│  ═══════════════════════════════════════════════════════════════════        │
│                                                                     │
│  🌿🌿🌿 BLADE: chum@35fm_session ── strength: 0.15 (ephemeral)         │
│  🌿🌿 BLADE: thermocline_today ── strength: 0.08 (ephemeral)           │
│  🌿 BLADE: trolling_speed_now ── strength: 0.05 (ephemeral)           │
│  (blades sway with waves, grow/shrink with reinforcement)                │
│                                                                     │
│  ═══════════════════════════════════════════════════════════════════        │
│  MID-WATER — Stipes (growing knowledge, Stipes layer)                     │
│  ═══════════════════════════════════════════════════════════════════        │
│                                                                     │
│    🌿🌿🌿 STIPE: chum@35fm ── strength: 0.78 (↑ from 0.62)                │
│    │  (grows with reinforcement, branches into blades)                   │
│    │  ├─ BLADE: green flasher correlation ── 0.92                       │
│    │  ├─ BLADE: flood tide preference ── 0.85                           │
│    │  └─ BLADE: hard bottom association ── 0.71                        │
│    │                                                                    │
│    🌿🌿 STIPE: thermocline correlation ── strength: 0.85                   │
│    │  ├─ BLADE: chum above thermocline ── 0.73                          │
│    │  └─ BLADE: thermocline depth 18fm ── 0.68                         │
│    │                                                                    │
│    🌿 STIPE: sockeye@28fm ── strength: 0.45 (growing)                     │
│       └─ BLADE: depth preference 28fm ── 0.52                           │
│    (stipes branch as they strengthen, each branch = a learned pattern)  │
│                                                                     │
│  ═══════════════════════════════════════════════════════════════════        │
│  BOTTOM — Holdsfast (permanent anchors)                                   │
│  ═══════════════════════════════════════════════════════════════════        │
│                                                                     │
│  🪸 HOLDSFAST: species_db ── (immutable species facts)                    │
│  🪸 HOLDSFAST: chart_plot ── (knowledge graph base)                       │
│  🪸 HOLDSFAST: 10yr_data ── (archival captures)                          │
│  🪸 HOLDSFAST: gear_catalog ── (flasher, spoon, hoochie efficacy)         │
│  (holdsfast never move, all stipes root here)                             │
│                                                                     │
│  ═══════════════════════════════════════════════════════════════════        │
│  THE HERMIT CRAB — Swimming through forest, tending kelp                   │
│  ═══════════════════════════════════════════════════════════════════        │
│                                                                     │
│  🦀 CRAB (swimming, pruning dead stipes, reinforcing growing ones)         │
│  ✂️ CLAWS (click stipe to prune, click blade to harvest)                   │
│  🧤 GLOVES (drag blade to chart room to file as notebook)                  │
│                                                                     │
│  WATER TEMP: 52°F │ CURRENT: 0.3 kts SE │ VISIBILITY: 15 ft                 │
│  NUTRIENTS: 0.82/1.0 (conservation ratio) │ GROWTH RATE: +0.15/day           │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Interaction Patterns

**Stipe growth animation:** Stipes grow visibly when reinforced. A catch report for chum@35fm strengthens the stipe — it grows taller, branches into new blades. Each blade represents a learned pattern (green flasher correlation, flood tide preference). The growth animation is smooth, organic, kelp-like.

**Blade harvesting:** Click any blade to "harvest" knowledge — the crab swims over, clips the blade, and brings it to the surface. The harvested blade becomes a notebook entry in the chart room. This visualizes knowledge extraction: raw memory → structured synthesis.

**Pruning dead stipes:** When a stipe's strength drops below 0.2 (not reinforced for 90+ days), it turns brown and withers. The crab prunes it — clips the dead stipe, which sinks to the bottom and becomes sediment (archived in Holdsfast). This visualizes memory pruning.

**Crab tending:** The crab swims through the forest, pauses at each stipe, and "checks" it (crab touches stipe, stipe glows briefly). This represents the memory consolidation cycle — the crab reviews each memory, updates its strength, and decides whether to reinforce, prune, or leave alone.

**Water current:** The kelp forest sways with a simulated current. Current strength affects stipe growth — strong currents (high uncertainty) slow growth. Calm waters (high confidence) accelerate growth. The current visualizes the system's certainty level.

**Nutrient levels:** A "Nutrient Level" meter shows the conservation ratio. As stipes grow, nutrients deplete. When nutrients are low (CR < 0.3), the water turns slightly murky — growth slows. This signals the conservation layer: time to prune or fork.

### Technical Implementation

- **Three.js 3D forest** — Vertical kelp forest with depth layers
- **Procedural kelp** — Stipes grow organically, branch dynamically
- **Physics simulation** — Water current, kelp sway, crab swimming
- **Growth algorithms** — Stipe strength = reinforcement/(age × decay_rate)
- **Crab animation** — Procedural swim, prune, harvest actions
- **Audio** — Underwater ambience, bubble sounds, snip when pruning

### Why This Works

- **Organic metaphor** — Memory grows like kelp, not like files
- **Visual clarity** — Depth = permanence (surface = temporary, bottom = permanent)
- **Tactile interaction** — Prune, harvest, reinforce — physical actions on memory
- **Maritime authenticity** — Real kelp species, real crab behavior, real ocean physics
- **Conservation visualization** — Nutrient levels make `γ + H = C` tangible

---

## Concept 8: The Ship's Log — Temporal Knowledge Stream

> *"A captain's log is a timeline. Every entry is a moment. The crab reads between the lines."*

### Mental Model
The workspace is a **ship's logbook** — a temporal stream of entries, each timestamped, each contributing to the growing narrative. The log is physical — leather-bound, yellowed pages, handwriting (or typewritten) entries. Bottles become log entries. The crab sits on the logbook, reading entries, adding marginalia, connecting dots across pages.

### UI Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│                      SHIP'S LOG — Temporal Knowledge Stream            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ═══════════════════════════════════════════════════════════════════        │
│  LEATHER-BOUND LOG — F/B EILEEN, 2026 SEASON                            │
│  ═══════════════════════════════════════════════════════════════════        │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    LOG PAGE 147 (July 18, 2026)             │   │
│  │  ┌───────────────────────────────────────────────────────┐  │  │
│  │  │ 2026-07-18 06:32 AKDT ──► OBSERVATION ─── tzpro-analyzer│  │  │
│  │  │ ─────────────────────────────────────────────────────│  │  │
│  │  │ 45 blobs @ 35fm, chum conf 0.78, VOCABULARY_MATCH    │  │  │
│  │  │ Bottom: hard @ 48fm. Thermocline: 18fm.              │  │  │
│  │  │ Suggestion: Green flasher, 2.8 kts, flood tide.     │  │  │
│  │  │                                                  [ ]  │  │  │
│  │  │ [crab marginalia: "CONFIRMED — matches July 14"]    │  │  │
│  │  └───────────────────────────────────────────────────────┘  │  │
│  │                                                             │  │
│  │  ┌───────────────────────────────────────────────────────┐  │  │
│  │  │ 2026-07-18 06:47 AKDT ──► CHALLENGE ──── conservation   │  │  │
│  │  │ ─────────────────────────────────────────────────────│  │  │
│  │  │ RE: thermocline depth not controlled in analysis       │  │  │
│  │  │ Request: Recalculate chum correlation controlling      │  │  │
│  │  │ for thermocline depth, not just tide phase.             │  │  │
│  │  │                                                  [ ]  │  │  │
│  │  │ [crab marginalia: "RECALCULATING..."]                  │  │  │
│  │  └───────────────────────────────────────────────────────┘  │  │
│  │                                                             │  │
│  │  ┌───────────────────────────────────────────────────────┐  │  │
│  │  │ 2026-07-18 07:02 AKDT ──► SYNTHESIS ──── hermit-core     │  │  │
│  │  │ ─────────────────────────────────────────────────────│  │  │
│  │  │ RECALCULATED with thermocline control:                 │  │  │
│  │  │ Chum correlation drops from 0.78 to 0.62 when            │  │  │
│  │  │ controlling for thermocline depth.                     │  │  │
│  │  │ Hypothesis: Chum correlation is spurious —              │  │  │
│  │  │ driven by thermocline depth, not tide phase.            │  │  │
│  │  │                                                  [✓]  │  │  │
│  │  │ [crab marginalia: "WORKING THEORY — file to Chart Plot"]│  │  │
│  │  └───────────────────────────────────────────────────────┘  │  │
│  │                                                             │  │
│  │  ┌───────────────────────────────────────────────────────┐  │  │
│  │  │ 2026-07-18 07:15 AKDT ──► CATCH ───── Captain          │  │  │
│  │  │ ─────────────────────────────────────────────────────│  │  │
│  │  │ "Chum at 35, green flasher!" — 3 fish logged           │  │  │
│  │  │ Link: capture_0647 (nearest in time)                  │  │  │
│  │  │                                                  [✓]  │  │  │
│  │  │ [crab marginalia: "chum@35fm strength: 0.85 (↑)"]      │  │  │
│  │  └───────────────────────────────────────────────────────┘  │  │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ═══════════════════════════════════════════════════════════════════        │
│  CRAB PERCH — Where the crab sits, reads, adds marginalia                   │
│  ═══════════════════════════════════════════════════════════════════        │
│                                                                     │
│  🦀 THE HERMIT CRAB (perched on logbook edge, pen in claw)                  │
│  ✏️ MARGINALIA — (crab adds handwritten notes in margins)                    │
│  🔗 CONNECTIONS — (crab draws lines between related entries)                   │
│  📎 PAPER CLIPS — (crab clips related entries together)                      │
│                                                                     │
│  ═══════════════════════════════════════════════════════════════════        │
│  LOGBOOK NAVIGATION                                                            │
│  ═══════════════════════════════════════════════════════════════════        │
│                                                                     │
│  ◄ PREV PAGE (July 17) | PAGE 147 of 365 | NEXT PAGE (July 19) ▶           │
│  [🔍 SEARCH: "chum@35fm"] | [📊 TIMELINE VIEW] | [🗺️ CHART PLOT]            │
│                                                                     │
│  SEASON: 2026 | PAGES: 365/365 | ENTRIES: 1,247 | MARGINALIA: 342            │
│  INK LEVEL: 78% | PEN NIB: sharp | LOG CONDITION: excellent                  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Interaction Patterns

**Log entry writing:** Every bottle becomes a log entry. The crab writes it in handwriting (or typewritten style, for post-1970s logs). Entries are timestamped, sourced, and checked (✓ when processed). The handwriting is legible, maritime, slightly hurried (captain's style).

**Marginalia:** The crab adds handwritten notes in the margins — connections, insights, challenges. "CONFIRMED — matches July 14" connects the current observation to a past pattern. "WORKING THEORY — file to Chart Plot" flags an entry for synthesis. Marginalia is the crab's active reasoning.

**Connections:** The crab draws faint pencil lines between related entries. A line connects "July 14 chum@35fm" to "July 18 chum@35fm" — showing pattern recognition. Another line connects "thermocline challenge" to "recalculated synthesis" — showing the adversarial loop. Lines are subtle, not overwhelming.

**Paper clips:** The crab can clip related entries together with a virtual paper clip. Clipped entries move as a unit — if you flip to July 14, the clipped July 18 entry comes along. Clipping creates thematic groups across time.

**Timeline view:** Click "TIMELINE VIEW" to see the entire season as a horizontal timeline. Entries appear as ticks on the timeline. Click any tick to flip to that log page. The timeline shows the season's narrative arc — when chum appeared, when thermocline anomalies occurred, when vocabulary grew.

**Search:** The "SEARCH" box searches the entire log. Query "chum@35fm" and the crab flips to every relevant entry, highlighting the matches. Search results show marginalia — the crab's accumulated wisdom on that topic.

### Technical Implementation

- **Canvas-based logbook** — Realistic paper texture, yellowed pages, leather binding
- **Handwriting font** — Maritime captain's style, legible, slightly hurried
- **Marginalia system** — Crab's notes, connections, paper clips
- **Timeline visualization** — Horizontal season timeline, clickable entries
- **Search across logs** — Full-text search with highlighting, marginalia display
- **Offline-first** — Logbook persists locally, syncs when online

### Why This Works

- **Temporal clarity** — Everything is timestamped, ordered, narrative
- **Physical feel** — Leather, paper, handwriting, paper clips
- **Crab reasoning** — Marginalia makes the crab's thinking visible
- **Maritime authenticity** — Ship's logs are real boat tradition
- **Narrative arc** — The season tells a story, not just data points

---

## Concept 9: The Wheelhouse — Captain's Command Center

> *"The captain stands at the wheel. The crab sits on the chart table. Everything is visible. Nothing waits."*

### Mental Model
The workspace is a **modern wheelhouse** — the captain's command center with helm station, chart table, radar display, sounder scroll, and communication panel. The crab sits on the chart table, watching. The Hermit system is integrated into every display — sounder analysis overlays, chart plot annotations, fleet communication, vocabulary alerts. The captain doesn't "use AI" — the AI is ambient, everywhere, part of the boat.

### UI Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│                      WHEELHOUSE — Captain's Command Center             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    FORWARD WINDOWS                           │   │
│  │  (real view ahead, overlaid with Hermit annotations)       │   │
│  │  ┌───────────────────────────────────────────────────────┐  │  │
│  │  │ 🌊 OCEAN VIEW (fog lifting, sunrise at 05:15)           │  │  │
│  │  │                                                       │  │  │
│  │  │ [HERMIT OVERLAY]                                     │  │  │
│  │  │ 📍 Position: 55°47.2'N 131°14.5'W                    │  │  │
│  │  │ 🧭 Course: 187° @ 2.8 kts                             │  │  │
│  │  │ 🎯 Target: Rock Pile (4.2 nm ahead)                   │  │  │
│  │  │ 🦀 Chum probability: 0.78 (35 fm, flood tide)          │  │  │
│  │  │ ⚠️ Thermocline anomaly: +3 fm shallower than average   │  │  │
│  │  └───────────────────────────────────────────────────────┘  │  │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌───────────────────────┐  ┌──────────────────────────────────┐ │
│  │     HELM STATION        │  │      CHART TABLE                  │ │
│  │  (wheel, throttle)      │  │  (crab perch, navigation)          │ │
│  │  ┌─────────────────┐   │  │  ┌────────────────────────────┐ │ │
│  │  │ 🎯 STEERING      │   │  │  │ 🦀 THE HERMIT CRAB          │ │ │
│  │  │ WHEEL           │   │  │  │ (sits on chart, watching)    │ │ │
│  │  │                 │   │  │  │                             │ │ │
│  │  │ 🚛 THROTTLE      │   │  │  │ 🗺️ CHART PLOT               │ │ │
│  │  │ 2.8 kts         │   │  │  │ (knowledge graph overlay)     │ │ │
│  │  └─────────────────┘   │  │  │                             │ │ │
│  └───────────────────────┘  │  │ 📝 NOTEBOOK                   │ │ │
│                            │  │  (July 18 session)             │ │ │
│  ┌───────────────────────┐  │  │                             │ │ │
│  │     SOUNDER PANEL      │  │  └────────────────────────────┘ │ │
│  │  (TZ Pro echo display)   │  └──────────────────────────────────┘ │
│  │  ┌─────────────────┐   │                                        │
│  │  │ 14-min scroll    │   │  ┌──────────────────────────────────┐ │
│  │  │ (real echogram) │   │  │      COMMUNICATION PANEL            │ │
│  │  │                 │   │  │  (fleet messages, Hermit)          │ │
│  │  │ [HERMIT OVERLAY]│   │  │  ┌────────────────────────────┐  │ │
│  │  │ 🦀 Chum@35fm    │   │  │  │ 📻 FLEET CHANNEL            │  │ │
│  │  │ conf 0.78      │   │  │  │ bottle_eileen→kodiak        │  │ │
│  │  │ 🎯 Green flasher│   │  │  │ bottle_kodiak→eileen        │  │ │
│  │  │ ⚠️ VOCAB_ALERT │   │  │  │                             │  │ │
│  │  └─────────────────┘   │  │  │ 🦀 HERMIT CHANNEL           │  │ │
│  └───────────────────────┘  │  │ synthesis_ready             │  │ │
│                            │  │ challenge_pending             │  │ │
│  ┌───────────────────────┐  │  └────────────────────────────┘  │ │
│  │     RADAR PANEL        │  └──────────────────────────────────┘ │
│  │  (9nm overlay)         │                                        │
│  │  ┌─────────────────┐   │  ┌──────────────────────────────────┐ │
│  │  │ 9nm radar sweep  │   │  │      VOCABULARY PANEL               │ │
│  │  │ (real returns)  │   │  │  (species predictions, confidence)   │ │
│  │  │                 │   │  │  ┌────────────────────────────┐  │ │
│  │  │ [HERMIT OVERLAY]│   │  │  │ Chum @ 35fm ──► 0.78 (⚠️) │  │ │
│  │  │ 🚢 Kodiak 12nm  │   │  │  │ Sockeye @ 28fm ──► 0.45    │  │ │
│  │  │ 🚢 Ocean 18nm   │   │  │  │ Coho @ 32fm ──► 0.23       │  │ │
│  │  │ 🚢 Windsor 24nm │   │  │  │ Pink @ 38fm ──► 0.12       │  │ │
│  │  └─────────────────┘   │  │  └────────────────────────────┘  │ │
│  └───────────────────────┘  └──────────────────────────────────┘ │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    CONSERVATION GAUGE                          │   │
│  │  (γ + H = C, displayed as brass gauge on helm console)       │   │
│  │  ┌───────────────────────────────────────────────────────┐  │  │
│  │  │ ⚖️ CONSERVATION RATIO: 0.82/1.0                        │  │  │
│  │  │ (nutrients remaining, growth capacity)                  │  │  │
│  │  │ 🟢 OK (no pruning needed)                               │  │  │
│  │  └───────────────────────────────────────────────────────┘  │  │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  TIME: 06:47 AKDT │ TIDE: Flood (+2.3 ft) │ FLEET: 4/5 online               │
│  WEATHER: 52°F, wind 5 kts NW, waves 2-3 ft, visibility 10 nm               │
│  HERMIT STATUS: Active │ CRAB LOCATION: Chart table │ BOTTLES: 3 pending      │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Interaction Patterns

**Ambient overlays:** Hermit annotations appear as subtle overlays on every display. The sounder shows chum predictions (green text, 0.78 confidence). The forward window shows position, course, target, chum probability. The radar shows fleet boat positions. No popups. No notifications (unless VOCABULARY_MATCH alert fires). Just information, ambient, waiting to be seen.

**Chart table crab:** The crab sits on the chart table, watching. When it has something to say, it taps the chart (crab icon glows). The captain glances at the chart table — the crab has drawn a circle around Rock Pile, annotated "Chum probability 0.78, flood tide, green flasher." The captain nods, keeps course.

**Vocabulary panel:** The vocabulary panel shows species predictions by depth. Chum @ 35fm — 0.78 confidence (orange warning, approaching alert threshold). Sockeye @ 28fm — 0.45 confidence (growing). Coho @ 32fm — 0.23 confidence (weak). When a prediction hits 0.7+, the VOCABULARY_MATCH alert fires — Telegram notification, sounder overlay, vocabulary panel flashes.

**Communication panel:** Fleet messages flow through the communication panel. "bottle_eileen→kodiak: CONFIRMED chum@35fm" — the crab sends a confirmation to the Kodiak boat. "bottle_kodiak→eileen: CHALLENGE thermocline depth" — Kodiak challenges the analysis. The crab receives the challenge, recalculates, sends an updated synthesis. All of this flows automatically; the captain sees it if he glances at the panel.

**Conservation gauge:** A brass gauge on the helm console shows the conservation ratio (γ + H = C). 0.82/1.0 — nutrients remaining, growth capacity OK. When the ratio drops below 0.3, the gauge turns orange — time to prune or fork. The crab suggests: "Prune weak stipes (chum@38fm, sockeye@25fm) to free nutrients."

### Technical Implementation

- **Multi-display layout** — Helm station, sounder, radar, chart table, comm panel
- **Overlay rendering** — Hermit annotations overlaid on real displays
- **Brass gauge visualization** — Conservation ratio as physical gauge
- **Crab animation** — Perched on chart table, taps when important
- **Fleet communication** — Real-time bottle flow, challenge loop
- **Audio feedback** — Subtle gong for VOCABULARY_MATCH, crackle for fleet messages

### Why This Works

- **Captain's perspective** — Everything visible, nothing waits
- **Ambient intelligence** — AI is everywhere, not in a chat window
- **Maritime authenticity** — Real wheelhouse layout, real displays, crab on chart
- **Decision support** — Captain decides, AI suggests
- **Fleet integration** — See all boats, all messages, all patterns

---

## Concept 10: The Glass Buoy — Transparent Cognitive Sphere

> *"The crab floats in a glass buoy. The ocean is memory. The crab sees through."*

### Mental Model
The workspace is a **glass navigation buoy** — a transparent sphere floating in the ocean, with a hermit crab inside. The crab sees through the glass in all directions — seeing the ocean (memory), other buoys (fleet boats), and bottles drifting by. The user can rotate the buoy, look in any direction, and see what the crab sees. The buoy itself is the interface — no windows, no panels, just transparency.

### UI Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│                      GLASS BUOY — Transparent Cognitive Sphere        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ═══════════════════════════════════════════════════════════════════        │
│  GLASS SPHERE — Rotate to look in any direction                          │
│  ═══════════════════════════════════════════════════════════════════        │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    VIEW THROUGH GLASS                        │   │
│  │  (ocean, fleet buoys, drifting bottles, memory layers)        │   │
│  │                                                                 │   │
│  │    ═══════════════════════════════════════════════════════        │   │
│  │    SURFACE — Tide Pool (ephemeral)                                 │   │
│  │    ═══════════════════════════════════════════════════════        │   │
│  │    🍾 bottle_001 ──────► (drifts right)                           │   │
│  │    🍾 bottle_047 ───────────►                                      │   │
│  │    🍾 challenge_12 ──────► (crab reaching for it)                  │   │
│  │                                                                 │   │
│  │    ═══════════════════════════════════════════════════════        │   │
│  │    MID-WATER — Stipes (growing knowledge)                          │   │
│  │    ═══════════════════════════════════════════════════════        │   │
│  │    🌿 stipe: chum@35fm ── strength: 0.78 (visible as glow)         │   │
│  │    🌿 stipe: thermocline correlation ── strength: 0.85             │   │
│  │    🌿 stipe: green flasher efficacy ── strength: 0.92              │   │
│  │                                                                 │   │
│  │    ═══════════════════════════════════════════════════════        │   │
│  │    BOTTOM — Holdsfast (permanent)                                  │   │
│  │    ═══════════════════════════════════════════════════════        │   │ │
│  │    🪸 holdsfast: species_db ── (glows faintly, permanent)          │   │
│  │    🪸 holdsfast: chart_plot ── (glows faintly, permanent)          │   │
│  │    🪸 holdsfast: 10yr_data ── (glows faintly, permanent)          │   │
│  │                                                                 │   │
│  │    ═══════════════════════════════════════════════════════        │   │
│  │    HORIZON — Fleet buoys (other boats)                              │   │
│  │    ═══════════════════════════════════════════════════════        │   │
│  │    🧊 GLASS BUOY: F/V KODIAK ──► 12 nm NW (visible as sphere)       │   │
│  │    🧊 GLASS BUOY: F/V OCEAN ──► 18 nm SE (visible as sphere)        │   │
│  │    🧊 GLASS BUOY: F/V WINDSOR ──► 24 nm SW (visible as sphere)      │   │
│  │    🧊 GLASS BUOY: F/V TIDERUNNER ──► 31 nm N (visible as sphere)     │   │
│  │    (bottle signals flow between buoys as glowing arcs)              │   │
│  │                                                                 │   │
│  │    ═══════════════════════════════════════════════════════        │   │
│  │    DEEP WATER — Chart Plot (knowledge graph)                       │   │
│  │    ═══════════════════════════════════════════════════════        │   │
│  │    🗺️ CHUM ──CAUGHT_WITH──► GREEN_FLASHER (0.92)                   │   │
│  │       │                                                           │   │
│  │       └─PREFERS_DEPTH──► [30-40 fm] (0.85)                       │   │
│  │                                                                 │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ═══════════════════════════════════════════════════════════════════        │
│  THE HERMIT CRAB — Inside the glass, seeing everything                    │
│  ═══════════════════════════════════════════════════════════════════        │
│                                                                     │
│  🦀 CRAB (inside sphere, reaching through glass for bottles)               │
│  🫧 GLASS (transparent, refractive, shows ocean in all directions)           │
│  🪝 HOOK (crab pulls bottles through glass, reads them, sends back)           │
│  💡 LIGHT (glows from within, illuminating memory layers)                   │
│                                                                     │
│  ROTATION: Click & drag to rotate sphere                                    │
│  ZOOM: Scroll to zoom in/out (see detail or see fleet)                     │
│  CLICK: Click bottle to read, click buoy to connect, click stipe to prune  │
│                                                                     │
│  WATER TEMP: 52°F │ CURRENT: 0.3 kts SE │ VISIBILITY: 20 nm                 │
│  BUOY POSITION: 55°47.2'N 131°14.5'W │ FLEET: 4/5 buoys visible               │
│  GLASS CLARITY: 92% (slight biofouling) │ LIGHT: 78% (bioluminescent crab)    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Interaction Patterns

**360° transparency:** Rotate the glass buoy to look in any direction. Look up to see the surface (bottles drifting). Look down to see the bottom (Holdsfast anchors). Look horizontally to see fleet buoys (other boats). The crab is inside, visible from any angle.

**Bottle retrieval:** Bottles drift past the glass. The crab reaches through the glass, hooks a bottle with its claw, pulls it inside, reads it, and sends a response bottle back out through the glass. The glass is permeable to bottles but not to water — a cognitive membrane.

**Buoy communication:** Other fleet boats appear as glass buoys on the horizon. Click any buoy to connect — the view zooms to that buoy, showing its internal state (its crab, its memory layers, its bottle queue). Bottle signals flow between buoys as glowing arcs.

**Memory layer visibility:** Look down to see the memory layers. Stipes (growing knowledge) glow at 20 fm depth. Holdsfast (permanent) anchors glow faintly at 30 fm. The Chart Plot (knowledge graph) glows at 40 fm. The crab's light illuminates these layers — making memory visible.

**Bioluminescence:** The crab glows from within — bioluminescent blue-green light. When the crab is thinking, the light pulses. When the crab is confident, the light is steady. When the crab is uncertain, the light dims. The crab's internal state is visible through the glass.

**Glass clarity:** The glass accumulates biofouling over time (metaphor for cognitive load). At 100% clarity, everything is visible. At 50% clarity, memory layers are murky. At 20% clarity, the crab is barely visible. The crab "cleans the glass" by pruning weak stipes — restoring clarity.

### Technical Implementation

- **Three.js glass sphere** — Transparent, refractive, realistic glass
- **360° view** — Rotate to look in any direction
- **Bioluminescent crab** — Glows from within, pulses with thinking
- **Fleet buoy rendering** — Other boats as glass buoys on horizon
- **Bottle animation** — Drifting, crab retrieval, glass permeation
- **Physics** — Water current, buoy bobbing, crab movement

### Why This Works

- **Radical transparency** — See everything, no hidden panels
- **Spatial clarity** — Up = surface, down = memory, horizon = fleet
- **Crab perspective** — See what the crab sees, inside the glass
- **Maritime metaphor** — Glass buoys are real navigation aids
- **Organic feel** — Biofouling, bioluminescence, glass permeability

---

## Synthesis: Design Principles Across All Concepts

### Common Themes

1. **Maritime Metaphor Consistency**
   - Every concept uses maritime language, aesthetics, and behavior
   - Crab, bottles, beachcomber, tide pool, chart room, wheelhouse
   - No Silicon Valley terminology — no "chats," "prompts," "AI assistants"

2. **Spatial Memory Organization**
   - All concepts organize knowledge by depth/location
   - Surface = ephemeral, mid-depth = growing, bottom = permanent
   - User remembers "where" knowledge lives (not just "what")

3. **Ambient Intelligence**
   - Information is visible, waiting to be seen — not pushed
   - No popups, no notifications (unless critical alerts)
   - Captain glances, absorbs, decides

4. **Physical Metaphors for Cognitive Processes**
   - Kelp growth = memory growth
   - Tide cycle = memory lifecycle
   - Glass clarity = cognitive load
   - Brass gauge = conservation ratio

5. **Collaborative Human-AI Model**
   - Crab suggests, Captain decides
   - Challenge loop for truth-seeking
   - Adversarial debate between agents
   - Institutional memory across captains

6. **Offline-First Design**
   - All concepts work without internet
   - File-based bottles (filesystem IS the API)
   - Local state, sync when connected
   - Boat laptop resilience

### Technical Requirements Shared

- **Web-based** — Browser, PWA, offline-first
- **Canvas/WebGL** — Smooth 60fps rendering
- **File System API** — Bottle directory watching
- **WebSockets** — Real-time fleet communication
- **Local storage** — Bottle persistence, memory layers
- **Audio** — Maritime sounds, ambient feedback

### Mental Models Supported

- **Temporal** — Ship's log (time-based narrative)
- **Spatial** — Chart room, tide pool, glass buoy (location-based memory)
- **Ecological** — Kelp forest (organic growth)
- **Social** — Wheelhouse, crow's nest (fleet communication)
- **Minimalist** — Bottle beach (fast interaction)

---

## Recommendation: Hybrid Approach

**Best of All Worlds — The Hermit Cognitive Workspace (Production)**

Combine elements from multiple concepts:

1. **Chart Room (Concept 1)** — Primary workspace layout
   - Wood paneling, brass accents, central chart table
   - Crab sits on chart table, bottles drift in from porthole
   - Holdsfast cabinet left, Tide Pool right, Conservation gauge bottom-right

2. **Sonar Workspace (Concept 2)** — Secondary view for captures
   - Click "SONAR VIEW" to see echogram-style thought display
   - Thoughts at different depths, scroll like TZ Pro
   - Familiar interface for Captain

3. **Ship's Log (Concept 8)** — Temporal navigation
   - Click "LOG VIEW" to see ship's log timeline
   - Every bottle is a log entry with marginalia
   - Search across entire season

4. **Crow's Nest (Concept 6)** — Fleet awareness
   - Click "FLEET VIEW" to see all boats
   - Signal flags, bottle traffic, anomalies
   - Zoom to boat for detail

5. **Bottle Beach (Concept 5)** — Mobile/minimalist mode
   - Switch to "MINIMAL MODE" for slow connections
   - Flat 2D, fast-loading, touch-friendly

6. **Wheelhouse Integration** — Real deployment
   - On the actual boat, integrate with TZ Pro sounder
   - Ambient overlays on helm displays
   - Crab on chart table, vocabulary panel on comm panel

**Final Architecture:**

```
┌─────────────────────────────────────────────────────────────────┐
│                    HERMIT COGNITIVE WORKSPACE                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  PRIMARY VIEW: Chart Room (Concept 1)                           │
│  - Wood paneling, brass accents, chart table                   │
│  - Crab sits on chart, bottles drift from porthole             │
│  - Holdsfast cabinet, Tide Pool, Conservation gauge            │
│                                                                 │
│  SECONDARY VIEWS:                                               │
│  - SONAR VIEW (Concept 2) — Capture-focused, echogram style    │
│  - LOG VIEW (Concept 8) — Temporal timeline, ship's log       │
│  - FLEET VIEW (Concept 6) — Crow's nest, all boats             │
│                                                                 │
│  MINIMAL MODE:                                                  │
│  - BOTTLE BEACH (Concept 5) — Flat 2D, mobile-friendly         │
│                                                                 │
│  BOAT INTEGRATION:                                             │
│  - WHEELHOUSE (Concept 9) — Real helm overlays, ambient AI    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Next Steps: From Concept to Implementation

### Phase 1: Prototype (Week 1-2)
- Build Chart Room UI (Concept 1) as web app
- Implement bottle drift animation, crab presence
- Create Holdsfast cabinet, Tide Pool, Conservation gauge
- Test offline-first PWA behavior

### Phase 2: Multi-View (Week 3-4)
- Add Sonar View (Concept 2) for capture-focused view
- Add Log View (Concept 8) for temporal navigation
- Add Fleet View (Concept 6) for crow's nest awareness
- Implement view switching, state sync

### Phase 3: Minimal Mode (Week 5)
- Build Bottle Beach (Concept 5) as minimalist mode
- Optimize for mobile, slow connections
- Test touch interactions, drag-and-drop

### Phase 4: Boat Integration (Week 6-8)
- Integrate with TZ Pro sounder (wheelhouse mode)
- Add ambient overlays on helm displays
- Test on boat laptop, offline scenarios
- Calibrate with Captain's workflow

### Phase 5: Fleet Deployment (Week 9-10)
- Deploy to multiple boats
- Test fleet bottle traffic, challenge loops
- Measure vocabulary growth, fleet intelligence
- Iterate based on real fishing season data

---

**Generated:** 2026-07-18 19:12 AKDT
**Sources:** hermit_vessel.py, _DEEP_IDEATION.md, ONBOARDING.md
**Concepts:** 10 distinct workspace designs, synthesized into hybrid recommendation
**Metaphor:** Hermit crab, bottles, beachcomber, tide pool, chart room, wheelhouse
**Philosophy:** Maritime, ambient, collaborative, offline-first, transparent cognition

> *"The crab doesn't live in the shell. The crab lives in the cognitive space between the shell and the sea. The Hermit workspace is that space — where human and AI think together about the ocean."*

---
