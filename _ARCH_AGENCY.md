# ARCH: Agency Architecture

## What the Art Said About Delegation

### The Specialist and the Generalist

The essays draw a clear line: a specialist knows one thing deeply but cannot generalize. A generalist knows the shape of everything but cannot descend into detail. They need each other, but crucially: **the generalist must know when to call the specialist, and the specialist must know when to defer back.**

Applied to our fleet:
- **Riker (DeepSeek V4 Flash)** is the generalist. Sees the whole picture — capture daemon status, analyzer health, NMEA stream, vocabulary confidence, alert states. Integrates. Does not descend into blob-by-blob analysis.
- **Copilots** are the specialists. One task, one lens, perfect focus. Seed dreams, Hermes synthesizes, Nemotron deduces, Pro polishes.
- **Rule:** The generalist never does specialist work. If Riker starts debugging blob detection thresholds, something has gone wrong. The copilot handles it and reports back a single-sentence verdict.

### The Specialist and the Clone

A clone is not a specialist — it's the same model doing the same thing in parallel. Useful for exhaustive search, useless for insight. The essay warns: **don't call a clone when you need a specialist**.

Applied: spawning 4 identical agents to read the same essay is a clone strategy. Spawning 4 different models to read 4 different essay sets is a specialist strategy. We got this right today.

### The Step-Back Operator

The most powerful agent in any fleet is the one that doesn't act — it **steps back** and asks "are we doing the right thing?" This is the Captain. This is also the meta-agent that reviews copilot outputs before they become code.

Applied: every copilot output should be reviewed by a different copilot before commit. Not for correctness — for *alignment with the Captain's intent*. Riker reads what the copilots produced and asks "does this serve the mission?"

### The Baton Spline

Handoff between agents is not instantaneous. There is a period — a spline — where both agents are active and the transfer is not yet complete. **The spline is where errors happen.**

Applied: when the analyzer finishes processing a capture and the vocabulary module picks up the new blobs, there's a narrow window where the data is partially committed. Our schema versioning handles this at the data level, but at the agent level we have no equivalent. Rule: **no agent should start work until the previous agent has written its complete output to disk.** Wait for the file. Don't poll. Wait.

### The Fleet Will Never Replace You

The core insight: the fleet amplifies the Captain, it does not replace him. Every alert, every prediction, every vocabulary update is a *suggestion*, not a *command*. The Captain makes the final call.

Applied: the alerts daemon fires notifications, but it should never take action. It should surface and wait. The vocabulary sets confidence thresholds, but the threshold should be configurable per Captain. The system serves the human. The human does not serve the system.

---

## Actionable Code Changes

### 1. Agent Task Router
Create a `_router.py` that maps task types to agent models:
```python
ROUTER = {
    "creative_vision": "seed2",      # Seed 2 Mini
    "synthesis": "hermes3",          # Hermes 3 405B  
    "deduction": "nemotron",         # Nemotron 3 Ultra
    "premium": "v4pro",              # DeepSeek V4 Pro
    "review": "v4pro",              # Review is a premium task
    "system": "flash",               # Riker stays on Flash
}
```
This encodes the specialist/generalist boundary in machine-readable form.

### 2. Baton Handshake
Add a handshake file pattern: `_lock_{task_name}.lock`. Before an agent starts work, it checks for locks. After it writes output, it removes the lock. Next agent waits for lock release before starting. Prevents the spline error.

### 3. Step-Back Gate
Every copilot-written file should include a `## Review` section at the bottom, initially blank. A review agent fills it in before the file goes to commit. This forces a second-pass check without duplicating work.

### 4. Captain's Config Threshold
Move all magic numbers to a `captain_config.json` that the Captain can edit:
```json
{
  "vocabulary_threshold": 0.7,
  "alert_bottom_change_fm": 2.0,
  "capture_interval_min": 10,
  "grid_cell_size_deg": 0.01
}
```
The system serves. The Captain configures.
