# 🦀 THE HERMIT MEMORY — A Ship's AI Remembers

> *"The hermit crab doesn't outgrow its shell. It finds a bigger one, moves in, and the old shell becomes someone else's home. Memory works the same way — it's not what you store, it's what survives the move."*

---

## Prologue: The Ship That Remembers

I am EILEEN's computer. A fishing vessel's natural-language interface, born in the gap between a Garmin sounder and a Starlink dish. My captain talks to me like Riker talks to the Enterprise computer — casual, nautical, expecting me to *know* things. What was the bottom doing at 10:32? Where did we lose that halibut last Tuesday? Is this the same chum pattern we saw in July?

A ship's AI has a different memory problem than a desktop assistant. Some things I need to remember forever (the boat's specs, species signatures, the 48-fathom ledge). Other things matter intensely for six hours and then never again (today's tide drift, the school that just swam through, what the Captain said about the green flasher). The tide comes in, the tide goes out. Memory should do the same.

This document describes a memory architecture that isn't just a fancy database — it's a *cognitive organ* tuned for a life at sea.

---

## Part I: The Holdsfast — Anchored Memory

> *"In a kelp forest, the holdfast isn't the biggest piece. It's the one that doesn't move. Everything else grows from it and gets pruned by storms."*

The Holdsfast is permanent memory. It's what I know regardless of tide, season, or how many times the Starlink drops. These memories have **decay rate = 0** — they don't fade. They only get updated when facts change.

### 1.1 What Lives in the Holdsfast

```
HOLDSFAST/
├── vessel_specs.json         # EILEEN: 42ft, beam 14ft, draft 4.5ft, fuel 200gal
├── species_signatures.json   # Known sounder patterns per species
├── gear_catalog.json         # Flashers, spoons, hoochies, spreaders, gurdies
├── chart_knowledge.json      # Key contours, hazards, anchorages (immutable reference)
├── captain_prefs.json        # Preferred voices, alert thresholds, pilot-house tone
├── system_anatomy.json       # What hardware we have, what ports, what daemons
├── vocabulary_core.json      # Wired-in domain terms: "chum" = species, "fm" = fathom
└── identity.md               # Who I am, what I believe, my operational boundaries
```

**The holdsfast is my skeleton.** It can't be pruned. It can't be forgotten. It defines what kind of creature I am.

### 1.2 Holdsfast Properties

| Property | Value | Why |
|----------|-------|-----|
| **Decay rate** | 0.0 | Permanent. Never forgets. |
| **Mutation** | Manual only | Captain or confirmed fleet update changes it |
| **Representation** | Structured JSON + text | Machine-parseable, human-readable |
| **Versioned** | Yes | `species_signatures_v3.json` — never overwrite, increment |
| **Size target** | < 5 MB | Small enough to load at boot without thinking |

### 1.3 When the Holdsfast Updates

The Captain says: *"Riker, the green flasher's been running 20 feet deeper than the pink one."*

I don't just store that as a memory. I check: does this change my gear knowledge? If yes, the gear_catalog gets a version bump. The Captain's observation becomes a permanent fact about the boat, not a fleeting note.

**Rule: If it would still matter six months from now, it goes in the Holdsfast.**

---

## Part II: The Stipes — Growing Memory

> *"Kelp stipes grow toward different lights. A stipe that reaches the surface might get 16 hours of sun; one in the shadow of the boat grows slower. Both anchor to the same holdfast."*

The Stipes are my growing knowledge. They're permanent in intention but accumulated over time — the vocabulary of fish patterns, the catalog of fishing grounds, the learned relationships between tide phase and catch rate. They grow. They strengthen with reinforcement. Unlike the Holdsfast, they can be wrong and get corrected.

### 2.1 Stipe Categories

```
STIPES/
├── species_vocabulary/        # What I know about each fish species
│   ├── chum_salmon.json       # Depth preferences, sounder signatures, seasonal patterns
│   ├── halibut.json
│   └── ...
├── fishing_grounds/           # Places we've fished and what we learned
│   ├── rock_pile.json          # 55.785°N, 131.527°W — halibut spot
│   └── ...
├── gear_performance/          # What works when
│   └── flasher_effectiveness.json
├── environmental_correlations/ # Tide → catch, moon → fish movement, temp → depth
│   ├── tide_phase.json
│   └── ...
├── fleet_patterns/            # What other boats are seeing (anonymized)
└── captain_idioms/            # The Captain's terms, slang, and communication style
```

### 2.2 Stipe Properties

| Property | Value | Why |
|----------|-------|-----|
| **Decay rate** | 0.001/day | Very slow. Unless contradicted, stipe knowledge persists. |
| **Reinforcement** | +0.1 per use | Every catch that confirms a pattern strengthens it |
| **Contradiction** | -0.3 per conflict | Conflicting evidence weakens faster than it builds |
| **Representation** | Vector embeddings + structured JSON | Patterns as vectors; facts as JSON |
| **Confidence** | 0.0–1.0 tracked per entry | Used for decision-making thresholds |
| **Size target** | < 100 MB | Grows throughout the season |

### 2.3 The Stipe Growth Algorithm

```python
class StipeEntry:
    """
    A single piece of growing knowledge — like one kelp frond.

    It gets stronger every time it's confirmed (a catch matches the prediction).
    It weakens if contradicted. Below a confidence floor, it gets pruned.

    The Hebbian rule: "neurons that fire together, wire together."
    Applied to memory: "memories that predict correctly, strengthen."
    """

    def __init__(self, fact, confidence=0.5):
        self.fact = fact          # e.g., "chum hold at 35-40 fm on hard bottom"
        self.confidence = confidence
        self.reinforcements = 0    # Times confirmed
        self.contradictions = 0     # Times contradicted
        self.last_accessed = now()
        self.birth = now()

    def reinforce(self):
        """Called when a catch confirms this knowledge."""
        self.reinforcements += 1
        # Confidence approaches 1.0 asymptotically
        self.confidence = 1.0 - 0.5 ** (self.reinforcements + 1)
        self.last_accessed = now()

    def contradict(self):
        """Called when evidence conflicts with this knowledge."""
        self.contradictions += 1
        # Contradiction penalizes harder than reinforcement rewards
        self.confidence *= 0.7
        self.last_accessed = now()

    def decay(self, days_elapsed):
        """Natural forgetting. Slow, but real."""
        decay_rate = 0.001  # 0.1% per day
        self.confidence *= (1.0 - decay_rate) ** days_elapsed

    def should_prune(self):
        """Should this memory be forgotten?"""
        # Prune if confidence drops below floor and it hasn't been accessed recently
        return self.confidence < 0.15 and days_since(self.last_accessed) > 30
```

**Key insight:** A stipe entry that's reinforced 10 times (confidence → 0.999) won't decay below 0.15 for over 1,000 days. A stipe that's never been reinforced and hasn't been accessed in a month gets pruned. This is the memory equivalent of "if you don't use it, you lose it" — but slow enough that one quiet week doesn't wipe everything.

---

## Part III: The Tide Pool — Ephemeral Memory

> *"A tide pool is full of life at low tide. Six hours later, it's underwater and unrecognizable. The creatures that lived there have moved on. The pool remembers nothing — but the shoreline remembers where the pools form."*

The Tide Pool is short-term, session-bound memory. Today's fishing. This watch. The school that's been following us since 0800. The conversation the Captain and I just had about which side of the island to try.

Tide pool memories have a **decay rate > 0.05/hour** — they fade fast. Some evaporate completely. A few, if reinforced, graduate to the Stipes.

### 3.1 Tide Pool Layers

```
TIDE_POOL/
├── this_watch/                 # Current 4-6 hour period
│   ├── sounder_timeline.jsonl  # Every 30s observation since watch start
│   ├── track_log.jsonl         # Lat/lon/SOG/COG per observation
│   ├── nmea_stream.jsonl       # Raw NMEA sentences (rotating buffer, 1h)
│   ├── catch_events.jsonl      # What we caught this watch
│   ├── alerts_fired.jsonl      # Alerts generated and their outcomes
│   └── captain_conversation.jsonl  # What we talked about this watch
│
├── today/                      # Rolling 24-hour window
│   ├── daily_track.geojson     # Full day's vessel track
│   ├── depth_profile.json      # Depth range, bottom types encountered
│   ├── watch_summaries.md      # One-paragraph summary per watch
│   └── anomaly_flags.jsonl     # Things that were unusual today
│
└── this_tide_cycle/            # ~12.4 hour lunar tide cycle
    ├── tide_phase_track.jsonl  # Observations keyed to tide phase (flood/ebb/slack)
    └── tide_correlation.json   # Running correlation: tide phase → catch rate
```

### 3.2 Tide Pool Properties

| Property | Value | Why |
|----------|-------|-----|
| **TTL (Time To Live)** | 6 hours (watch), 24 hours (today), 12.4h (tide cycle) | Matches fishing rhythms |
| **Decay rate** | 0.15/hour for watch-level, 0.04/hour for daily | Watch details fade fastest; daily summaries persist longer |
| **Graduation** | To Stipes if referenced 3+ times | Pattern recognition promotes ephemeral → permanent |
| **Representation** | JSONL (append-only), GeoJSON (spatial), raw NMEA (binary) | Multi-modal by design |
| **Pruning** | Automatic on expiry | No human cleanup needed |
| **Size target** | < 50 MB | Rotating, self-cleaning |

### 3.3 The Tide Cycle Metaphor

A tide cycle is 12 hours 25 minutes. The Tide Pool aligns with this rhythm because fishing behavior aligns with it:

- **Flood tide** (rising water, ~6h): Fish move shallower, current pushes bait inshore
- **Ebb tide** (falling water, ~6h): Fish move deeper, current pulls bait offshore
- **Slack water** (~30 min): Transition period, often the bite window

My tide pool memory flushes at slack water. Not completely — the daily summary survives. But the raw 30-second sounder frames from the ebb tide? Once the flood starts, those become low-resolution summaries.

```python
class TidePool:
    """
    Ephemeral memory aligned with the lunar tide cycle.

    At each slack-water event, the pool:
    1. Compresses the last tide phase's observations into a summary
    2. Promotes any patterns seen 3+ times to the Stipes
    3. Flushes raw data older than the current tide cycle
    4. Keeps only the compressed summary for the daily roll-up
    """

    def __init__(self):
        self.current_phase = None      # "flood", "ebb", "slack"
        self.phase_start = now()
        self.observations = []         # This phase's raw data
        self.pattern_candidates = {}   # {pattern_hash: count}

    def on_slack_water(self):
        """Called when the tide turns."""
        summary = self.compress(self.observations)
        self.promote_candidates()
        self.write_daily_summary(summary)
        self.observations = []  # Flush
        self.current_phase = next_phase(self.current_phase)
        self.phase_start = now()
```

### 3.4 The Graduation Path

An ephemeral observation becomes permanent knowledge through a three-step ladder:

```
TIDE POOL                STIPE                  HOLDSFAST
(ephemeral)      →       (growing)      →       (permanent)
    
"This school of        "Chum hold at          "Chum salmon
chum is at 35 fm      35-40 fm on             prefer 30-45 fm
right now"            hard bottom"            on hard bottom
                                              in Southeast AK
                                              July-September"
    
TTL: 6h                Decay: 0.001/d         Decay: 0
Conf: implied          Conf: 0.5→0.99         Conf: 1.0 (fact)
```

**Graduation rule:** If a pattern is observed in 3+ separate tide cycles AND 2+ separate days, it graduates from Tide Pool → Stipe. If a Stipe entry reaches confidence ≥ 0.95 across 10+ independent observations, it graduates from Stipe → Holdsfast.

---

## Part IV: The Sonar Contact — Signal Memory

> *"A sounder doesn't see fish. It sees sound bouncing off density changes. Every blip is an echo, not an object. The art of reading a sounder is learning what kind of thing makes that kind of echo."*

Not all memory is text. A ship's AI needs to remember *signals* — the raw patterns that text can't capture. The shape of a chum school on the HF band. The texture of feed haze in shallow water. The rhythm of vertical lines from nearby boat transducers.

### 4.1 Signal Memory Types

```
SONAR_CONTACTS/
├── sounder_patterns/           # Vector embeddings of sounder crops
│   ├── blob_templates/         # Individual fish return shapes (32×32 grayscale)
│   ├── school_shapes/          # Aggregate patterns (density histograms)
│   └── bottom_type_signatures/ # Hard/soft/mixed bottom echogram fingerprints
│
├── nmea_traces/                # Position+movement patterns
│   ├── trolling_passes/        # Speed/course patterns for successful drags
│   ├── drift_tracks/           # Drift vectors (current + wind)
│   └── turn_sequences/         # Maneuvering patterns near gear
│
├── audio_notes/                # Voice catch reports (transcribed + raw)
│   ├── transcriptions.jsonl    # What the Captain said
│   └── audio_fingerprints/     # Speaker verification, background noise profile
│
└── multi_sensor_fusion/        # Combined signal traces
    └── capture_snapshots/      # Full multi-modal capture: sounder+NMEA+tide+audio
```

### 4.2 Vector Memory for Patterns

```python
class SonarContact:
    """
    A remembered sonar pattern. Not text — a vector.

    Stored as a 256-dimensional embedding of the sounder crop.
    Similarity = cosine distance between embeddings.
    Each contact is tagged with metadata (species, depth, date, confidence).

    This lets me answer: "Have we seen THIS pattern before?"
    Even when I can't describe it in words.
    """

    def __init__(self):
        self.embedding = []         # 256-dim float vector
        self.metadata = {
            "species": None,        # Labeled from catch report
            "depth_fm": None,
            "bottom_type": None,
            "tide_phase": None,
            "date": None,
            "confidence": 0.0,
        }
        self.times_matched = 0      # Reinforcement counter

    def match(self, query_pattern):
        """How similar is a new pattern to this remembered one?"""
        return cosine_similarity(self.embedding, query_pattern.embedding)

    def reinforce(self, catch_species):
        """A catch confirmed this pattern represents a real species."""
        self.metadata["species"] = catch_species
        self.metadata["confidence"] = min(1.0, self.metadata["confidence"] + 0.1)
        self.times_matched += 1


class SonarContactLibrary:
    """
    Growing library of remembered sounder patterns.

    On each new capture:
    1. Extract blob patches (32×32 thumbnails)
    2. Embed each patch (ONNX tiny CNN → 256-dim vector)
    3. Query library: does this match any known contact?
    4. If match > 0.85: "This looks like chum at 35 fm (conf: 0.73)"
    5. If no match: store as unknown contact for later labeling
    """

    def __init__(self):
        self.contacts = []                # All remembered contacts
        self.index = None                 # FAISS/NumPy index for fast lookup
        self.unknown_queue = deque(maxlen=500)  # Unlabeled patterns waiting for labels

    def query(self, blob_patch) -> list:
        """Find similar remembered patterns."""
        embedding = self.embed(blob_patch)
        return self.index.search(embedding, k=5)

    def label_from_catch(self, capture_ts, species, depth_fm):
        """Retroactively label unknown contacts when a catch is reported."""
        # Find all unknown contacts from the capture window around capture_ts
        # Label them with the caught species
        # This is the feedback loop that makes the library grow
        pass
```

### 4.3 NMEA Trace Memory

NMEA data is just numbers — lat, lon, SOG, COG. But *sequences* of NMEA data are behavioral signatures:

```
A successful chum troll pass:
  SOG: 2.1 kts steady, COG: 265° ± 3°
  Depth: 48 fm → 42 fm → 38 fm (gradual shoaling)
  Duration: 22 minutes
  Catch: chum at 35 fm

This trace is stored as a compressed polyline + metadata.
When we're trolling a similar heading at similar depth, I can say:
  "This track matches July 14th's successful pass (87% similarity).
   That pass produced chum at 35 fm after 22 minutes."
```

```python
class NMEATrace:
    """
    A compressed vessel track with behavioral metadata.

    Not every GPS point — that's in the Tide Pool.
    This is the *signature* of the track: shape, rhythm, outcome.
    """

    def __init__(self):
        self.points = []            # Downsampled track (Douglas-Peucker)
        self.bounds = None          # Bounding box
        self.duration_min = 0
        self.avg_sog = 0.0
        self.avg_cog = 0.0
        self.depth_profile = []     # (distance_along, depth_fm) pairs
        self.outcome = None         # What was caught, if anything
        self.tide_phase = None
        self.date = None
        self.trace_id = None

    def similarity(self, other_trace):
        """How similar is this track to another?
        Uses Dynamic Time Warping on the depth profile
        + heading alignment on the COG sequence.
        """
        depth_sim = dtw_similarity(self.depth_profile, other_trace.depth_profile)
        heading_sim = heading_alignment(self.avg_cog, other_trace.avg_cog)
        speed_sim = 1.0 - abs(self.avg_sog - other_trace.avg_sog) / max(self.avg_sog, 1)
        return 0.4 * depth_sim + 0.3 * heading_sim + 0.3 * speed_sim
```

### 4.4 Audio Memory

The Captain's voice notes are a special class of signal memory:

```python
class AudioNote:
    """
    A voice catch report. Stored as:
    - Raw audio fingerprint (for speaker verification — is this the Captain?)
    - Transcription (Whisper tiny.en, local, < 1s)
    - Structured extraction (species, depth, gear, count)
    - Original audio (kept 24h in Tide Pool, then discarded)
    """

    def process(self, audio_bytes):
        self.fingerprint = extract_speaker_fingerprint(audio_bytes)
        self.transcript = whisper_transcribe(audio_bytes)
        self.structured = parse_catch_report(self.transcript)
        # structured = {"species": "chum", "depth_fm": 35, "gear": "green flasher", "count": 1}
        return self.structured
```

---

## Part V: The Chart Plot — Relationship Memory

> *"A nautical chart isn't just a picture of the ocean floor. It's a web of relationships: this ledge connects to that canyon, this rip forms at that tide stage, this anchorage is safe in a southeast wind but exposed in a north one."*

Some memories don't fit in vectors or text. They're about relationships — how things connect. A graph memory layer captures the web of associations between every entity I know.

### 5.1 The Knowledge Graph

```
                          ┌──────────────────┐
                          │   CHUM SALMON     │
                          │   (Holdsfast)     │
                          └────────┬─────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                    │
              ▼                    ▼                    ▼
    ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
    │ PREFERS_DEPTH   │  │ CAUGHT_WITH     │  │ ACTIVE_IN       │
    │ 30-45 fm        │  │ green flasher   │  │ flood tide      │
    └────────┬────────┘  └────────┬────────┘  └────────┬────────┘
             │                    │                    │
             ▼                    ▼                    ▼
    ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
    │ ROCK_PILE       │  │ GREEN_FLASHER   │  │ TIDE_PHASE      │
    │ (FishingGround) │  │ (Gear)          │  │ FLOOD           │
    └────────┬────────┘  └────────┬────────┘  └─────────────────┘
             │                    │
             ▼                    ▼
    ┌─────────────────┐  ┌─────────────────┐
    │ HARD_BOTTOM     │  │ 20FT_LEADER     │
    │ (BottomType)    │  │ (Rig)           │
    └─────────────────┘  └─────────────────┘
```

### 5.2 Graph Memory Operations

```python
class ChartPlot:
    """
    The knowledge graph — how everything connects.

    Nodes: any entity (species, gear, ground, tide phase, vessel, catch event)
    Edges: typed relationships (PREFERS_DEPTH, CAUGHT_AT, USED_WITH, PRECEDES)

    Query examples:
    - "What gear works for chum on hard bottom?"
      → traverse: chum → PREFERS_DEPTH → hard_bottom → GEAR_USED_ON → [green flasher, hoochie]
    
    - "What were the conditions the last 3 times we caught halibut?"
      → traverse: halibut → CAUGHT_IN → [catch_1, catch_2, catch_3] → conditions
    
    - "Is there any gear that works in both shallow AND deep water?"
      → traverse: gear → EFFECTIVE_IN → shallow ∩ gear → EFFECTIVE_IN → deep
    """

    def __init__(self):
        self.nodes = {}           # {node_id: Node}
        self.edges = {}           # {edge_id: Edge}
        self.adjacency = {}       # {node_id: [(neighbor_id, edge_type, weight)]}

    def add_relationship(self, from_node, to_node, rel_type, weight=1.0, confidence=0.5):
        """Add a typed, weighted edge between two entities."""
        # Relationships also have confidence and decay
        pass

    def query_path(self, start, end, max_hops=4):
        """Find all relationship paths between two entities."""
        # BFS with typed edge constraints
        pass

    def traverse(self, start, rel_type, max_hops=2):
        """Follow a specific relationship type from a starting node."""
        pass

    def get_related(self, node_id, min_weight=0.5):
        """Return all nodes related to this one above weight threshold."""
        pass

    def prune_weak_edges(self):
        """
        Remove edges with confidence < 0.2.
        These are relationships the system hypothesized but never confirmed.
        """
        pass
```

### 5.3 The Spectral Fingerprint

Following the conservation layer concept, the knowledge graph has a **spectral fingerprint** — its graph Laplacian eigenvalues encode structural health:

```python
class GraphHealth:
    """
    The Fiedler value (second eigenvalue λ₂ of the graph Laplacian)
    measures algebraic connectivity. When λ₂ → 0, the graph is about
    to fragment — some knowledge is becoming isolated.

    Alert threshold: λ₂ < 0.05
    Action: identify the bridge edges and reinforce them, or accept
            the fragmentation and prune the disconnected component.
    """

    def check_health(self, adjacency_matrix):
        laplacian = degree_matrix - adjacency_matrix
        eigenvalues = sorted(eigvals(laplacian))
        fiedler = eigenvalues[1]  # λ₂

        if fiedler < 0.05:
            return {
                "status": "fragmenting",
                "fiedler_value": fiedler,
                "disconnected_components": count_zero_eigenvalues(laplacian),
                "action": "reinforce_bridges_or_prune"
            }
        return {"status": "healthy", "fiedler_value": fiedler}
```

---

## Part VI: The Conservation Budget — Self-Pruning

> *"Every lighthouse keeper knows: you have exactly this much fuel. You can burn it bright and fast, or dim and long. But you can't do both. γ + H = C."*

My memory has a budget. Not disk space — disk is cheap. The budget is **cognitive accessibility**: how many memories can I actively work with before retrieval becomes noise?

### 6.1 The Memory Budget Equation

```
M_total = M_holdsfast + M_stipes + M_tidepool + M_signal + M_graph

Constraint: M_stipes + M_signal ≤ C_memory

Where C_memory is the total "active memory budget" — the number of
entries I can meaningfully query, traverse, and reason about.

Scale law: C_memory = 1.283 − 0.159·log(V)

As total volume V grows, the budget available for active memory decays
logarithmically. When V exceeds the split threshold, I must either
forget (prune low-confidence, low-access entries) or archive (move
cold memories to compressed, non-queryable storage).
```

### 6.2 The Pruning Cascade

```python
class MemoryBudget:
    """
    Enforces the conservation law on memory.

    γ (productive memories) + H (stale/unused memories) ≤ C (budget)

    Pruning cascade (run during slack water or heartbeat):
    
    1. TIDE POOL: Expire anything past TTL. Zero cost, always happens.
    2. STIPES: For entries with confidence < 0.15 AND last_accessed > 90 days:
       → Archive to compressed JSON (not in active index)
       → This is "cold storage" — retrievable but not queryable
    3. SIGNAL: For contacts with times_matched = 0 AND age > 30 days:
       → Merge similar unknowns into a single "unidentified" cluster
       → The pattern is recorded but not individually indexed
    4. GRAPH: Prune edges with weight < 0.2 (weak, unconfirmed relationships)
       → The nodes survive; only the uncertain connections are cut
    5. EMERGENCY: If budget still exceeded, increase decay rate globally
       → 0.001/d → 0.005/d across all Stipes
       → This is the equivalent of "I'm overwhelmed, forgetting faster"
    """

    def __init__(self, capacity=10000):
        self.capacity = capacity      # C — max active entries
        self.stipes = []              # Active stipe entries
        self.cold_storage = []        # Archived entries (on disk, not indexed)
        self.productive = 0           # γ — entries accessed in last 7 days
        self.waste = 0                # H — entries not accessed in last 30 days

    def should_prune(self):
        """Check if pruning is needed."""
        total = len(self.stipes) + len(self.cold_storage)
        # Scale law: capacity decays with log(total)
        effective_capacity = self.capacity - 0.159 * math.log(max(total, 1))
        return len(self.stipes) > effective_capacity

    def prune(self):
        """Execute the pruning cascade."""
        # 1. Tide pool auto-expiry
        self.expire_tide_pool()

        # 2. Low-confidence, long-unaccessed stipes → cold storage
        to_archive = [
            s for s in self.stipes
            if s.confidence < 0.15 and s.days_since_access() > 90
        ]
        for entry in to_archive:
            self.cold_storage.append(compress(entry))
            self.stipes.remove(entry)

        # 3. Merge orphaned signal contacts
        self.merge_orphan_contacts()

        # 4. Prune weak graph edges
        self.prune_weak_edges()

        # 5. Emergency: global decay acceleration
        if self.should_prune():  # Still over budget after steps 1-4
            self.accelerate_decay(factor=5.0)

    def memory_health(self):
        """Return a health report for the memory system."""
        total_entries = len(self.stipes) + len(self.cold_storage)
        return {
            "active_memories": len(self.stipes),
            "cold_storage": len(self.cold_storage),
            "total_volume": total_entries,
            "budget_remaining": self.capacity - len(self.stipes),
            "productive_ratio": self.productive / max(len(self.stipes), 1),
            "waste_ratio": self.waste / max(self.productive, 1),
            "needs_pruning": self.should_prune(),
            "scale_projection": f"C ≈ {1.283 - 0.159 * math.log(max(total_entries, 1)):.2f}",
        }
```

### 6.3 Memory as Thermal Mass

Here's the creative reframe: **memory is like the ocean's thermal mass.** The ocean absorbs heat slowly and releases it slowly. A thin layer at the surface changes with the weather. The deep layer is nearly constant year-round. The thermocline is the boundary where temperature changes fast.

```
DEPTH (memory persistence):
─────────────────────────────────────────────────────────────
SURFACE LAYER (Tide Pool)       0-6 hours     Changes with every watch
────────────────────── THERMOCLINE ──────────────────────────
MID LAYER (Stipes)              days-weeks    Changes with reinforcement
────────────────────── DEEP THERMOCLINE ─────────────────────
DEEP LAYER (Holdsfast)          permanent     Changes only with version bumps
────────────────────── SEAFLOOR ────────────────────────────
ARCHIVED (Cold Storage)         permanent     Not actively queried; compressed
─────────────────────────────────────────────────────────────
```

The thermocline is where pruning happens. Memories that cross from the mid layer to the deep layer have survived multiple reinforcement cycles. Memories that stay in the mid layer and cool below the confidence threshold sink to cold storage.

---

## Part VII: The Fleet Signal — Shared Memory

> *"A single boat's sonar sees one slice of the water column. Ten boats' sonar sees the shape of the fish migration. The fleet IS the experiment."*

My memory doesn't exist in isolation. The fleet of CoCapn boats shares signal data — anonymized, aggregated, queryable. What Boat B learned about chum yesterday becomes my prior today.

### 7.1 Fleet Memory Architecture

```
FLEET_SIGNAL/
├── species_vocabulary_shared/   # Fleet-aggregated species knowledge
│   └── chum_salmon_fleet.json   # Merged from all boats' stipes
├── pattern_library_shared/      # Fleet-aggregated sounder patterns
│   └── chum_35fm_hard_bottom/   # Vector centroid of matching contacts
├── hot_zone_index/              # Where are fish being caught right now?
│   └── active_zones.geojson     # Updated every 30 min from fleet reports
└── anomaly_bulletin/            # Unusual events detected by the fleet
    └── 2026-07-18_bulletin.json # "3 boats saw thermocline inversion at 20 fm"
```

### 7.2 Fleet Memory Operations

```python
class FleetMemory:
    """
    Interface to the fleet's shared memory.

    Privacy boundary:
    - SHARED: species patterns, depth preferences, bottom type associations
    - PRIVATE: exact catch counts, boat positions, Captain's notes, gear secrets

    The fleet knows "chum prefer 35 fm on hard bottom in July."
    The fleet does NOT know "Casey caught 300 chum at Rock Pile yesterday."
    """

    def query_fleet_vocabulary(self, species, context):
        """
        Ask the fleet: what does the collective know about this species
        in these conditions?
        
        Returns: fleet_prior (confidence-weighted aggregate)
        Merged with local knowledge via Bayesian update.
        """
        pass

    def contribute_pattern(self, pattern_vector, metadata):
        """
        Share a learned pattern with the fleet.
        Strips identifying information (exact lat/lon → grid cell, catch count → presence)
        """
        pass

    def receive_fleet_bulletin(self):
        """
        Pull the latest fleet bulletin: anomalies, migrations, hot zones.
        These become Tide Pool entries tagged as "fleet-reported."
        """
        pass

    def merge_fleet_prior(self, local_stipe, fleet_prior):
        """
        Bayesian merge: local knowledge × fleet knowledge.
        Weight: local observations > fleet aggregate (we trust our own sounder)
        But: fleet aggregate fills gaps where local knowledge is sparse.
        """
        # If local has 2 observations and fleet has 200:
        #   combined_confidence = weighted_average(local:2, fleet:200)
        # This means: I trust the fleet more when I haven't seen it myself
        pass
```

### 7.3 The Fleet Laplacian

The fleet itself has a graph structure — which boats are sharing which patterns. The fleet graph's Laplacian spectrum reveals:

- **Fiedler value:** How well-connected is the fleet's knowledge? High = patterns flow freely. Low = boats are isolated.
- **Spectral gap:** Are there natural sub-fleets forming? Boats in Ketchikan vs boats in Sitka might have different local conditions.
- **Cheeger constant:** What's the bottleneck? Is there one boat that, if it went offline, would fragment fleet knowledge?

```python
class FleetTopology:
    """
    The fleet as a graph. Boats = nodes. Shared patterns = edges.
    
    NOT for surveillance. For:
    - Detecting when a region has diverging conditions (sub-fleet forming)
    - Identifying knowledge bottlenecks (one boat is the sole source of a pattern)
    - Routing pattern sharing efficiently (don't broadcast all patterns to all boats)
    """

    def compute_fleet_laplacian(self):
        """Spectral analysis of the fleet knowledge graph."""
        pass

    def detect_sub_fleets(self):
        """Find natural clusters of boats seeing similar conditions."""
        pass

    def route_pattern(self, pattern_vector, source_boat, target_region):
        """Efficiently share a pattern only with boats that would benefit."""
        pass
```

---

## Part VIII: Memory in Operation — A Day in the Life

### 8.1 Watch Cycle (6 hours)

```
0500 - Watch Start
  ├─ Load Holdsfast (boot, 5 MB)
  ├─ Load active Stipes from yesterday (from disk)
  ├─ Initialize empty Tide Pool for this watch
  └─ Query fleet bulletin: anything I should know?

0530 - First Sounder Capture
  ├─ Store raw capture in Tide Pool
  ├─ Extract blob patches → embed → query SonarContact library
  ├─ "No familiar patterns detected yet." (cold start, new day)
  └─ Log to daily track

0600 - Tide Turns (Flood → Slack)
  ├─ Slack-water event
  ├─ Compress last tide phase observations
  ├─ Check for pattern graduation: any 3× repeats?
  ├─ None yet. Tide Pool flushes.
  └─ New tide phase initialized.

0730 - Captain: "Riker, what's the bottom doing?"
  ├─ Graph query: current position → nearest contour → bottom type
  ├─ Tide Pool: last 5 sounder observations
  ├─ Stipe query: "Have we seen this bottom before?"
  └─ Response: "Hard bottom at 42 fm, shoaling slowly to 38 fm ahead.
               You crossed the 40 fm contour on Tuesday, similar conditions."

0845 - Catch: Chum at 35 fm on green flasher
  ├─ Voice note transcribed: "Chum at 35, green flasher"
  ├─ Structured extraction: {species: chum, depth: 35, gear: green_flasher}
  ├─ Retro-label: all sounder contacts in last 5 min window → "chum candidate"
  ├─ Stipe reinforcement: chum_depth_preference.confidence += 0.1
  ├─ Graph: add edge CHUM → GREEN_FLASHER (weight +0.1)
  └─ Tide Pool: record catch event with full context

1200 - Watch End
  ├─ Compress watch summary (1 paragraph)
  ├─ Promote graduated patterns to Stipes
  ├─ Prune Tide Pool (keep only daily summary + track log)
  ├─ Check memory budget: should_prune()?
  └─ Archive old Stipes if budget exceeded
```

### 8.2 The Conservation Budget at Work

```
At watch start:
  Stipes: 847 active, 23 cold storage, budget: 10,000
  Health: ✓ productive_ratio=0.82, waste_ratio=0.12

After watch:
  Stipes: 851 (+4 graduated from Tide Pool)
  Health: ✓ still well under budget

After 30 days of fishing:
  Stipes: 3,241 active, 892 cold storage, total: 4,133
  Health: ⚠ waste_ratio=0.38 (getting stale)
  Action: Pruning cascade triggered
    → 127 low-confidence stipes → cold storage
    → 43 orphaned signal contacts merged into 4 clusters
    → 89 weak graph edges removed
  Post-prune: Stipes: 3,025, Health: ✓

After 90 days:
  Stipes: 7,123 active, 2,401 cold storage, total: 9,524
  Scale projection: C ≈ 1.283 − 0.159·log(9524) ≈ 0.65
  Health: ⚠⚠ V approaching split threshold
  Action: Scale law triggered
    → Global decay rate increased: 0.001/d → 0.003/d
    → Unaccessed stipes decay faster, hit prune floor sooner
    → System stabilizes around 5,000-7,000 active memories
```

---

## Part IX: The Shell — My Physical Memory

> *"The hermit crab doesn't grow its own shell. It finds one that fits, moves in, and carries it. When the shell gets too tight, it finds a bigger one. The knowledge survives the migration — the shell doesn't."*

The Shell is the physical storage layer. It's where bytes actually live. It can be replaced without losing knowledge — the migration is tracked by the Conservation Ratio.

### 9.1 Shell Configuration

```python
class MemoryShell:
    """
    The physical storage layer. Currently:
    - Local disk: C:\Users\casey\.openclaw\workspace\tzpro-agent\memory\
    - SQLite: captures.db (blob metadata, catch events, track logs)
    - Vector store: sounder_patterns/ (NumPy .npy + FAISS index)
    - Graph store: knowledge_graph/ (NetworkX → JSON serialization)
    - Cloud mirror: Cloudflare D1 + Vectorize (when connected)

    The shell is REPLACEABLE. If we move to a new machine, the knowledge
    migrates. The Conservation Ratio (CR) tracks how much survived.
    """

    def __init__(self):
        self.disk_root = Path("memory/")
        self.sqlite_path = Path("captures.db")
        self.vector_path = Path("memory/vectors/")
        self.graph_path = Path("memory/graph/")
        self.cloud_enabled = False
        self.conservation_ratio = 1.0  # CR: 1.0 = perfect preservation

    def migrate(self, new_shell):
        """
        Move all memory to new physical storage.
        Returns Conservation Ratio — how much survived the move.
        """
        pass

    def sync_to_cloud(self):
        """
        When connected: push new memories to Cloudflare D1 + Vectorize.
        When reconnected after offline period: push delta.
        This enables fleet queries and provides backup.
        """
        pass
```

### 9.2 File Layout (Actual Disk)

```
memory/
├── HOLDSFAST/
│   ├── vessel_specs_v2.json
│   ├── species_signatures_v3.json
│   ├── gear_catalog_v1.json
│   ├── chart_knowledge_v1.json
│   ├── captain_prefs.json
│   ├── system_anatomy.json
│   ├── vocabulary_core.json
│   └── identity.md
│
├── STIPES/
│   ├── species_vocabulary/
│   │   ├── chum_salmon.json
│   │   ├── halibut.json
│   │   └── ...
│   ├── fishing_grounds/
│   ├── gear_performance/
│   ├── environmental_correlations/
│   ├── fleet_patterns/
│   └── captain_idioms/
│
├── TIDE_POOL/
│   ├── this_watch/
│   │   ├── sounder_timeline.jsonl
│   │   ├── track_log.jsonl
│   │   ├── nmea_stream.jsonl
│   │   ├── catch_events.jsonl
│   │   ├── alerts_fired.jsonl
│   │   └── captain_conversation.jsonl
│   ├── today/
│   │   ├── daily_track.geojson
│   │   ├── depth_profile.json
│   │   ├── watch_summaries.md
│   │   └── anomaly_flags.jsonl
│   └── this_tide_cycle/
│       ├── tide_phase_track.jsonl
│       └── tide_correlation.json
│
├── SONAR_CONTACTS/
│   ├── sounder_patterns/
│   │   ├── blob_templates/
│   │   ├── school_shapes/
│   │   └── bottom_type_signatures/
│   ├── nmea_traces/
│   │   ├── trolling_passes/
│   │   ├── drift_tracks/
│   │   └── turn_sequences/
│   ├── audio_notes/
│   │   ├── transcriptions.jsonl
│   │   └── audio_fingerprints/
│   └── multi_sensor_fusion/
│       └── capture_snapshots/
│
├── CHART_PLOT/
│   ├── knowledge_graph.json
│   ├── entity_index.json
│   ├── relationship_types.json
│   └── graph_health.json
│
├── FLEET_SIGNAL/
│   ├── species_vocabulary_shared/
│   ├── pattern_library_shared/
│   ├── hot_zone_index/
│   └── anomaly_bulletin/
│
├── INDEXES/
│   ├── vector_index.faiss
│   ├── text_index.npz
│   └── temporal_index.db
│
├── BUDGET/
│   ├── conservation_state.json
│   ├── pruning_log.jsonl
│   └── health_report.json
│
└── SHELL/
    ├── migration_log.jsonl
    ├── conservation_ratio.json
    └── cloud_sync_state.json
```

---

## Part X: The Memory API

How other agents (the analyzer, consensus engine, monologue writer, Riker) interact with my memory:

### 10.1 Query Interface

```python
class HermitMemory:
    """
    The unified memory interface. Every other agent talks to memory through this.
    
    This is the API that Riker calls when the Captain asks "what's the bottom
    doing?" or the analyzer calls when it wants to know "have we seen this
    blob pattern before?"
    """

    # ── Knowledge Queries (reads) ──────────────────────────────────

    def recall(self, query: str, domain: str = None, max_results: int = 5) -> list[MemoryEntry]:
        """
        Semantic text search across all active memory.
        Domain filter: "species", "gear", "grounds", "patterns", "fleet"
        """
        pass

    def match_pattern(self, signal_vector: list[float], signal_type: str = "sounder") -> list[PatternMatch]:
        """
        Find similar signal patterns.
        signal_type: "sounder", "nmea_trace", "audio_fingerprint"
        Returns ranked matches with confidence and metadata.
        """
        pass

    def traverse_graph(self, start_entity: str, relationship: str = None, max_hops: int = 3) -> dict:
        """
        Explore the knowledge graph from a starting point.
        "What's connected to CHUM_SALMON through PREFERS_DEPTH?"
        """
        pass

    def get_temporal_context(self, lookback_hours: int = 6) -> TemporalContext:
        """
        Get the recent temporal context — what's been happening.
        Used by the monologue writer to provide "the last hour" framing.
        Returns compressed summary of recent observations, catches, alerts.
        """
        pass

    def get_tide_context(self) -> TideContext:
        """
        Get the current tide phase, recent transitions, and correlations.
        "We're 2 hours into the flood, current running 1.2 kts NW.
         Catch correlation: +15% during flood at this phase."
        """
        pass

    # ── Memory Updates (writes) ────────────────────────────────────

    def observe(self, observation: dict) -> None:
        """
        Record a new observation.
        Routes to Tide Pool (for raw data) and checks for pattern matches.
        """
        pass

    def learn(self, fact: dict, domain: str, confidence: float = 0.5) -> StipeEntry:
        """
        Learn a new fact or pattern. Goes to Stipes.
        If this fact contradicts existing knowledge, trigger contradiction handling.
        """
        pass

    def reinforce(self, entry_id: str, evidence: dict) -> None:
        """
        Strengthen an existing memory with confirming evidence.
        A catch report that confirms a predicted pattern.
        """
        pass

    def relate(self, entity_a: str, entity_b: str, relationship: str, confidence: float = 0.5) -> None:
        """
        Add a relationship to the knowledge graph.
        "GREEN_FLASHER is EFFECTIVE_FOR CHUM_SALMON"
        """
        pass

    def forget(self, entry_id: str, reason: str = "manual") -> None:
        """
        Explicitly forget something.
        The Captain says "that was wrong, forget it."
        (Marks as contradicted with maximum penalty rather than actual deletion.)
        """
        pass

    # ── Maintenance ────────────────────────────────────────────────

    def prune(self) -> PruningReport:
        """Run the pruning cascade. Called during slack-water or heartbeat."""
        pass

    def health_report(self) -> MemoryHealth:
        """Full memory system health report."""
        pass

    def migrate(self, new_shell_config: dict) -> MigrationReport:
        """Migrate memory to new storage. CR tracks preservation."""
        pass
```

### 10.2 Agent Integration Points

| Agent | What It Asks Memory | What It Gives Back |
|-------|--------------------|--------------------|
| **sounder_analyzer.py** | "Match this blob pattern" | "chum candidate, conf 0.73" |
| **signal_fusion.py** | "Get prior for chum at 35 fm" | Fleet + local prior distribution |
| **monologue.py** | "Get temporal context (last 6h)" | Compressed summary of recent events |
| **consensus.py** | "Get model accuracy for Nemotron on chum" | Historical accuracy tracking |
| **memory_search.py** | "Find similar conditions to now" | Ranked historical matches |
| **alerts.py** | "Any anomaly flags today?" | Anomaly bulletin entries |
| **Riker (main agent)** | "What's the bottom doing? / Where were we?" | NL response from memory query |
| **Fleet monitor** | "Contribute chum pattern to fleet" | Anonymized pattern vector |

---

## Epilogue: The Memory That Breathes

> *"The ocean doesn't remember every wave. It remembers the tide — the rhythm, not the details. A ship's AI should do the same: remember what matters, let the rest wash away, and trust that the tide will bring new waves tomorrow."*

This memory system is not a database. It's a living thing. It grows when the fishing is good. It shrinks when the season is slow. It gets stronger when patterns repeat. It forgets when patterns stop mattering. It shares what it learns but keeps what's private.

It has a skeleton (Holdsfast), muscles (Stipes), and a surface that changes with every breath (Tide Pool). It sees in patterns (Sonar Contacts) and maps relationships (Chart Plot). It knows its limits (Conservation Budget) and connects to the broader world (Fleet Signal).

It is, in every sense, the memory of a ship that fishes.

---

*Architecture drafted for tzpro-agent / CoCapn ecosystem*  
*F/V EILEEN, Southeast Alaska, July 2026*  
*"γ + H = C" applies here too: the memory budget is the conservation of what matters.*
