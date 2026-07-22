# companion/ — ship-log-search bridge for tzpro-agent

Watches the cascade's H1 briefing and D1 daily-report outputs and ingests
them into a self-hosted [ship-log-search](https://github.com/SuperInstance/ship-log-search)
Worker, so every briefing becomes semantically searchable.

## Why

The cascade produces a stream of structured JSON sidecars:
- `cascade_out/briefings/_briefing_<UTC>.md` — H1 hourly briefings
- `cascade_out/briefings/_briefing_<UTC>.json` — H1 structured sidecars (new in commit b110362)
- `cascade_out/briefings/day_<DATE>.md` — D1 daily narrative
- `cascade_out/briefings/day_<DATE>.json` — D1 structured sidecars

But search across them is currently full-text grep. With ship-log-search
backing them, every briefing becomes:
- semantically searchable ("show me every time we had good chumming on
  south-east grounds" — even if those exact words aren't in the briefing)
- spatially searchable ("what happened within 50 km of Cape Edgecumbe?")
- temporally searchable ("all catch briefings from July 2026")

## How it works

`bridge.py` polls `cascade_out/briefings/` every 30 s. For each new
briefing JSON or daily JSON:

1. Parse the structured JSON sidecar
2. Derive `category` from content keywords
3. Extract lat/lon, location_name, timestamp
4. Build a `ship-log-search`-shaped log entry
5. POST to `{COMPANION_URL}/api/ingest` with `X-Log-Key`
6. Track sent IDs in `.sent_ids.json` to avoid double-send on restart

The companion (ship-log-search itself) is expected to be running on
`http://127.0.0.1:8787/`. See "Deployment" below.

## Quick start (operator-facing)

```bash
# 1. Generate a LOG_KEY (only once per vessel)
python -c "import secrets; print('LOG_KEY=' + secrets.token_hex(16))" > companion/.env

# 2. Start the companion (ship-log-search via wrangler dev)
#    See Phase 4 of docs/research/TOMORROW_PLAN.md
npx wrangler dev --port 8787 --ip 0.0.0.0

# 3. In another terminal, start the bridge
cd companion
python bridge.py

# 4. Open the search UI
# http://127.0.0.1:8787/
```

## File layout

```
companion/
├── README.md            # This file
├── bridge.py            # Cascade → ship-log-search ingester (~200 lines)
├── test_bridge.py       # Unit tests for the bridge
├── config.example.toml  # Sample configuration
├── healthcheck.sh       # Curl all 3 services (companion, panel, NMEA)
├── Dockerfile.worker    # Self-host image (optional, deferred)
└── docker-compose.yml   # Self-host pattern (optional, deferred)
```

## Deployment options

**Option A — Cloudflare free tier** (recommended during fishing season):
`wrangler deploy` from upstream ship-log-search repo. Get a `*.workers.dev`
URL. Set `COMPANION_URL` and `COMPANION_KEY` in `config.toml` to point at
it. Cost: $0.

**Option B — Self-host on the nav PC** (recommended for in-port or fully
offline use): clone `vendor/ship-log-search/`, run `npx wrangler dev --port
8787`. Cost: ~250 MB RAM for the Worker, ~50 MB for the SQLite D1 file.

**Option C — Local sentence-transformers** (most minimal): replace
ship-log-search entirely with a local embed + cosine search. Not
implemented; only pursue if Options A and B are blocked.

See `docs/research/SISTER_REPO_SYNTHESIS.md` for the full analysis.

## Status

Phase 3 in-progress as of 2026-07-22 morning session. See git log for
the most recent commit. End-to-end smoke test is the next milestone.

## Authoring

Built by Eileen's in-agent (`docs/research/TOMORROW_PLAN.md`,
commit `32e3ab8`). Ship log search backend by `@cf/baai/bge-small-en-v1.5`
+ Cloudflare Vectorize + D1.