# Local Models for the Boat's Internal Monologue

## The Concept

An always-on awareness layer. Not a chatbot — a background process that reads sensor data,
maintains state, generates low-level observations, and only speaks when something matters.
Like the hum of the engines. You don't notice it until the pitch changes.

## The Hardware Budget

- **GPU:** RTX 4050 6GB VRAM (shared with display, power-aware)
- **RAM:** 32GB (plenty for model loading + grid cache)
- **CPU:** Ryzen AI 9 HX 370 (12C/24T — can run small models without GPU)
- **Already running:** Ollama with qwen3:4b

## Model Candidates

### Tier 1: Always-On (CPU / integrated GPU / shared VRAM)
*These stay loaded constantly, even at anchor.*

| Model | Size | Why | Power |
|-------|------|-----|-------|
| **qwen3:4b** (Ollama) | 2.5GB | Already loaded. Baseline internal monologue. Can process observations, generate alerts, maintain conversation state. | Low |
| **Phi-3-mini (3.8B)** GGUF | 2.2GB | Best-in-class for its size. Better reasoning than qwen3:4b on structured data. Would replace it. | Low |
| **Llama 3.2 3B** GGUF Q4 | 1.8GB | Fast, efficient, good at instruction following. Excellent for the "alert formatter" role. | Very Low |
| **Nomic-embed-text** (Ollama) | 0.3GB | Embedding model for memory search — matches current conditions against historical observations. | Minimal |
| **BGE-small** (Ollama) | 0.1GB | Alternative embedding model, slightly better for maritime/oceanic text. | Minimal |

### Tier 2: On-Demand GPU (swapped in when needed)
*These get loaded when the Captain starts fishing, unloaded at anchor.*

| Model | Size | Why | Notes |
|-------|------|-----|-------|
| **qwen3:8b** (Ollama) | 4.8GB | Upgrade from current 4b. Better reasoning for forward-look analysis, alert evaluation. Same Ollama API, drop-in replacement. | Fits in 6GB with ~1GB margin |
| **Florence-2** (PyTorch) | 0.9GB | Vision-language for sounder images. Identifies fish arches, bottom types, thermoclines from the cropped panel. This is the Phase 5 experiment. | GPU-native, efficient |
| **Mistral 7B** GGUF Q4 | 4.1GB | Better than qwen3:8b at spatial reasoning and multi-turn analysis. Good for the "what's changed since yesterday" queries. | Fits in 6GB |
| **Llama 3.1 8B** GGUF Q4 | 4.5GB | The safe choice. Well-tested, good tool use, reliable output formatting. | Tight fit with display |

### Tier 3: Power-Save Mode (when on battery / at anchor)
*Minimum viable awareness.*

| Model | Size | Why |
|-------|------|-----|
| **SmolLM2 1.7B** (Ollama) | 1.1GB | Tiny. Runs on CPU at 20+t/s. Can still process NMEA data and check for drift alerts. |
| **Llama 3.2 1B** GGUF Q4 | 0.7GB | Almost no memory footprint, runs on any core. "Depth changed by X, logged anomaly Y, nothing needs attention." |
| **Whisper tiny** | 0.4GB | Speech-to-text for voice commands. Could listen for "where's the 48?" or "what's the bottom look like?" |

## The Internal Monologue Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   INTERNAL MONOLOGUE                        │
│                                                             │
│  [NMEA tick @ 30s]                                         │
│    ├─ read position (lat, lon, sog, cog)                   │
│    ├─ query contour grid → depth_fm, clearance             │
│    ├─ run forward_look → profile, crossings, alerts        │
│    └─ pipe into small LLM                                  │
│                                                             │
│  [Small LLM processes observation]                          │
│    ├─ "Depth stable at 67 fm, gear clearance +19.          │
│    │   No contour crossing imminent at current heading."   │
│    ├─ → logged to memory, no Captain alert                 │
│    └─ (This is the hum of the engines)                     │
│                                                             │
│  [When anomaly detected]                                    │
│    ├─ "Sounder 53 fm vs chart 67 fm — 14 fm delta.         │
│    │   Possible depth scale calibration issue or           │
│    │   bottom change. Flagging for morning review."        │
│    ├─ → logged to anomalies database                       │
│    ├─ → IF delta > threshold → Captain alert               │
│    └─ (This is the pitch change)                           │
│                                                             │
│  [When Captain asks a question]                             │
│    ├─ load query into medium model (GPU swap)              │
│    ├─ search memory via BGE embeddings                     │
│    ├─ generate answer from grid + memory + position        │
│    └─ unload medium model, resume monologue                │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## The Tidal Model Strategy

Follows the Captain's own philosophy — "Ebb and Flow":

| Mode | When | Models Loaded | Power |
|------|------|--------------|-------|
| **Idle / Anchor** | Overnight, tied up | qwen3:4b + nomic-embed-text | ~15W (CPU only) |
| **Transit** | Underway, not fishing | qwen3:4b + nomic-embed-text + Whisper tiny | ~25W |
| **Fishing** | Working grounds | qwen3:8b + Florence-2 (alternating) | ~45W (GPU active) |
| **Processing** | Post-trip analysis | qwen3:8b + Florence-2 (parallel) | ~55W (full GPU) |

## Recommendation

For the always-on internal monologue:

1. **Keep qwen3:4b** as the primary monologue engine — it's already loaded, works, and costs zero setup time.

2. **Add Nomic-embed-text** (Ollama, `ollama pull nomic-embed-text`) — this enables semantic memory search across observations. When the monologue says "this feels like what we saw last Tuesday," the embedding model makes that connection real.

3. **First GPU experiment**: Load Florence-2 on the RTX 4050 and run it on a sounder crop. This is the one experiment that can't be done without the GPU — and it's the one that adds the most value (vision-based bottom analysis).

4. **Second GPU experiment**: Replace qwen3:4b with qwen3:8b for the internal monologue when fishing. Same Ollama API, better reasoning, drops into the existing pipeline.

The power strategy: the monologue model runs on CPU via Ollama at < 10W when at anchor. When you start the day's trip, it keeps running. When you drop gear, the GPU spins up for Florence-2 + qwen3:8b. When you tie up, GPU goes back to sleep. The monologue never stops — it just gets quieter or more capable depending on the tide.
