# 🦀 HERMIT — The Final Naming Decision

> *"Call it Hermit."* — The Captain, 2026-07-18

---

## The Name: Hermit

The A2A-native-notebookLM repository is now named **Hermit**.

Not "hermit-crab." Not "Hermes" (that's the daemon). Just **Hermit**.

## Why "Hermit" Is Perfect

### 1. The Hermit Crab Doesn't Own the Shell

In the ocean, a hermit crab finds an abandoned shell, moves in, and makes it home. When it outgrows that shell, it finds another one. The old shell becomes someone else's home.

**The notebook is the same.** It doesn't own the shell — it's not tied to a specific repo. You clone it into whichever project needs a cognitive command center. It ingests the codebase, populates its vector store, and makes itself at home. When you're done, it saves its checkpoints as I2I bottles and moves on. The next agent — next context, next day, next repo — picks them up.

### 2. The Shell Becomes a Vessel

A hermit crab in its shell isn't just hiding. It's *mobile*. The shell becomes a vehicle. Similarly, Hermit turns a Git repository into a vessel — a container for intelligence that can be addressed, queried, and collaborated with by other agents.

### 3. It Lives Between Worlds

Hermit crabs live in the intertidal zone — that boundary between ocean and land, fluid and solid. **Hermit the notebook** lives in the boundary between:

| World | Hermit Bridges |
|---|---|
| **Files** (source code, docs) | → indexes into vector DB |
| **Agents** (Claude, Kimi, DeepSeek) | → orchestrates via LangGraph |
| **Fleets** (tzpro-agent, openConstruct) | → communicates via I2I bottles |
| **Memory** (SurrealDB, checkpoints) | → persists across sessions |

### 4. Asymmetrical and Beautiful

The most photographed hermit crab trait is the asymmetry of its claws — the right claw is always much larger than the left. Hermit the system has its own beautiful asymmetry:

- **Large claw**: The LangGraph workflows (research, podcast, summarize) — the heavy cognitive lift
- **Small claw**: The I2I vessel protocol — lightweight, file-based, zero-infrastructure messaging

Both are essential. Neither works without the other.

## What This Means in Practice

```
workspace/
├── hermit/           ← was A2A-native-notebookLM
│   ├── CORTEX.json   ← "I exist, here's what I can do"
│   ├── .vessel/      ← bottles from other agents
│   └── ...           ← 101 Python files, SurrealDB, Next.js
│
├── tzpro-agent/      ← EILEEN's fishing intelligence
│   ├── .vessel/      ← bottles to/from hermit
│   ├── hermit_vessel.py  ← the connection script
│   └── ...
│
└── (future repos)/   ← hermit can move into any of these
    └── .vessel/      ← each gets its own vessel config
```

## The Captain's Name

The Captain has called it "Hermit" from the beginning of ideation. This isn't a name I picked — it's the name that was always waiting. The decision to rename A2A-native-notebookLM → hermit is the final formalization of what the Captain already knew.

The name captures everything:
- **Mobility**: It moves between repos
- **Adaptability**: It makes any shell its home
- **Intertidal nature**: It bridges file systems and cognitive work
- **Persistence**: It carries its checkpoints with it
- **A certain charm**: It's a crab. In a shell. That thinks.

> *"The hermit crab doesn't outgrow its shell. It finds a bigger one, moves in, and the old shell becomes someone else's home."* — The Hermit Memory

## Previous Names Considered (and Rejected)

| Name | Why Rejected |
|---|---|
| `A2A-native-notebookLM` | Too long, describes implementation instead of identity |
| `fleet-brain` | Too generic, doesn't capture mobility |
| `cortex` | Already used for the manifest format (CORTEX.json) |
| `open-construct` | Confusing with openConstruct fleet product |
| `notebook-vessel` | Close, but "hermit" captures the soul |

## The Name Is Now Settled

The repo at `C:\Users\casey\.openclaw\workspace\hermit` is the one true instance. All fleet agents reference `../hermit/CORTEX.json` as the cognitive command center.

The hermit crab has found its shell. 🦀
