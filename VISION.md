# VISION.md — CoCapn Ecosystem: From One Boat to Fleet

**Date:** July 17, 2026
**Current State:** 1 boat (F/V EILEEN), 5 daemons, ~30 captures/day, OpenCV rule-based analysis, 1 species label (chum@35fm)

---

## The Core Insight

Every minute a fisherman spends looking at the sounder is a minute not fishing. The sounder already sees the fish — it just can't tell you *what* they are. That's the gap CoCapn fills: not better sensors, better *interpretation*.

The vocabulary compounds. Today: "unidentified blob at 35 fm." After 10 catch reports: "probable chum at 35 fm (conf 0.73)." After 100: the system identifies chum schools from sonar alone with useful accuracy. This works because:
- Sounders see species-specific patterns (school shape, depth preference, density)
- GPS + catch reports provide ground truth labels
- Bayesian accumulation doesn't require ML; it just works with enough data

---

## The Next 6 Weeks

### Week 1 (July 20-26): Production Hardening
- Fix the rendering bug in the agent runtime
- Add stats endpoint fix (result.count → result.matches.length)
- D1 database on the Worker for proper timeline/spatial queries (Vectorize stays semantic-only)
- Ship the SQLite mirror as is
- Weekly checkpoint: zero known crashes in a 24h test

### Week 2 (July 27-Aug 2): Alerts Live
- Deploy alerts.py daemon (4 rule types)
- Wire to Telegram: the Captain gets a push when vocabulary-matched patterns appear
- "High-confidence chum cluster at 32-36 fm, 15 blobs" → Telegram notification
- Add `/api/alerts` endpoint on the Worker for dashboard badge
- Weekly checkpoint: first production alert sent and acknowledged

### Week 3 (Aug 3-9): Fleet Registration
- Build fleet onboarding: simple CLI `copilot join` that registers a boat's Worker ID
- Each boat gets its own Vectorize namespace or partitioned index
- Fleet-level query: /api/fleet/search?q=chum&region=SEAK&days=7
- Weekly checkpoint: 3 boats can see each other's anonymized data

### Week 4 (Aug 10-16): DAW Dashboard MVP
- Build the echogram time-lapse scrubber
- 24 hours of captures rendered as an animated sequence
- Depth zone overlay + catch report markers
- Speed controls (1x, 2x, 10x) — like scrubbing through a fishing day
- Weekly checkpoint: Captain can watch an entire day's fishing in 2 minutes

### Week 5 (Aug 17-23): Vocabulary Acceleration
- Add synthetic data: known target strength curves per species (chum = -35dB, sockeye = -40dB)
- Transfer learning: if Boat A catches chum at 35 fm and Boat B has similar bottom/bathymetry, Boat B's vocabulary gets a prior
- Model-assisted labeling: Kimi/Claude describes echogram images as text, text feeds the vocabulary
- Weekly checkpoint: 10 species labels minimum in the vocabulary

### Week 6 (Aug 24-30): Public Beta
- Open-source release on GitHub with README, installation script, and 1-hour setup
- Plugin API v1: POST /api/plugin with structured observation
- CoCapn.com landing page with documentation
- Weekly checkpoint: beta signups open, 1 new boat installed remotely

---

## Architecture Decisions for the Road

### Data Flow: 50 Boats
```
Boat → Local SQLite (always-on) → Cloudflare D1 (when connected) → Fleet queries
```
Each boat runs independently. The cloud is a replication target, not a control plane. This is critical for Alaska where internet is intermittent.

**Fleet discovery:** Each boat's Worker has a `/api/fleet/discover` endpoint. When online, boats discover each other's existence via the Worker — no P2P mesh needed.

**Anonymized patterns:** "chum at 35 fm" is shared. "Captain Casey caught 300 chum at 35 fm" is not. The vocabulary is shared; the catch counts are private.

### Edge vs Cloud Split

| Component | Edge (boat) | Cloud (Worker) | Rationale |
|-----------|------------|-----------------|-----------|
| Capture daemon | ✅ | — | 10-min PNG dump, must be local |
| OpenCV analyzer | ✅ | — | 1080p frames, too large to upload |
| SQLite mirror | ✅ | — | Offline resilience, fast queries |
| Alerts | ✅ | — | Must fire without internet |
| Species vocabulary | ✅ shared | ✅ shared | Edge caches, cloud aggregates |
| Semantic search | — | ✅ | Vectorize + Workers AI only in cloud |
| Fleet queries | — | ✅ | Needs cross-boat aggregation |
| Dashboard | — | ✅ | Served from Worker, accessible from phone |
| Model inference | ⏳ future | ⏳ future | OAK-D on edge, fine-tuning in cloud |

### Plugin API (v1 — September 2026)

A plugin is a WebSocket or HTTP endpoint that receives structured observations:

```json
{
  "type": "echogram_blob",
  "spec_version": "1.0",
  "vessel_id": "eileen-001",
  "ts_utc": "2026-08-15T14:30:00Z",
  "lat": 55.78,
  "lon": -131.69,
  "features": {
    "blobs": [{"depth_fm": 35.2, "intensity": 112, "prediction": "chum", "conf": 0.73}],
    "bottom": {"depth_fm": 57.2, "confidence": "high"},
    "thermoclines": [{"depth_fm": 17.6, "confidence": "medium"}]
  },
  "vocabulary": {"chum": {"confidence": 0.73, "reports": 3}}
}
```

Plugins can:
1. Subscribe to capture events (real-time WebSocket)
2. Query historical data (REST)
3. Submit observations (REST POST)
4. Export analysis (CSV/GeoJSON)

### Offline Resilience

The system survives internet loss with these guarantees:
- Captures continue (daemons are local)
- Analysis continues (OpenCV is local)
- Alerts fire (local SQLite is the data source)
- Vocabulary accumulates (local)
- Dashboard is unavailable (Cloudflare Worker)

On reconnect:
- SQLite WAL syncs to D1 via changelog
- Any unsent catch reports POST to Ship Log Search
- Vocabulary merges (edge confidence weighted by local reports, cloud weighted by fleet)

### 12-Month Breakthrough Milestones

**Month 3 (Oct 2026): First transfer-learned prediction**
A boat that caught no chum predicts chum at 35 fm based on fleet patterns. The Captain sees the prediction before making a set. This validates the entire vocabulary-sharing concept.

**Month 6 (Jan 2027): Fleet-level pattern discovery**
"3 boats saw chum at similar depth in the last 72 hours — fish are moving south at 0.8 knots." This is the first fleet-level intelligence that no individual boat could produce.

**Month 12 (Jul 2027): Autonomous chum detection**
An OAK-D camera + on-device model identifies a chum school from the sounder alone, with confidence > 90% across 50+ boats. The vocabulary has passed the human-expert threshold. The system is now a competent fishing partner, not just a log.

---

## What Not to Build

- Don't build a mobile app. The phone is a browser. Progressive Web App covers everything.
- Don't build real-time P2P mesh. It's unnecessary with Cloudflare Workers at 300ms latency.
- Don't build custom hardware. Every boat already has a sounder, GPS, and a laptop.
- Don't train a vision model until you have 10,000+ labeled echogram frames. Until then, rule-based + Bayesian is correct.

---

## The Captain's Directives (from ONBOARDING.md)

> "My decisions are the final word, but everything else is negotiable."
> "Keep the pilot house tone — concise, no filler, info-dense."
> "Never overwrite. Version increment."

These aren't just preferences. They're the architecture. The entire system is additive: new captures don't touch old ones, new vocabulary labels don't overwrite earlier analysis, new boats don't change existing boat data. Everything compounds.

*Written July 17, 2026 — Phase 1-5 operational, Phase 6 vision mapped.*
