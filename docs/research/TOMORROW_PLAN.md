# Tomorrow Plan — 2026-07-22 R&D Session

> **Filed by:** tonight's in-agent (last session, before shutdown)
> **For:** tomorrow's in-agent (this morning, after operator wakes)
> **Operator status:** has gear to get in; will be busy on deck for several
> hours. You have the helm — *do not ping the operator unless something is
> blocking on a decision that only they can answer*.

## The Goal (one sentence)

Stand up the **ship-log-search companion** alongside the existing tzpro-agent
stack so that by end of tomorrow's session we can do semantic search over
every H1 briefing and D1 daily report the cascade has produced this season.

## Why this matters

The synthesis doc (`SISTER_REPO_SYNTHESIS.md`, commit `b5c5c9c`) recommends
ship-log-search as the recall layer. The cascade already writes structured
JSON sidecars. The bridge between them is the missing piece. Once it's
running, the operator gets a real semantic logbook — every briefing
searchable by meaning, location, and date range, all queryable from a phone
in the pilot house via `http://nav-pc:8787/`.

## What's already in place (don't redo)

| Item | Status | Commit |
|---|---|---|
| tzpro-agent cascade (M1/M10/H1/D1) | ✅ Running | `b110362` |
| Panel web app on `:8081` | ✅ Running | `b110362` |
| Start script for full stack | ✅ `start_stack.py` | `4a686cb` |
| Vision model config (degrades gracefully) | ✅ | `5a157a5` |
| Sister-repo research doc | ✅ | `b5c5c9c` |
| Working tree | ✅ Clean | HEAD `b5c5c9c` |
| NMEA bridge (COM6 → 6006/8654) | ✅ Running | `51cfc5d` |
| 5 Python processes from last night | ✅ Still alive | — |

You should NOT need to re-pull ollama models, restart the cascade, or
reboot anything cascade-related. Verify, don't redo.

## What needs to be built (today's R&D)

### Phase 1 — Verify state (5 min, before any code)

```bash
# 1. Confirm git is at b5c5c9c and clean
cd C:\Users\casey\tzpro-agent
git log --oneline -3
git status

# 2. Confirm processes still alive
powershell -NoProfile -Command "Get-Process python | Select-Object Id, ProcessName, StartTime | Format-Table -AutoSize"

# 3. Confirm panel serving
curl http://127.0.0.1:8081/

# 4. Confirm cascade daemon heartbeat (if file exists)
Get-Content cascade_out\.last_daemon_heartbeat

# 5. Confirm NMEA bridge still serving
curl http://127.0.0.1:8654/health

# 6. Confirm cascade_out\briefings path resolution
Test-Path cascade_out\briefings
Test-Path cascade_out\records
```

If any of these fail, restart via `python start_stack.py` before
proceeding. If panel/daemon are dead but NMEA/captures are alive, that's
fine — we'll fix it in Phase 5.

### Phase 2 — Vendor ship-log-search (15 min)

Don't fork; vendor as a pinned release.

```bash
mkdir vendor
git clone https://github.com/SuperInstance/ship-log-search.git vendor\ship-log-search
cd vendor\ship-log-search
git log --oneline -5
# Pin to the latest v0.2.0 commit (check `git tag` first)
```

Update `.gitignore` to track only the upstream code, not node_modules:

```
# Inside tzpro-agent/.gitignore
vendor/ship-log-search/node_modules/
vendor/ship-log-search/.wrangler/
```

Don't run `npm install` yet — that's Phase 4.

### Phase 3 — Write `companion/` (60 min)

The synthesis doc says ~80 lines. We're going to write ~200 because we want
it idempotent, testable, and observable.

Files to create:

```
tzpro-agent/companion/
├── README.md                    # Operator-facing deployment notes
├── bridge.py                    # Cascade → ship-log-search ingester
├── test_bridge.py               # Unit tests
├── config.example.toml          # URL, key, polling interval
├── Dockerfile.worker            # Image wrapping ship-log-search for self-host
├── docker-compose.yml           # Self-host pattern (Pattern 2 from VESSEL_SETUP)
├── .env.example                 # LOG_KEY=...
└── healthcheck.sh               # curl /health on companion + tzpro-agent stack
```

#### 3a. `companion/bridge.py` — the heart

Responsibilities:
1. Watch `cascade_out/briefings/` for new `*_briefing_*.json` and `day_*.json`
2. For each new file:
   - Parse JSON sidecar
   - Derive `category` from filename/content (catch/observation/weather/navigation/maintenance)
   - Extract `lat`, `lon` from artifact metadata
   - Extract `location_name` from artifact (or default to `Cape Edgecumbe`/etc. — see below)
   - Build `id` = `tzpro-{date}-{HHMM}-{kind}` (stable, idempotent)
   - Build `text` = briefing summary (truncate to 4000 chars)
   - Build `metadata` JSON = full original JSON sidecar
   - POST to `{COMPANION_URL}/api/ingest` with `X-Log-Key`
3. Track sent IDs in `companion/.sent_ids.json` to avoid double-send on restart
4. Exponential backoff on 5xx; fail-fast on 4xx (log + skip)
5. Background thread or `watchdog` observer (already a project dep)

**Critical detail:** Use `watchdog` if available, else poll every 30s. The
synthesis doc says the cascade writes H1 hourly and D1 daily at 03:00 UTC,
so polling at 30s is fine — no need for fancy observer.

**Idempotency rule:** if a file's modification time hasn't changed since last
successful POST, skip. This makes bridge restart safe.

**Why .sent_ids.json not SQL:** tzpro-agent's existing pattern (see `twin/`)
is SQLite for structured records and small JSON for queue/state. Stay
consistent. Future: we can promote to SQLite if `companion/.sent_ids.json`
ever exceeds ~50 KB.

#### 3b. `companion/test_bridge.py`

At minimum:
- `test_parse_h1_briefing_to_log_entry` — feed a sample H1 JSON sidecar,
  verify the resulting dict has all required ship-log-search fields
- `test_idempotency_skip` — run bridge twice on same file, verify only one
  POST happens (mock `requests.post`)
- `test_category_derivation` — feed briefings with different content, verify
  each gets the right `category`
- `test_4xx_skip_5xx_retry` — mock 400 → skip; mock 500 → backoff
- `test_truncate_text_to_4000_chars`

Aim for 5 tests, <100 lines total. Pattern after
`cascade/test_d1_daemon.py`.

#### 3c. `companion/Dockerfile.worker`

The upstream `self-host/Dockerfile` exists but is the wrong image — that's
for the D1/Vectorize stack on Cloudflare. For our local self-host, we want
**miniflare** (Cloudflare's local Worker emulator). Pattern:

```dockerfile
FROM node:20-slim
WORKDIR /app
COPY --from=vendor/ship-log-search /src /app/src
COPY --from=vendor/ship-log-search /package.json /app/
COPY --from=vendor/ship-log-search /wrangler.toml /app/
RUN npm install
EXPOSE 8787
CMD ["npx", "wrangler", "dev", "--port", "8787", "--ip", "0.0.0.0"]
```

NOTE: `wrangler dev` is the dev server; for production local we'd want
`wrangler deploy` to a local-only config. Research the right approach
during Phase 4 — miniflare has evolved.

#### 3d. `companion/docker-compose.yml`

```yaml
services:
  ship-log:
    build:
      context: ..
      dockerfile: companion/Dockerfile.worker
    ports:
      - "8787:8787"
    environment:
      - LOG_KEY=${LOG_KEY}
    volumes:
      - ship-log-data:/data
    restart: unless-stopped
volumes:
  ship-log-data:
```

#### 3e. `companion/healthcheck.sh`

```bash
#!/bin/bash
echo "=== Companion ==="
curl -fsS http://127.0.0.1:8787/health || echo "COMPANION DOWN"
echo
echo "=== Tzpro Panel ==="
curl -fsS http://127.0.0.1:8081/ -o /dev/null -w "%{http_code}\n" || echo "PANEL DOWN"
echo
echo "=== NMEA Bridge ==="
curl -fsS http://127.0.0.1:8654/health -o /dev/null -w "%{http_code}\n" || echo "NMEA DOWN"
echo
echo "=== Capture loop ==="
ls -la captures/v3/ | tail -3 || echo "NO CAPTURES"
```

### Phase 4 — Deploy the companion (30 min)

```bash
cd C:\Users\casey\tzpro-agent\companion

# 1. Generate LOG_KEY
$key = -join ((1..16) | ForEach-Object { '{0:x}' -f (Get-Random -Max 256) })
"LOG_KEY=$key" | Out-File -Encoding utf8 .env

# 2. Vendor deps
cd ..\vendor\ship-log-search
npm install
# verify
npx wrangler --version

# 3. Set D1 + Vectorize for local dev (wrangler.toml may need editing)
# Read the upstream wrangler.toml first. Look for [[d1_databases]] and
# [[vectorize]] bindings. For local dev, miniflare will spin up local D1
# (SQLite file) and in-memory Vectorize substitute.

# 4. Run wrangler dev
npx wrangler dev --port 8787 --ip 0.0.0.0

# In another terminal:
curl http://127.0.0.1:8787/health
curl http://127.0.0.1:8787/api/stats
```

**Expected outcome:** `/health` returns `{ok: true, model: bge-small-en-v1.5,
version: 0.2.0}`. `/api/stats` returns `{entries: 0, ...}`. If 404, check
that the upstream Worker path conventions in `src/index.js` weren't
clobbered by wrangler version mismatch.

**If wrangler dev fails** (likely if upstream hasn't been tested on Node 20+),
fall back to: copy the entire `src/index.js` into a Cloudflare Worker
project we own, deploy to free tier with `wrangler deploy`, get a
`*.workers.dev` URL, set that as `COMPANION_URL` in our `config.toml`. This
is Plan B from the synthesis doc and is fine for now.

### Phase 5 — Wire bridge.py into start_stack.py (20 min)

Extend `start_stack.py` to also launch `companion/bridge.py` after both
panel and cascade are alive. Pattern:

```python
import subprocess, time
from pathlib import Path

COMPANION_DIR = Path(__file__).parent / "companion"
bridge = subprocess.Popen(
    [sys.executable, "bridge.py"],
    cwd=COMPANION_DIR,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
# heartbeat check: ensure .sent_ids.json created within 30s
```

Add `companion/bridge.py` and `companion/.sent_ids.json` to `.gitignore`
(except for `.gitkeep` placeholder if needed).

### Phase 6 — Smoke test end-to-end (15 min)

1. Verify tzpro-agent stack running
2. Verify companion on `:8787`
3. Drop a synthetic H1 JSON in `cascade_out/briefings/` (copy from a previous
   run if any exist; otherwise synthesize one with the right shape)
4. Wait 30s (bridge polling interval)
5. `curl http://127.0.0.1:8787/api/stats` → `entries` should be ≥ 1
6. `curl "http://127.0.0.1:8787/api/search?q=test"` → returns the entry
7. Open `http://127.0.0.1:8787/` in a browser → see the entry in the UI

If 5/6/7 pass, we're golden.

### Phase 7 — Documentation + commit (15 min)

- Update `companion/README.md` with operator-friendly quickstart
- Add a section to top-level `README.md` mentioning the companion
- Update `BOAT_RUNBOOK.md` with the new "Semantic search" entry
- Update `BATON_PASS_YYYY-MM-DD.md` template if one exists
- Commit + push

### Phase 8 — Stretch (only if time remains)

- Pull `bge-small-en-v1.5` to local ollama as a backup embed model
- Write a tiny "search panel" tab inside the existing `:8081` panel that
  proxies to the companion (so operator has one URL for everything)
- Pre-build a week's worth of seed log entries from any past H1 briefings we
  have on disk, backfill them through bridge.py

## Total time budget: ~3 hours

| Phase | Time | Risk |
|---|---|---|
| 1 — verify | 5 min | low |
| 2 — vendor | 15 min | low |
| 3 — write companion/ | 60 min | medium |
| 4 — deploy | 30 min | medium-high (wrangler compat unknown) |
| 5 — wire | 20 min | low |
| 6 — smoke test | 15 min | low |
| 7 — docs + commit | 15 min | low |
| 8 — stretch | optional | varies |

If Phase 4's `wrangler dev` doesn't work after 20 minutes of debugging, **do
not waste more time.** Switch to Plan B: deploy the upstream Worker to
Cloudflare free tier with `wrangler deploy`, get a `*.workers.dev` URL,
point bridge.py at it. The synthesis doc said this is fine. It's actually
probably better because it survives reboots without needing the local
container.

## Decisions to make on the fly

These don't need operator input — use judgment:

1. **Companion port**: Use 8787. Mentioned in synthesis doc. Don't bikeshed.
2. **Bridge polling interval**: 30 seconds. Fine for H1/D1 cadence (hourly+
   daily). Don't use `watchdog` unless it's already a dep — adds complexity
   for no gain.
3. **LOG_KEY storage**: in `companion/.env`, not committed. 16 random hex
   bytes. Display once to operator at end of session for them to save
   elsewhere.
4. **D1 schema**: use upstream's `logs` table verbatim. Don't add tzpro-
   specific columns. Put tzpro context in `metadata` JSON.
5. **Categories**: derive from cascade content using simple keywords:
   - "catch", "harvest", "lbs", "kept" → `catch`
   - "wind", "gust", "sea state", "weather" → `weather`
   - "course", "heading", "position", "drift" → `navigation`
   - "engine", "hydraulic", "repair", "service" → `maintenance`
   - everything else → `observation`

   Update `companion/bridge.py` to keep this mapping in a single function so
   we can iterate.

## What NOT to do

- Don't try to fix the vision model situation (moondream/llava still
  blocked). Cascade is degrading gracefully.
- Don't rewrite the cascade to write into ship-log-search directly. The
  bridge pattern keeps ship-log-search optional — operator can turn it off
  and cascade keeps working.
- Don't change the panel web app yet. Phase 8 stretch only.
- Don't commit secrets. `.env` files, `.sent_ids.json`, node_modules,
  `.wrangler/` — all gitignored.
- Don't wake the operator. Work autonomously until you hit a true blocker
  (e.g., wrong wrangler version that needs operator decision).

## Final commit message template

```
feat(companion): ship-log-search self-host + cascade bridge

Adds tzpro-agent/companion/ — a Cloudflare Worker (via wrangler dev) that
ingests H1 briefings and D1 daily reports from cascade_out/briefings/ into
a self-hosted D1 + Vectorize semantic search index.

- Vendor SuperInstance/ship-log-search @ <commit> under vendor/
- Add companion/bridge.py: 200-line cascade → /api/ingest ingester
  with idempotency via .sent_ids.json
- Add companion/Dockerfile.worker + docker-compose.yml for self-host
  on port 8787
- Wire bridge into start_stack.py
- 5 unit tests in companion/test_bridge.py
- Docs: companion/README.md, updates to BOAT_RUNBOOK.md

End-to-end smoke test: synthetic H1 JSON → /api/search returns the entry.
Verified locally on ProArt PX13 with RTX 4050.

Refs: SISTER_REPO_SYNTHESIS.md (b5c5c9c), TOMORROW_PLAN.md (this commit)
```

## If you only do ONE thing

If phases 2-7 all hit blockers and you only get one thing done, **do this**:

Write `companion/bridge.py` + `companion/test_bridge.py` + commit. Even if
ship-log-search isn't deployed yet, having the bridge ready means the
operator can deploy the upstream Worker on Cloudflare later with a single
`wrangler deploy` and bridge.py is immediately useful.

A tested, documented bridge.py is a tangible deliverable. A half-built
docker-compose with no working bridge is not.

---

*In-agent signing off. Tomorrow-self, you've got this. The operator trusts
the plan. Trust it too.*