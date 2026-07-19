# 7-Day Strategy: Booting Hermit on EILEEN

> **Date:** 2026-07-19  
> **Horizon:** Next 7 days of development  
> **Goal:** Make the Hermit + tzpro-agent I2I bridge real and useful, not theoretical.

---

## Situation

- `tzpro-agent` pipeline is operational: `capture_v3.py`, `analyzer.py`, `vocabulary.py`, `alerts.py`, SQLite `captures.db`, and ~30 captures with ~22K blobs.
- `hermit_vessel.py` is written and ready to bridge the two systems via the I2I bottle protocol.
- Hermit already exists at `C:\Users\casey\.openclaw\workspace\hermit` but has **not** been booted or connected.
- `_DEEP_IDEATION.md` defines the vision: Hermit as the fleet cognitive command center, file-based bottles, and a layered memory architecture (Holdsfast / Stipes / Tide Pool).
- **This week's job:** get bottles flowing both ways with real fishing data, and seed enough memory that Hermit has something to reason about.

---

## Top 3 Priorities

### 1. Boot Hermit and establish a working I2I bottle bridge

**Why first:** Everything else depends on two-way bottle flow. Until Hermit answers a query from `tzpro-agent`, there is no fleet.

**Concrete work:**
- Start Hermit headless API (`python run_api.py`) on `localhost:8000`.
- Run `python hermit_vessel.py --status` and `python hermit_vessel.py` successfully.
- Fix any path/schema mismatches between `hermit/CORTEX.json` and `tzpro-agent/.vessel/config.json`.
- Verify an `I2I:QUERY` bottle from `tzpro-agent` lands in Hermit's incoming path and a response appears in `tzpro-agent/.vessel/bottles/incoming/`.
- Add a `--bottle-http` fallback in `hermit_vessel.py` that POSTs to Hermit's `/api/v1/a2a/bottle` endpoint if the file-based poller path is not configured.

### 2. Automate capture → Hermit ingestion and response handling

**Why second:** A bridge that requires manual CLI commands is a demo, not a crew member.

**Concrete work:**
- Extend `hermit_vessel.py` or create a lightweight `hermit_bridge.py` daemon that:
  - Sends an `I2I:OBSERVATION` bottle for each new capture (or batches the last 5 captures into an `I2I:SYNTHESIS` every 30 minutes).
  - Polls `.vessel/bottles/incoming/` every 10 seconds for Hermit responses.
  - Writes response summaries to a new SQLite table `hermit_insights` and to the daily Ship Log.
- Map analyzer output (blobs, bottom, thermoclines, vocabulary prediction) into the observation payload already defined in `capture_to_observation()`.
- Surface high-confidence Hermit insights through existing `alerts.py` as a new alert type `HERMIT_INSIGHT` so the Captain sees them.

### 3. Seed the memory architecture with real EILEEN data

**Why third:** Hermit needs a Holdsfast to reason from. The 30 captures and `_WORKING_THEORIES.md` are enough to start.

**Concrete work:**
- Create `memory/holdfast/` files from `_WORKING_THEORIES.md` and existing catch labels:
  - `species_signatures.json`
  - `gear_catalog.json`
  - `fishing_grounds/rock_pile.json`
  - `captain_prefs.json`
- Create `memory/tide_pool/` writer: append-only JSONL for `this-watch/`, `today/`, and `this-tide-cycle/` with TTL-based pruning.
- Implement a minimal `StipeEntry` class in `memory/stipes.py` with `reinforce()`, `contradict()`, `decay()`, and `should_prune()`.
- Add a daily job that promotes any Tide Pool pattern referenced ≥3 times into a Stipe.

---

## 7-Day Build Order

| Day | Focus | Deliverable |
|-----|-------|-------------|
| **1** | Hermit boot + CORTEX handshake | `hermit_vessel.py` runs end-to-end; handshake bottle written |
| **2** | Harden transport (file + HTTP) | Bottle roundtrip test passes; HTTP fallback implemented |
| **3** | Capture → Hermit ingest | New capture triggers `I2I:OBSERVATION` or `I2I:SYNTHESIS` automatically |
| **4** | Response handler + Ship Log | Hermit responses parsed, logged, and surfaced as alerts |
| **5** | Holdsfast seed | Structured memory files exist from real Captain knowledge |
| **6** | Tide Pool + Stipes | Ephemeral memory writes, decay, and graduation tested |
| **7** | End-to-end rehearsal + docs | Full loop demo; update `_BOOT_HERMIT.md`; write week-1 report |

---

## What Should Be Built First

**The bottle bridge (Priority 1).** Do not build memory algorithms, new sensor integrations, or dashboards before Hermit can actually receive and respond to a bottle. A bridge with no traffic is just configuration.

---

## What Can Wait

- **VIAME / Echopype integrations** (`_INTEGRATION_PLAN.md`): Valuable, but optional and heavy. Wait until the Captain confirms raw sonar files are available or until the pixel pipeline is demonstrably limiting catch-rate advice.
- **A2A Agent Card / GNAP task-board alignment**: Do after I2I is stable and a second agent is joining.
- **Frontend dashboard, TTS / pilot-house voice, mascot art, Telegram bot enhancements.**
- **Graph-Laplacian conservation math, recursive analyzer self-improvement, multi-boat fleet vocabulary merging.**
- **Cloudflare D1 migration** beyond the existing replication pattern.

---

## Definition of Done (Week 1)

- [ ] Hermit responds to a `tzpro-agent` query with a structured bottle.
- [ ] A new capture automatically produces an `I2I:OBSERVATION` bottle.
- [ ] `tzpro-agent` reads at least one Hermit response and logs it.
- [ ] `memory/holdfast/` contains species/gear/ground JSON seeded from `_WORKING_THEORIES.md`.
- [ ] Tide Pool prunes entries older than 24 hours without manual cleanup.
- [ ] All changes committed and `_BOOT_HERMIT.md` updated with the working procedure.

---

## Risks / Blockers

| Risk | Mitigation |
|------|------------|
| Hermit may require SurrealDB / Docker that fails on EILEEN's laptop. | Run headless API with SQLite fallback if available; otherwise use file-only mode. |
| Hermit's `/api/v1/a2a/bottle` may expect a different bottle schema than `hermit_vessel.py` produces. | Inspect `hermit/api/a2a.py` on Day 2 and adapt payload structure. |
| Adding Hermit calls must not block the capture daemon. | Use fire-and-forget bottle writes and a separate bridge daemon. |
| Captain availability for confirming working theories / catch labels. | Seed memory from existing documents; validate asynchronously with the Captain. |

---

## One-Sentence Summary

> **Boot the crab, send it real fish data, and give it a memory — then polish everything else.**
