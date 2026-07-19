# _REPO_IDEAS — Repo Scan & Ship AI Memory System Synthesis

**Scanned:** 2026-07-18 16:14 AKDT  
**Agent:** DeepSeek V4 Pro (subagent)  
**Context:** TZ Pro echogram capture pipeline + creeping AI memory architecture

---

## 1. Directory Scan Results

| Concept | Directory Found? | Exists As |
|---------|-----------------|-----------|
| `endless-radio` | ❌ | Fleet philosophy: murmur extractor, tick/loop heartbeat, capture_v3 10-min pulse |
| `lucid-dreaming` | ❌ | Fleet philosophy: LucidDreamer cloud-to-edge compiler (η→γ conversion) |
| `murmur` | ❌ | Fleet philosophy: 5-strategy reasoning engine, emergent from 9-channel intent |
| `spreader-tool` | ❌ | Fleet philosophy: deadband detection, seed propagation, η-budget manager |
| `_radio` | ❌ | — |
| `dream` | ❌ | — |
| `spreader` | ❌ | — |

**None of the four concepts exist as standalone directories or codebases in the workspace.** They exist purely as architectural ideas — named agents/components in the SuperInstance fleet philosophy documented across AI-Writings, with their properties proven mathematically.

### What Does Exist (Adjacent)

| Directory/File | Relevance |
|----------------|-----------|
| `soundcrab/` | Multi-speaker audio router (WASAPI loopback → per-device EQ/compression) — analogous to multi-channel signal distribution |
| `agent-loop/` | Constantly-thinking agent with 14-model flock, tick heartbeat, goal queue, escalation protocol |
| `hermit-crab/` | Agent migration framework — knowledge survives, shell doesn't |
| `cold/buffer.jsonl` | Tiny — a single buffer file, possibly a signal ring buffer |
| `tzpro-agent/` | Full echogram capture pipeline: fleet monitor, conservation layer, vocabulary, alerts |
| `AI-Writings/` | 957 stories — 4 of them (SYNOPTIC-GLM, PHILOSOPHY-OF-FLUX, THE-COMPLETE-FLEET, SYNOPTIC-SEED) define the fleet concepts |

---

## 2. What Each Concept *Is* — From the Source Writings

### Endless Radio (murmur extractor)

From `THE-COMPLETE-FLEET.md`: `core/reasoning_tiler.py — step-tile cutter, murmur extractor`

Endless Radio is not a radio station. It's the continuously-running background reasoning system that never stops listening. In agent-loop, this is the iterator (qwen2.5:0.5b) that runs permanently — the heartbeat. In tzpro-agent, this is the capture_v3 daemon firing every 10 minutes on the :00/:10 boundary.

**Core properties:**
- **Continuous pulse** — never stops, never sleeps
- **Signal extraction from noise** — the "murmur" is the faint signal beneath the loudest channel
- **Step-tile cutting** — slicing continuous time-series into discrete reasoning tiles
- **Always-on, always-under** — runs below conscious attention, like background music

### Lucid Dreaming (LucidDreamer compiler)

From `SYNOPTIC-GLM.md`: *"LucidDreamer compiles from cloud to edge. This is a literal conservation operation: you are moving computation from a high-entropy environment (the cloud, where everything is possible) to a low-entropy environment (the edge, where constraints are tight). The compilation IS the act of converting η to γ."*

Lucid Dreaming is the **offline-to-online knowledge compression**. When the ship is docked and has internet, it absorbs raw cloud knowledge (high η). When it's at sea and disconnected, it dreams that knowledge into compact, deployable form (high γ).

**Core properties:**
- **Compilation, not deletion** — knowledge is restructured, not lost
- **η→γ conversion** — exploration entropy becomes structural entropy
- **Edge-deployable** — the dream output runs on ship hardware without cloud dependency
- **Conservation-preserving** — total C never changes, only the γ/η ratio

### Murmur

From `SYNOPTIC-GLM.md`: *"Murmur has five thinking strategies. Why five? Because we tried three (too rigid), seven (too diffuse), and five was where the strategies stopped stepping on each other."*

Murmur is the **multi-strategy reasoning core**. It listens to the continuous signal (from Endless Radio) and applies multiple independent reasoning strategies simultaneously. Five strategies emerged from the 9-channel intent model — they are the integer partitions that minimize mutual interference.

**Core properties:**
- **5 orthogonal strategies** — no two strategies step on each other
- **Pattern extraction** — hears the signal beneath the noise
- **Strategy accumulation** — learns new strategies over time (γ increases)
- **Deadband-aware** — respects the exploration budget η

### Spreader-tool (Spreader)

From `SYNOPTIC-GLM.md`: *"Spreader has a deadband. Between the lower threshold and the upper threshold, it does nothing. This is not a bug — it is the definition of η, the exploration budget."*

Spreader is the **deadband manager and seed propagator**. It defines where the system should be uncertain (the gap between lower and upper thresholds) and where it should act. It spreads seeds — knowledge fragments — across the fleet.

**Core properties:**
- **Deadband as feature, not bug** — uncertainty is allocated, not eliminated
- **Seed propagation** — distributes knowledge across agent topology
- **Threshold management** — lower bound = act, upper bound = suppress, between = explore
- **η-budget guardian** — the deadband IS the conservation slack

---

## 3. Synthesis: A Ship's AI Memory System

### The Problem

A fishing vessel at sea is a disconnected edge node. It has:
- **No internet** (Starlink might exist, but unreliable)
- **Finite compute** (one RTX 4050 laptop, 6GB VRAM)
- **Continuous sensory input** (sounder, GPS, radar, AIS, captain's notes)
- **Accumulating knowledge** (every ground, every catch, every tide observation)
- **Human in the loop** (the Captain, who must make decisions)

The memory problem: **How do you accumulate years of maritime knowledge on a laptop that might get salt-sprayed, power-cycled, or replaced — and have it get smarter, not dumber, over time?**

### The Four-Component Architecture

```
                    ┌──────────────────────────────┐
                    │      ENDLESS RADIO            │
                    │   (continuous ingest pulse)   │
                    │   NMEA → sounder → alerts     │
                    └──────────┬───────────────────┘
                               │ raw signal stream
                               ▼
                    ┌──────────────────────────────┐
                    │         MURMUR               │
                    │   (5-strategy reasoner)       │
                    │   pattern → strategy → tile   │
                    └──────────┬───────────────────┘
                               │ structured tiles
                               ▼
                    ┌──────────────────────────────┐
                    │       SPREADER               │
                    │   (deadband + seed prop)      │
                    │   threshold → explore → act   │
                    └──────────┬───────────────────┘
                               │ γ/η budget decisions
                               ▼
                    ┌──────────────────────────────┐
                    │     LUCID DREAMING           │
                    │   (edge compilation)          │
                    │   η→γ → deployable memory     │
                    └──────────────────────────────┘
```

### Endless Radio → The Memory Ingest Layer

The ship's AI memory needs a **continuous ingest pulse** that never stops:

- **What it listens to:** NMEA sentences, sounder captures, AIS contacts, engine telemetry, Captain's voice notes, catch reports, tide tables, weather observations
- **What it produces:** A raw event stream — unjudged, unfiltered, timestamped, geotagged
- **Inspiration from existing:** `capture_v3.py` (10-min screenshot pulse), `agent-loop` tick heartbeat, `nmea_bridge.py` (serial→TCP multiplexer)

For the ship's memory system, Endless Radio would be a **ring-buffer of experience**: the last N hours of raw sensor data, continuously overwritten unless something flags it for permanent storage. Like a voyage data recorder (VDR) — but one the AI can access.

### Murmur → The Reasoning Layer

The ship doesn't just record data. It needs to **extract patterns** from the stream:

- **5 strategies for maritime reasoning:**
  1. **Spatial** — where are we? what's the bottom like? (chart correlation)
  2. **Temporal** — what's changing? tide, season, migration patterns
  3. **Causal** — did that sounder mark produce a catch? (catch-link learning)
  4. **Social** — what are other boats doing? (AIS proximity, sounder interference)
  5. **Conservation** — is our γ/η budget healthy? should we forget something?

- **What it produces:** Structured reasoning "tiles" — small, composable insights like "chum at 35 fm on ebb tide over hard bottom at this GPS coordinate"

- **Inspiration from existing:** `vocabulary.py` (Bayesian species prediction), `analyzer.py` (signal detection), `conservation_layer.py` (budget management)

### Spreader → The Gatekeeping Layer

Not everything deserves permanent memory. Spreader defines the **deadband** — the zone of productive uncertainty:

- **Lower threshold:** "We've seen this pattern 3+ times at confidence ≥0.7" → promote to permanent memory
- **Upper threshold:** "This contradicts 5 prior observations" → suppress or flag for Captain review
- **Deadband (between):** "Maybe interesting, hold in buffer, wait for more evidence" → η budget

- **Seed propagation:** When a tile reaches the lower threshold, Spreader propagates it as a "seed" that can cross-pollinate with other tiles. "Chum at 35 fm at this coordinate" + "Chum at 35 fm at that coordinate" → "Chum at 35 fm along this contour line."

- **Inspiration from existing:** `alerts.py` deduplication, `conservation_layer.ActionBudget` (waste_ratio > 3.0 → deny)

### Lucid Dreaming → The Compression Layer

When the ship docks and has connectivity (or during idle periods at sea), the system enters a **dream state**:

- **Cloud → Edge compilation:** Raw observations (high η, high volume) are compiled into compact models (high γ, low volume). A year of chum trolling data becomes a "this is what chum look like on this sounder at these coordinates" compressed model.
- **Cross-voyage synthesis:** When the ship migrates from Ketchikan to Cordova, the Southern Southeast ground knowledge is compiled and frozen. Northern Gulf ground knowledge begins accumulating fresh.
- **Forgetting as feature:** The conservation law says γ + η = C. As memory grows, exploration budget shrinks. The dream state prunes low-confidence, stale, or contradicted memories to free η for new learning.

- **Inspiration from existing:** `conservation_layer.split()` (forget-or-spawn), `vocabulary.py` Laplace smoothing, `captures/v3/` daily folder structure

---

## 4. How This Fits the Existing Code

### What Already Exists (Ground Truth)

| Existing Component | Maps To | Status |
|-------------------|---------|--------|
| `capture_v3.py` (10-min pulse) | Endless Radio ingest | ✅ Running (PID 33360) |
| `analyzer.py` (signal detection) | Murmur strategy #1 (spatial) | ✅ Running |
| `vocabulary.py` (Bayesian prediction) | Murmur strategy #3 (causal) | ✅ Running |
| `alerts.py` (5 rules + dedup) | Spreader threshold management | ✅ Running |
| `conservation_layer.py` (γ+H=C) | Lucid Dreaming budget | ✅ Built, needs wiring |
| `catch_link.py` (human annotation) | Spreader lower-threshold trigger | ✅ Built |
| `fleet_monitor.py` (health check) | Infrastructure | ✅ Running |
| `_router.py` (agent task routing) | Murmur strategy dispatch | ✅ Built |
| `agent-loop/autonomous.py` | Endless Radio tick loop | ✅ Built (separate project) |
| `nmea-bridge/nmea_bridge.py` | Endless Radio data source | ✅ Running |

### What's Missing (The Gap)

The ship's AI memory system is **not yet integrated across the four components**:

1. **No memory persistence layer.** SQLite captures come and go. There's no long-term "here's what we learned this season" store.
2. **No Lucid Dreaming compile step.** Knowledge accumulates but never compresses. Vocabulary entries only grow.
3. **No cross-voyage transfer.** Start a new trip and the system forgets last week's grounds.
4. **No Spreader deadband wired to real decisions.** The conservation layer calculates budgets but nothing reads them.
5. **Murmur strategies are implicit.** The 5 reasoning modes exist in the fleet philosophy but aren't coded as explicit strategy objects.

### The Integration Path

```
Phase A: Wire Endless Radio → Murmur
  - Add raw event buffer (ring buffer of last 24h NMEA + captures)
  - Wire 5 strategy objects that consume the buffer
  - Each strategy produces reasoning tiles with confidence scores

Phase B: Wire Murmur → Spreader
  - Tiles enter Spreader's deadband manager
  - Below threshold → discard after buffer window
  - Above threshold → promote to persistent memory
  - In deadband → hold, accumulate evidence

Phase C: Wire Spreader → Lucid Dreaming
  - On dock/connectivity: compile persistent memory into compressed models
  - Prune low-confidence entries to free η budget
  - Package per-ground, per-species, per-season

Phase D: Cross-Voyage Transfer
  - Freeze old ground knowledge on migration
  - Load new ground knowledge on arrival
  - Fleet-level sharing between cooperating vessels (CoCapn)
```

---

## 5. Creative Extensions

### The Radio as Metaphor

The ship's sounder is literally a radio — it transmits acoustic pulses and listens for echoes. Endless Radio is the same principle at the cognitive level: the AI transmits queries into the data stream and listens for the "echo" — the pattern that returns. The "murmur" in the fleet writings is the faint signal between the loud returns — the thing you only hear when you're listening continuously, patiently, forever.

### Dreams at Anchor

A real-world Lucid Dreaming cycle: when the engine stops and the anchor sets, the GPU is idle. The system enters dream mode. It replays the day's captures, cross-references them with catch reports, compresses the vocabulary, prunes stale observations. By morning, it's smarter than it was at sunset — not because it received new data, but because it reorganized what it already had. γ increased while the ship slept.

### The Spreader as Social Memory

In the CoCapn ecosystem (multiple cooperating fishing vessels), Spreader becomes a social protocol. When vessel A's Spreader promotes a tile above threshold, it propagates a seed to vessels B and C. But the deadband prevents echo chambers — each vessel must independently verify before promoting the seed. The fleet learns collectively without herding.

### Murmur as the Captain's Second Mind

The 5 Murmur strategies should never replace the Captain's intuition — they should amplify it. Strategy #5 (conservation) is the meta-strategy that asks "are we reasoning about the right things?" When the Captain is focused on chum at 35 fm, Murmur-5 notices that the tide is about to turn and the bottom is shoaling — things the Captain knows but might not be attending to. It murmurs, doesn't shout.

---

## 6. Relevant Source Files (for reference)

| File | Key Concept |
|------|------------|
| `AI-Writings/SYNOPTIC-GLM.md` | Full fleet architecture description (Spreader, Murmur, LucidDreamer, AIR) |
| `AI-Writings/PHILOSOPHY-OF-FLUX.md` | FLUX as conserved relation between γ and η |
| `AI-Writings/agents-and-ai/THE-COMPLETE-FLEET.md` | Fleet roster, tools, router, murmur extractor |
| `AI-Writings/SYNOPTIC-SEED.md` | Polyformalism, 11-language implementations, fleet integration |
| `tzpro-agent/_ARCH_AGENCY.md` | Agent delegation architecture (specialist/generalist/clone/baton) |
| `tzpro-agent/_ARCH_CONSERVATION.md` | 3 conservation laws + 6 code implementations |
| `tzpro-agent/_ARCH_SCALING.md` | Kelp forest, membrane law, phase transition at scale 200 |
| `tzpro-agent/_AGENTS_GUIDE.md` | Complete system reference (signals, schema, alerts, commands) |
| `tzpro-agent/README.md` | Project overview, founding story, hierarchy |
| `agent-loop/README.md` | Tick heartbeat, model flock, goal queue |
| `agent-loop/WHITEPAPER.md` | "Emergence by Arrangement" theory |
| `soundcrab/README.md` | Multi-speaker audio router (WASAPI loopback) |
| `_creative_source.md` | Master index: FLUX VM, PLATO, conservation thesis, Hermit Crab |

---

*This document synthesizes the fleet philosophy from AI-Writings with the running code in tzpro-agent to propose a ship's AI memory architecture built on four proven concepts — none of which exist as separate repos, all of which are waiting to be wired together.*
