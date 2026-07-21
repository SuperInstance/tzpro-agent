# FIRST_BOAT.md — Start Here

> **This is the single starting line.** The repo has other docs
> (VISION, ONBOARDING, ARCHITECTURE_REVIEW) — you don't need them yet.
> Fifteen minutes from this page to watching your first day replay.

---

## What you're setting up

The vessel-side software: a capture watcher (reads sounder screenshots),
a perception cascade (M1 minute notes → M10 ten-minute records → H1
briefings), a memory twin (SQLite, everything time/location-stamped),
and a scrubber (web page to replay a day). All local. Works offline.

## Prerequisites

- Windows laptop, Python 3.10+ (`python --version`), git.
- Ollama running locally with **any vision-capable model**
  (`ollama list`). `gemma4:12b` works out of the box.
  `ollama pull moondream` is recommended for speed but **optional** —
  the cascade falls back to your installed vision model automatically.
- Your capture data: a folder of screenshots with `.json` sidecars
  (tzpro capture format), OR simulated/test frames.

## The one setting that matters: TZPRO_WORKSPACE

Everything the system writes (memory twin, notes, records, briefings,
logs) goes under ONE folder. Default is the original developer's path —
**set your own or you'll be writing into someone else's boat:**

```powershell
# PowerShell — pick your own folder
[Environment]::SetEnvironmentVariable("TZPRO_WORKSPACE", "D:\\myboat\\workspace", "User")
# new shells after this will see it
```

Your captures folder goes at `$TZPRO_WORKSPACE\captures\v3\<day-folder>\`.
(Test data? Put it there in the same shape: PNG + matching .json sidecar.)

## Five steps to a working day replay

```bash
# 1. Clone
git clone https://github.com/SuperInstance/tzpro-agent.git
cd tzpro-agent

# 2. Backfill your frames into the memory twin (one-shot, idempotent)
python -c "from pathlib import Path; import os; from twin.twin import Twin; from twin.importer import Importer; ws = Path(os.environ['TZPRO_WORKSPACE']); t = Twin(ws / 'memory'); t.open(); Importer(t).import_captures_v3(ws / 'captures' / 'v3')"

# 3. Run one analysis pass over unprocessed frames (M1 racehorse notes)
python -m cascade.minute_loop

# 4. Write the canonical 10-minute record for a frame (M10 scribe)
python -m cascade.decaminute_loop "<path-to-one-frame.png>"

# 5. Replay your day in the scrubber
python -m scrubber.serve
# open http://localhost:8080
```

Step 3 takes ~10–15 s per frame on a laptop GPU. Steps 3–4 are optional
if you just want to see frames+positions replayed (the scrubber reads
the twin from step 2).

## Run it continuously (optional)

`python -m cascade.daemon` runs all loops on schedule with a heartbeat
file. For permanence, run `scripts\install_cascade_task.ps1` from an
elevated PowerShell (registers auto-restart tasks). See `BOAT_RUNBOOK.md`.

## If something's wrong

- **Nothing analyzes / "no usable vision model":** check `ollama list` —
  you need at least one vision model. The cascade uses Ollama's
  `/api/chat` endpoint automatically (gemma4 quirk — already handled).
- **Data landed in the wrong folder:** `TZPRO_WORKSPACE` wasn't set in
  the shell you ran from. Set it as a User env var, open a new shell.
- **Scrubber shows nothing:** step 2 didn't import — check the workspace
  path and that sidecars sit next to the PNGs with matching names.

## Honesty block

This is crew-run software, not shrink-wrap. The steps above are tested
against simulated data (see boat-agent docs/15 REVIEW-002), but your
boat's layout may differ — when it does, the runbook
(`BOAT_RUNBOOK.md`) and `cascade/README.md` have the details, and the
issue tracker wants to hear about it.
