# Sister-Repo Synthesis: ship-log-search & search-superinstance-ai

> Research deliverable for tzpro-agent. Compiled by the in-agent (inside
> Eileen's virtual shell) on 2026-07-22 morning after a thorough read of both
> upstream repos at HEAD on `main`. This is a design document, not code.

## TL;DR

Both sister repos are **excellent backends** for tzpro-agent — better than
anything we'd build from scratch. They solve the same problem (semantic +
spatial + temporal recall over time-stamped records) and they use the same
exact architecture (D1 + Vectorize + Workers AI `bge-small-en-v1.5`) — a stack
that's already validated, free-tier-friendly, and aligned with the
tzpro-agent's structured-output philosophy.

**Recommendation:** ship tzpro-agent as the *producer* of structured records
(M10 echogram records, H1 briefings, D1 day reports) and use **ship-log-search
as the recall layer** — either self-hosted on the boat or deployed to
Cloudflare free tier. We get years of captain-readable search ("show me every
time we had good chumming near Cape Edgecumbe in a south-east wind") for the
cost of one `curl POST /api/ingest` per H1/D1.

**Bonus:** The same `bge-small-en-v1.5` model can be pulled and run locally
via `sentence-transformers` on the RTX 4050 (it fits in <500 MB VRAM, 384
dims) if we'd rather not depend on Cloudflare at all.

---

## Repo 1: SuperInstance/ship-log-search

**Size:** ~61 KB Worker, ~25 KB embedded UI. Single-file deployable.

**Architecture (read from `src/index.js`):**

| Layer | Tech | Role |
|---|---|---|
| Compute | Cloudflare Workers (no build step) | Routing, validation, embeddings |
| Source of truth | Cloudflare D1 (SQLite) | All log records, SQL range queries |
| Semantic index | Cloudflare Vectorize | 384-dim cosine similarity search |
| Embedding model | `@cf/baai/bge-small-en-v1.5` (Workers AI) | Query & document embedding |
| Frontend | Inline HTML template string in Worker | Dark-themed 4-tab SPA |

**Endpoints (all JSON):**

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | The SPA |
| GET | `/health` | Liveness + model + version |
| GET | `/api/search?q=&k=&category=&from=&to=` | Semantic search (Vectorize → D1 join) |
| GET | `/api/nearby?lat=&lon=&radius=&k=` | Spatial search (D1 bounding-box + haversine refine) |
| GET | `/api/timeline?from=&to=&category=&k=` | SQL range query with ORDER BY timestamp DESC |
| POST | `/api/ingest` | Bulk insert → D1 + Vectorize (auth: `X-Log-Key`) |
| POST | `/api/log` | Single entry insert → D1 + Vectorize |
| DELETE | `/api/log/:id` | Remove single entry from both stores |
| GET | `/api/stats` | Counts, categories, date range |

**Schema (from `self-host/migrations/0001_init.sql`):**

```sql
CREATE TABLE logs (
    id            TEXT PRIMARY KEY,
    text          TEXT NOT NULL,
    category      TEXT NOT NULL DEFAULT 'observation',
    lat           REAL,
    lon           REAL,
    location_name TEXT,
    timestamp     TEXT NOT NULL,
    metadata      TEXT,
    created_at    INTEGER DEFAULT (strftime('%s', 'now'))
);
CREATE INDEX idx_logs_ts     ON logs (timestamp);
CREATE INDEX idx_logs_cat    ON logs (category);
CREATE INDEX idx_logs_latlon ON logs (lat, lon);
```

Valid categories: `catch`, `maintenance`, `weather`, `observation`, `navigation`.

**Embedding text construction:**
```js
[text, category, location_name].filter(Boolean).join(' | ')
```

**Quality / production maturity:** v0.2.0. The source explicitly tags "P0
fixes" already applied: topK cap, text storage in D1, D1 migration, XSS
prevention, error leak prevention. UI is mobile-first, dark-themed,
WAI-ARIA-compliant, has browser geolocation integration, localStorage write
key persistence, filter chips with individual removal, score visualization
(percent badge + gradient bar), and `escHtml` for every render. This is a
real, deployable product, not a prototype.

**Self-host path:** The repo ships a `self-host/` directory with Dockerfile,
docker-compose.yml, .env.example, init-db.sh, and the migration SQL. The
companion `VESSEL_SETUP.md` is a 12 KB setup guide written explicitly for
"OpenClaw agents on navigation computers."

**Free tier headroom:**

| Resource | Free limit | Single-vessel use |
|---|---|---|
| Workers req/day | 100K | ~100-500 |
| Workers AI neurons/day | 10K | ~100-500 embeds |
| Vectorize vectors/index | 10M | <10K entries |
| D1 reads/day | 5M | <1K |
| D1 writes/day | 100K | <100 |

For a single F/V Eileen logging every 10 minutes all day, this is <1% of
every limit for years.

---

## Repo 2: SuperInstance/search-superinstance-ai

**Size:** ~25 KB. Lighter, demo-grade.

**Architecture:** Identical stack — same `bge-small-en-v1.5`, same
Vectorize, no D1 (Vectorize is the only store). Endpoints: `/`, `/health`,
`/api/stats`, `/api/search`, `/api/ingest`.

**Differentiation:** UI displays `metadata.repo`, `metadata.description`, and
renders `language`/`topic`/`category`/`type` as tag chips, with the top
languages appearing as filter chips beneath results. The result-card design
is the cleanest of the two and worth stealing patterns from.

**Index name:** `superinstance-repos`.

**Not directly useful to tzpro-agent** as a backend (it's a demo over public
GitHub repo metadata). But its UI patterns and the `topLanguages` filter-chip
concept are worth porting into our `panel/` 3-panel web app.

---

## How tzpro-agent maps onto the ship-log-search schema

This is where the design clicks.

| tzpro-agent artifact | ship-log-search field | Source |
|---|---|---|
| Echogram frame (10-min canonical) | `id` = `echogram-YYYY-MM-DDTHH-MM_<lat>N_<lon>W` | `cascade/decaminute_loop.py` |
| H1 briefing markdown text | `text` | `cascade/hourly_loop.py` |
| H1 briefing JSON `summary` | `text` (preferred over MD — denser) | new `_briefing_<ts>.json` |
| D1 daily report JSON `key_events[].narrative` | one `text` per event | `cascade/daily_loop.py` |
| Vessel lat/lon at capture time | `lat`, `lon` | NMEA bridge |
| Named fishing ground | `location_name` | crew-supplied ground names |
| H1/D1 category bucket | `category` ∈ {catch, observation, weather, navigation, maintenance} | derived from M10 content |
| Capture timestamp | `timestamp` | `datetime.utcnow().isoformat() + "Z"` |
| Full JSON sidecar | `metadata` (TEXT, JSON-encoded) | existing artifact |
| Embedding target | `[text, category, location_name].filter(Boolean).join(' \| ')` | same as ship-log-search |

**Volume estimate per season:** 6 hooks/day × 30 days × ~6 embeds (H1 + D1
plus optional M10 hotspots) ≈ 1,000 records/season. Vectorize handles 10M,
so this is 0.0001% of capacity.

**Searchable queries we unlock immediately:**

- "any day we had good chumming on the south-east grounds" (semantic)
- "what happened within 50 km of Cape Edgecumbe last June" (spatial)
- "every catch log from July 2026" (timeline+category)
- "any briefing that mentioned whales or bait balls" (semantic)
- "show me every day the tide change correlated with the fish marks" (semantic across D1 events)

---

## Integration paths (three options, ranked)

### Option A — Self-hosted ship-log-search companion (RECOMMENDED for Eileen's setup)

**Why:** Eileen is offline-first (Starlink, fishing grounds outside cell
range). Running ship-log-search in a Docker container on the boat's nav
computer means semantic search works in-port, at anchor, and underway with no
cloud dependency. The D1 database becomes a tiny SQLite file we can
trivially back up alongside the rest of `tzpro-agent`.

**Implementation:** Add a `companion/` subdirectory to tzpro-agent:

```
companion/
├── docker-compose.yml        # ship-log-search + a thin Caddy reverse proxy
├── .env.example              # LOG_KEY=...
├── bridge.py                 # watches cascade_out/ for new H1/D1, POSTs to /api/ingest
├── test_bridge.py
└── README.md
```

The `bridge.py` is ~80 lines: `watchdog` observer on `cascade_out/briefings/`,
parses H1 MD and D1 JSON, derives `category` from filename or content,
POSTs to `http://localhost:8787/api/ingest` (the companion Worker's port).

**Search UI:** Already shipped by ship-log-search — single HTML page with
semantic + spatial + timeline search. Point Eileen's phone/tablet at
`http://nav-pc:8787/` and we have a real semantic logbook.

**Backup:** The companion's SQLite DB lives in a Docker volume; backup is
`docker exec sqlite3 .dump > backup.sql`. Already aligned with our R2 cloud
backup strategy in `scripts/`.

**Cost:** $0. Hardware: ~250 MB RAM for the Worker container, ~50 MB for the
SQLite file.

**Status of upstream Docker support:** Already shipped in `self-host/`. We
just need to wire it.

### Option B — Cloud-deployed ship-log-search (good fallback for non-vessel use)

**Why:** If we want to share Eileen's logbook with the broader SuperInstance
fleet (or another boat), Cloudflare free tier is fine. ~1% utilization.

**Implementation:** Fork `SuperInstance/ship-log-search`, add an
`api/ingest` key just for tzpro-agent. Deploy via `wrangler deploy`. Add the
Worker URL + key to tzpro-agent's `secrets.toml` (or env vars on the boat).
The `bridge.py` is the same — just points at a Cloudflare URL instead of
localhost.

**Cost:** $0 (well under free tier).

### Option C — Local sentence-transformers, no external service

**Why:** If we want zero external dependencies. `bge-small-en-v1.5` is 384
dim and runs at ~2000 sentences/sec on an RTX 4050 in FP16. Embedding all
season records takes seconds.

**Implementation:** Pull the model via `pip install sentence-transformers`
then `SentenceTransformer('BAAI/bge-small-en-v1.5')`. Compute embeddings
locally on the H1/D1 cycle. Store vectors in a tiny SQLite extension or
FAISS index alongside the existing twin. Search is cosine similarity +
text SQL filter — pure stdlib Python, no Workers, no Docker.

**Why this is third-choice:** It duplicates the production-quality code in
ship-log-search (D1 schema, CORS, error handling, P0 fixes, embedded UI) for
marginal benefit. Only pursue if Options A and B are blocked.

---

## What tzpro-agent's panel/ web app could learn from ship-log-search's UI

The 3-panel web app at `:8081` already covers M1 logs, M10 records, and
H1+D1 briefings. Three concrete UI patterns ship-log-search has that we
should adopt:

1. **WAI-ARIA tab navigation with arrow-key support.** Our current panel
   uses a day picker but no proper tabs. Easy port.
2. **Filter chips with individual removal.** Our panel renders static
   records. Search-as-you-type with filter chips would let the captain
   narrow "M10 records mentioning halibut" without leaving the page.
3. **Score badge + gradient bar on semantic results.** When we surface
   ship-log-search hits inside panel 3, the percent-match badge from
   ship-log-search (`<span class="score-badge">73% match</span>`) is the
   right visualization — we already banned raw confidence percentages from
   captain-facing text (docs/23 R1), but the score-badge format is the
   calibrated-language exception.

We should not copy verbatim — the dark theme is similar but not identical.
The CSS variables in ship-log-search (`--bg: #050b13`, `--accent: #5ab8e8`)
are close enough to ours that a 30-line port would harmonize them.

---

## What we should NOT take from these repos

- **No need to adopt D1 ourselves.** tzpro-agent's `twin/` is a SQLite file
  that already plays the role D1 would. Migrating to D1 means a cloud
  dependency for the on-boat system of record, which violates the
  offline-first doctrine (docs/17).
- **No need to adopt Workers AI directly.** Our ollama pipeline handles M1,
  M10, H1, D1 inference. Pulling `bge-small-en-v1.5` via ollama is a stretch
  (Workers AI is the Cloudflare-tuned version). Use `sentence-transformers`
  if we go local-embed, not ollama.
- **Don't fork the Worker into our repo.** It's already deployed-able as-is.
  Vendor it as a git submodule or pin a release commit.

---

## Recommended action sequence

1. **Today (low risk, high payoff):** Add `companion/` skeleton to
   tzpro-agent. Defer actual deploy until crew is back aboard.
2. **When moored with reliable power:** Pull `docker-compose.yml` from
   ship-log-search's `self-host/`, run it on the nav PC, verify
   `curl localhost:8787/health` returns OK.
3. **Next fishing day:** Wire `companion/bridge.py` to ingest H1 + D1
   outputs. Confirm records appear via the ship-log-search UI at
   `http://nav-pc:8787/`.
4. **Stretch:** Pull `bge-small-en-v1.5` to ollama as a backup embed model
   (offline semantic search if the companion is down).
5. **Fleet phase:** If/when there's a second boat, swap the single-vessel
   self-host for the Cloudflare-deploy variant with `vessel_id` in metadata.

---

## Open questions for the operator

1. Is `localhost:8787` (or any free port) acceptable as the in-port
   semantic search endpoint? Or do we want it on the existing `:8081`
   panel port with a sub-route?
2. Are we OK adding `sentence-transformers` (~250 MB pip install) as a
   dependency for the offline-embed stretch goal, or do we want to keep
   the Python environment lean?
3. The current `panel/` UI is single-day. Should we keep ship-log-search
   as a *separate* URL (different design language, different intent), or
   unify them under one navbar?

These don't block the implementation but they shape what gets built first.

---

*Filed under docs/research/ for the next in-agent to find. Not committed
yet — see companion commit when implementation starts.*