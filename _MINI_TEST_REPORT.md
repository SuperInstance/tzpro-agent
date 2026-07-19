# Mini-Agent Test Report

**Generated:** 2026-07-18 18:16:33 ADT
**Workspace:** `C:\Users\casey\.openclaw\workspace\tzpro-agent`

---

## Summary

| # | Test | Result |
|---|------|--------|
| 1 | `python tests/run_canary.py` | ✅ PASS |
| 2 | `python holdfast.py test` | ✅ PASS |
| 3 | `python stipes.py test` | ✅ PASS |
| 4 | `python tide_pool.py test` | ✅ PASS |
| 5 | `python memory_bridge.py tick` | ✅ PASS |
| 6 | `python hermit_vessel.py --status` | ✅ PASS |

**Overall:** 6/6 suites passing ✅

---

## 1. `tests/run_canary.py` — ✅ PASS

Ran three canary test groups covering conservation layer, routing, and fleet monitoring.

### `conservation_layer.py`
- ✅ imports OK
- ✅ `ActionBudget`: consume + productive/waste tracking
- ✅ `ActionBudgetExceeded` raised correctly
- ✅ `ActionBudget`: to_dict/from_dict roundtrip
- ✅ `SplitTrigger.should_split()` (146 chars)
- ✅ `SplitTrigger.forget()`: pruned 4, survived 6
- ✅ `ConservationState`: remaining=92.0
- ✅ `SpectralLaplacian`: gap=0.5000, Fiedler=1.0000
- ✅ `EventLog`: write/read/events_by_type/clear
- ✅ CLI: status (V=0, C=10000.00, no split needed)
- ✅ CLI: gc (no split needed, waste ratio OK at 0.00)

### `_router.py`
- ✅ imports OK
- ✅ `route_task`: exact match → seed2
- ✅ `route_task`: unknown fallback → flash
- ✅ `route_task`: context hints override
- ✅ `acquire_lock`: first attempt succeeds
- ✅ `acquire_lock`: second attempt correctly denied (lock held)
- ✅ `list_active_locks`: 1 lock(s)
- ✅ `release_lock`: released
- ✅ `wait_for_release`: completed

### `fleet_monitor.py`
- ✅ imports OK
- ✅ `check()`: 4 UP, 0 DOWN (4 services total)
- ✅ report keys correct
- ✅ `report()`: 325 chars, markdown format

**Result:** `ALL CANARY TESTS PASSED`

---

## 2. `holdfast.py test` — ✅ PASS

Self-test of the holdfast memory (long-term store / graduation queue).

```
[OK] Fresh holdfast is empty
[OK] 3 entries planted
[OK] recall() returns all 3 entries
[OK] query('boat_spec') returns correct entry
[OK] stats: total=3, kinds=3
[OK] Queue has 2 entries ready for migration
[OK] Graduation complete, holdfast now has 5 entries
[OK] Persistence: save/load roundtrip verified
```

**Result:** `ALL TESTS PASSED`

---

## 3. `stipes.py test` — ✅ PASS

Self-test of the stipes memory layer (mid-term buffer / vitality tracking).

- ✅ (1) Append test entries — 1 capture, 1 concept, 1 haze created
- ✅ (2) List (limit 5) — entries returned with vitality values
- ✅ (3) Stats — `capture: 3, concept: 3, haze: 1`
- ✅ (4) Search('chum') — 3 matching captures
- ✅ (5) Reinforce('capture') 9x — count rose to 27, then pruned to 18 and 9
- ✅ (6) Graduation check — 2 candidates (count ≥ 10, vitality > 0.5)
- ✅ (7) Prune — 0 pruned
- ✅ (8) Age an entry beyond vitality=0 and re-prune — pruned 1 (haze gone); remaining kinds: `['capture', 'concept']`
- ✅ (9) Status — active, 6 entries, avg vitality 1.0, 2 graduation candidates

**Result:** `=== all tests passed ===`

---

## 4. `tide_pool.py test` — ✅ PASS

Self-test of the tide pool graduation/gc pipeline.

```
Graduated kinds: ['capture_analysis', 'feed_haze']
Dropped count:   3
Stipes file:     ...\.stipes_memory.jsonl
Result:          PASS
```

**Result:** `PASS`

---

## 5. `memory_bridge.py tick` — ✅ PASS

Health tick of the memory bridge (tide ↔ stipes ↔ holdfast).

```json
{
  "tide_ok": true,
  "stipes_ok": true,
  "holdfast_ok": true
}
```

All three subsystems healthy.

---

## 6. `hermit_vessel.py --status` — ✅ PASS

Hermit vessel status report.

```json
{
  "vessel": "tzpro-agent",
  "version": "2.0.0",
  "timestamp": "2026-07-19T02:16:29.914926+00:00",
  "hermit_available": true,
  "vessel_config": true,
  "outgoing_bottles": 8,
  "incoming_bottles": 0,
  "captures_db": true,
  "hermit_identity": {
    "name": "hermit",
    "version": "2.0.0-hermit",
    "description": "Fleet cognitive command center — the hermit crab that moves between repos",
    "agent_type": "notebook",
    "formerly_known_as": "a2a-native-notebooklm"
  },
  "hermit_capabilities": [
    "research", "transform", "summarize", "podcast",
    "ai-query", "agent-chat", "i2i-vessel", "fleet-ingest"
  ],
  "capture_stats": {
    "total_captures": 30,
    "captures_today": 2,
    "depth_stats": {"avg_fm": 57.2, "min_fm": 57.2, "max_fm": 57.3},
    "blob_stats": {"avg_per_capture": 494.5, "max_in_capture": 730},
    "bottom_types": {"high": 30}
  }
}
```

**Highlights:**
- Vessel: `tzpro-agent` v2.0.0, hermit available
- 8 outgoing bottles queued, 0 incoming
- 30 captures total, 2 today; avg depth 57.2 fm (deep)
- All 8 hermit capabilities registered

---

## Conclusion

All six test suites pass cleanly. Memory stack (tide → stipes → holdfast) is healthy, conservation layer is at baseline (V=0, no split needed), router and fleet monitor report full UP, and the hermit vessel is operational with all capabilities intact.
