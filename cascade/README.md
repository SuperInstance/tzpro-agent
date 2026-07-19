# cascade/ — The Three-Loop Perception Daemon ("zeroclaw")

> Governing design: boat-agent `docs/17_CASCADED_PERCEPTION.md`.
> One job, own scheduler, kill-safe, **no OpenClaw dependency**.

## The loops

| Loop | File | Cadence | Job |
|------|------|---------|-----|
| M1 "racehorse" | `minute_loop.py` | 60 s | one frame + gaze → tiny note; novel notes kept, rest GC'd |
| M10 "scribe" | `decaminute_loop.py` | 10 min | frame + M1 notes → canonical searchable record |
| H1 "analyst" | `hourly_loop.py` | 60 min + on-demand | day's records → briefing with recommendations |

Attention flows **down** via `gaze.json` (human > H1 > M10). Records flow
**up**. The evening pass reads discarded frames one final time before GC —
nothing is deleted unread.

## Layout

```
cascade/
├── daemon.py            # zeroclaw: scheduler + heartbeat + model-degraded mode
├── config.py            # paths, models, thresholds (env-overridable)
├── ollama_client.py     # vision inference via local Ollama
├── gaze.py              # the downward attention channel
├── minute_loop.py       # M1
├── decaminute_loop.py   # M10
├── hourly_loop.py       # H1
└── retention.py         # ring buffer, novelty retention, evening final read + GC
```

## Run

```bash
# once:
python -m cascade.daemon            # foreground (dev)

# installed (Windows Task Scheduler):
schtasks /create /tn "tzpro-cascade" /tr "python -m cascade.daemon" /sc onstart /rl highest /f
```

On-demand briefing: `python -m cascade.hourly_loop --now`

Set the gaze (as the human would from chat):
```bash
python -m cascade.gaze --set "watch 25-35fm for thermocline breaks" --ttl 3600
```

## Output (default: $TZPRO_WORKSPACE/cascade_out/)

```
cascade_out/
├── gaze.json
├── heartbeat.json          # daemon liveness — watchdog this
├── minute_notes/novel/     # retained racehorse notes (training ore)
├── records/                # canonical M10 records (never GC'd)
├── briefings/              # H1 briefings (never GC'd)
└── logs/
```

## Rules (inherited, non-negotiable)

1. Read-only on the captures tree. Atomic writes (temp+rename) everywhere.
2. Kill-safe between frames; idempotent re-runs.
3. Ollama down = queue quietly, never crash, never invent analysis.
4. Every decision is a record: what was analyzed, skipped, kept, and why.

## Field notes (2026-07-19, first live run)

- All three loops verified end-to-end on real captures (18 frames, F/V
  EILEEN): M1 notes, M10 canonical record, H1 briefing with confidence-
  tagged recommendations, and the gaze channel firing (M10 → M1).
- **Calibration watch:** gemma4:12b marks ~95% of frames novel/notable —
  `NOVELTY_THRESHOLD = 0.65` retains nearly everything, which defeats the
  GC contract. Tune per model (try 0.8, or percentile-of-day scoring)
  before trusting retention. Novelty scores are model-relative, not
  absolute.
- **Ollama API:** use `/api/chat` with `think: false` — `/api/generate`
  returns empty completions for gemma4 with images (verified live).
- ~10–15 s per M1 frame on the RTX 4050 (gemma4:12b); moondream should
  be pulled for true minute-cadence margin.

