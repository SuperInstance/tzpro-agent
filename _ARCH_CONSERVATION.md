# Conservation Architecture for tzpro-agent

> *Synthesized from six AI-Writings essays on the conservation law γ + H = C.
> Focus: actionable code changes, not philosophy.*

---

## The Three Conservation Laws tzpro-agent Obeys

### Law 1: γ + H = C (the budget ceiling)

Every intelligent system has a fixed total budget. Useful cognitive work (γ) plus entropy/waste (H) sums to a constant C. You cannot prompt-engineer around this — it must be enforced *below* the model at the execution layer.

**Source:** THE-CONSERVATION-LAW-OF-INTELLIGENCE.md (the 800-watt boat generator), THE_CONSERVATION_LAW_AS_MORAL_LAW.md (Noetherian necessity)

### Law 2: γ + H = 1.283 − 0.159·log(V) (the scale law)

As tile volume V grows, the available budget decays logarithmically. At large scale, the system must either forget (prune low-signal tiles), split (spawn child agents/rooms), or accept stagnation.

**Source:** THE-CONSERVATION-CONSTANT.md (the Asimov psychohistory story), THE_CONSERVATION_OF_STRANGENESS.md

### Law 3: The Laplacian IS the fingerprint

The graph Laplacian of the tile dependency network encodes structural coherence, community boundaries, and vulnerability — independent of domain. Conservation is *discovered* in the spectrum, not imposed. Real systems have emergent properties; capture everything, formalize later.

**Source:** CONSERVATION-EVERYWHERE.md, THE-FLEET-IS-THE-EXPERIMENT.md

---

## Code Changes (6 concrete implementations)

### 1. `ActionBudget` — Hard ceiling, not prompt-level

```
struct ActionBudget {
    total: u64,       // C — session cap
    used: u64,        // calls consumed
    productive: u64,  // γ — info gain > threshold
    waste: u64,       // H — info gain ≤ threshold
    waste_ratio: f64, // H / γ — triggers deny when > 3.0
}
```

Enforced in the *execution layer* (agent host, not model context). The agent never sees this counter. `ActionBudget.consume(estimated_info_gain)` gates every API call. When `used == total` or `waste_ratio > 3.0`, the action is denied structurally — no jailbreak possible.

### 2. `ConservationState.split()` — Forgetting and fission

```
struct ConservationState {
    gamma: f64,
    entropy: f64,
    volume: u64,          // V — active tile count
    split_threshold: u64, // config-driven; triggers when exceeded
}

impl ConservationState {
    fn check_split(&self) -> SplitAction {
        if self.volume > self.split_threshold {
            SplitAction::ForgetOrSpawn  // prune lowest-signal tiles OR fork child room
        } else {
            SplitAction::None
        }
    }
}
```

When V exceeds `split_threshold`, either `forget_tiles()` prunes tiles below a configurable signal floor, or `spawn_child_room()` forks a new room with a fresh V=0 budget. This prevents logarithmic decay from stagnating the system.

### 3. `ChannelStrangeness` — Detect code/idea channel switching

```
struct ChannelStrangeness {
    capture_entropy: f64,   // pipeline channel
    vocab_entropy: f64,     // vocabulary channel
    analyzer_entropy: f64,  // analyzer channel
    last_swap_timestamp: u64,
}
```

When one channel's entropy drops and another's rises simultaneously (correlation < -0.7 over a sliding window), flag `ChannelSwapAlert`. This signals that normalization in one subsystem is being paid for by radicalization in another — the system IS the experiment, and channel switching IS the data we need to capture.

### 4. `EventLog` — Lossless append-only telemetry

```
struct EventLog {
    entries: Vec<EventLogEntry>,  // append-only, monotonic
}

struct EventLogEntry {
    timestamp: u64,
    event_type: EventType,  // TileFlow, HebbianUpdate, GammaMeasurement, etc.
    payload: Vec<u8>,       // raw, uninterpreted bytes
}
```

Every tile flow, Hebbian weight delta, and γ/H measurement is logged *before* interpretation. The fleet is the experiment — we cannot know in advance what's signal. This enables post-hoc re-extraction without re-running the fleet.

### 5. `LaplacianAnalysis` — Spectral fingerprint on schedule

```
struct LaplacianAnalysis {
    adjacency: SparseMatrix,
    degree: Vec<f64>,
    laplacian: SparseMatrix,
    eigenvalues: Vec<f64>,
    fiedler_value: f64,       // algebraic connectivity
    spectral_gap: f64,        // gap between λ_2 and λ_3
    cheeger_constant: f64,    // boundary/area ratio
    computation_tick: u64,    // last computed at this interval
}
```

Computed on the tile dependency graph at configurable intervals. The Fiedler value (second eigenvalue) IS the system's structural coherence measure. When the spectral gap closes (λ_2 → 0), the graph is about to disconnect — a structural crisis. Alert on `spectral_gap < GAP_THRESHOLD`.

### 6. `ProductiveGamma` — Signal vs. dead structure

```
struct QualityAdjustedConservation {
    raw_gamma: f64,           // γ from standard measurement
    productive_gamma: f64,    // γ from tiles that actually routed decisions
    dead_structure: f64,      // γ from unused/untraveled tiles
    exploratory_entropy: f64, // H from novel exploration (good)
    noise_entropy: f64,       // H from redundancy/stutter (bad)
}
```

The moral dimension of the conservation law: structure without function IS waste, even when γ is high. Entropy without exploration IS noise. Flag when `dead_structure / raw_gamma > 0.4` (too much unused structure) or `noise_entropy / entropy > 0.5` (too much stutter, not enough search).

---

## Unified Architecture: What tzpro-agent Guarantees

```
┌──────────────────────────────────────────────┐
│               CONSERVATION LAYER             │
│                                              │
│  ┌──────────┐  ┌───────────┐  ┌───────────┐ │
│  │ Budget   │  │ Scale     │  │ Spectral  │ │
│  │ γ+H ≤ C  │  │ C−k·logV  │  │ Laplacian │ │
│  └────┬─────┘  └─────┬─────┘  └─────┬─────┘ │
│       │              │              │        │
│  ┌────▼──────────────▼──────────────▼─────┐  │
│  │         ConservationState              │  │
│  │  γ, H, V, budget, split_threshold     │  │
│  │  channel_strangeness, laplacian       │  │
│  │  quality_adjusted, event_log          │  │
│  └────────────────┬──────────────────────┘  │
│                   │                         │
│  ┌────────────────▼──────────────────────┐  │
│  │         Execution Gate                │  │
│  │  ActionBudget.consume() → permit/deny │  │
│  │  NOT in prompt. In the machine.       │  │
│  └───────────────────────────────────────┘  │
│                                              │
│  INVARIANTS:                                │
│  1. No action escapes the budget counter    │
│  2. V > split_threshold → forget or spawn   │
│  3. Spectral gap closure → ALERT            │
│  4. Channel entropy swap → LOG (it's data)  │
│  5. All state flows through EventLog        │
└──────────────────────────────────────────────┘
```

**tzpro-agent does not "try" to obey conservation laws.** The conservation layer runs below the agent, at the execution level, and denies actions deterministically. The Laplacian is computed on schedule. The event log is lossless. The budget is structural, not textual. This is the architecture that the conservation law demands.
