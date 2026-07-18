# TZPro-Agent Capture Pipeline Test Report

**Date:** 2026-07-18
**Workspace:** `C:\Users\casey\.openclaw\workspace\tzpro-agent\`
**Pipeline Version:** schema v2 (analyzer) / v3 (capture)

---

## Executive Summary

| Test | Verdict | Key Finding |
|------|---------|-------------|
| Vocabulary Test | ⚠️ WARN | Laplace smoothing inflates confidence to 0.95 with only 1 species in zone |
| Database Inspection | ✅ PASS | 30 captures, 1 catch label, 21,984 blobs — all analyzed |
| Analyzer Dry-Run | ⚠️ WARN | Race conditions on JSON read, no retry logic, hardcoded display layout |
| Alert System Audit | ❌ FAIL | No retry on Ship Log POST, hardcoded 0.7 threshold, stale alert spamming risk |
| Capture_v3 Audit | ⚠️ WARN | Non-atomic writes, hardcoded monitor offset, NMEA parsing fragile |

**Ship-Ready Score: 4/10** — Pipeline functions but has critical reliability gaps for unattended marine deployment.

---

## 1. Vocabulary Test

### Commands Run
```bash
python vocabulary.py summarize
python vocabulary.py lookup 35
```

### Output Analysis
```
vocabulary.py summarize:
  Total labels: 1
  Captures scanned: 1
  Species known: chum
  mid (20-40 fm): chum: 1 report(s), 15 total fish, confidence 0.40

vocabulary.py lookup 35:
  Predictions at 35.0 fm: chum (P=0.95, 1 report(s))
```

### Bayesian Confidence Model — **Laplace Smoothing Issue**

**File:** `vocabulary.py:190-210`

```python
# Current implementation
n_species = max(len(zone_species_keys), 1)  # Always ≥ 1
p = (reports + ALPHA) / (total_reports + ALPHA * n_species)
# With 1 report, 1 species: p = (1+1)/(1+1*1) = 2/2 = 1.0 → clamped to 0.95
```

**Problem:** With only **one species** in a zone, Laplace smoothing (α=1) produces **p=1.0**, clamped to **0.95**. This gives false high confidence from a single catch report.

**Expected behavior:** Confidence should reflect data scarcity. With 1 report of 1 species, true probability is uncertain — Bayesian posterior with uniform prior should be much lower.

### Recommendations

| Priority | File | Line | Fix |
|----------|------|------|-----|
| P1 | `vocabulary.py` | 190-197 | Use **Jeffreys prior** (α=0.5) or add a "dummy" unknown species to denominator when `n_species == 1` |
| P1 | `vocabulary.py` | 197 | Replace `max(len(zone_species_keys), 1)` with `len(zone_species_keys) + 1` (always reserve probability mass for unknown) |
| P2 | `vocabulary.py` | 42-45 | Make confidence thresholds (`CONF_UNIDENTIFIED`, `CONF_POSSIBLE`, `CONF_LIKELY`) configurable |

---

## 2. Database Inspection

### Tables Found
| Table | Rows | Status |
|-------|------|--------|
| `captures` | 30 | ✅ All have `analyzed_at`, schema_version 2-3 |
| `catch_labels` | 1 | ✅ 1 label (chum @ 35 fm, 15 fish) |
| `blobs` | 21,984 | ✅ ~700 blobs/capture |
| `sqlite_sequence` | 2 | Internal |

**Note:** No `analysis` table exists — `db.py` schema doesn't create one. The analyzer embeds analysis in JSON files; SQLite is a mirror of `captures`, `catch_labels`, `blobs` only.

### Analysis Status
- All 30 captures show `analyzed_at` timestamps (2026-07-18T00:18:xxZ)
- First capture (`1240_...`) has `schema_version: 3` (caught label bumped it)
- Remaining 29 have `schema_version: 2`
- **All captures analyzed — no pending work**

---

## 3. Analyzer Dry-Run — `analyzer.py`

### Error Handling Gaps

| Issue | Location | Severity |
|-------|----------|----------|
| **Bare `except Exception: pass`** swallows vocabulary errors | `detect_blobs()`:216-218 | P1 — Silent failures hide vocabulary bugs |
| **No retry on Ship Log POST** | `update_ship_log()`:275-300 | P1 — Network blips lose analysis records |
| **Outer loop catches all exceptions** but continues | `run_forever()`:458-468 | P0 — Good: watcher survives individual failures |
| **No handling of corrupted/incomplete JSON** during concurrent writes | `load_meta()`:340-347 | P2 — Race with `capture_v3.py` |

### Race Conditions

| Scenario | Risk |
|----------|------|
| `capture_v3.py` writing JSON while analyzer reads | **High** — `capture_frame()` writes JSON → MD → Ship Log sequentially (no atomicity). Analyzer's `load_meta()` can read partial JSON. |
| File system cache delay on Windows | **Medium** — `capture_frame()` returns path, analyzer may read before flush |

### Missing Retry Logic
- Ship Log POST: `urllib.request.urlopen()` with 5s timeout, **no retry**
- Vocabulary fetch: no retry on cache miss
- No exponential backoff anywhere

### Hardcoded Display Layout Assumptions

| Constant | Value | Risk if Changed |
|----------|-------|-----------------|
| `LF_X_START` / `LF_X_END` | 8 / 945 | Monitor divider shift breaks LF crop |
| `HF_X_START` / `HF_X_END` | 950 / 1890 | Resolution change breaks HF crop |
| `PX_PER_FM` | 18.0 (1080/60) | Depth range change breaks all zone math |
| `ZONES` dict | Fixed pixel rows | Any layout change invalidates zones |

**File:** `analyzer.py:19-48` — All constants at module top, no config injection.

### Recommendations

| Priority | File | Line | Fix |
|----------|------|------|-----|
| P0 | `analyzer.py` | 216-218 | Replace bare `except` with specific catch + log warning |
| P0 | `analyzer.py` | 275-300 | Add retry with exponential backoff (3 attempts) for Ship Log POST |
| P0 | `analyzer.py` | 340-347 | Add file size/stability check before `json.load()` (wait for file to stop growing) |
| P1 | `analyzer.py` | 19-48 | Move display config to `config.py` or JSON; load dynamically |
| P1 | `analyzer.py` | 340-347 | Use file locking (`portalocker`) or write-temp-rename pattern in capture, reader checks for `.writing` flag |
| P2 | `analyzer.py` | 458-468 | Add circuit breaker — if N consecutive failures, alert and back off |

---

## 4. Alert System Audit — `alerts.py`

### Alert Deduplication — **`_already_sent()` Has Gaps**

**File:** `alerts.py:45-55`

```python
def _already_sent(alert_id: str, state: dict) -> bool:
    entry = state.get(alert_id)
    if entry is None:
        return False
    if entry.get("acknowledged", False):
        return False  # Re-fire after ack
    return True
```

**Issues:**
1. **State saved only on new alerts** (`_save_state()` called only when `triggered` list non-empty). If daemon crashes between alert trigger and state save, alert re-fires on restart (acceptable — at-least-once).
2. **NO_ANALYSIS alert spam risk:** If pipeline is down >15 min, `check_stale_analysis()` fires every 60s daemon cycle. The `trigger_data` includes `age_minutes`, so each check gets a **new alert_id** → no deduplication! The stale alert will **spam continuously**.
3. **Alert ID includes timestamp-derived data** (`trigger_data` has `age_min`, `capture_ts`) — same condition at different times = different IDs.

### Ship Log POST Failure Handling

**File:** `alerts.py:57-85` (`_post_to_ship_log`)

- Single attempt, 5s timeout
- On failure: `log.warning()` only — **alert lost silently**
- Daemon mode: no retry queue, no persistence
- `--dry-run` disables POST entirely (testing only)

### Hardcoded Vocabulary Confidence Threshold

**File:** `alerts.py:28`

```python
VOCAB_CONFIDENCE_MIN = 0.7  # Hardcoded, no config
```

Not exposed to CLI, config file, or environment variable.

### Stale-Detection Timer Survival

**File:** `alerts.py:137-174` (`check_stale_analysis`)

- Uses **file mtime** of newest capture JSON — survives restarts correctly (filesystem is source of truth)
- **BUT**: Alert ID changes every cycle (see deduplication issue above) → **spams on every check**

### Recommendations

| Priority | File | Line | Fix |
|----------|------|------|-----|
| P0 | `alerts.py` | 137-174 | Fix NO_ANALYSIS alert ID to be stable (e.g., hash of `rule_name` + `captures_dir` only, not `age_min`) |
| P0 | `alerts.py` | 57-85 | Add retry queue (persist failed alerts to `.alert_queue.json`, replay on next cycle) |
| P1 | `alerts.py` | 28 | Make `VOCAB_CONFIDENCE_MIN` configurable via `config.py` or env var |
| P1 | `alerts.py` | 45-55 | Persist state **before** posting (write-ahead), or use SQLite for alert state |
| P2 | `alerts.py` | 87-112 | Add `max_age_hours` to dedup — auto-expire old alert IDs to prevent unbounded state growth |

---

## 5. Capture_v3 Audit — `capture_v3.py`

### NMEA Parsing

**File:** `capture_v3.py:55-70` (`parse_nmea_latlon`, `fetch_position`)

```python
def parse_nmea_latlon(nmea_str: str) -> Optional[float]:
    dot_pos = nmea_str.find(".")
    if dot_pos < 3:
        return None
    deg_digits = dot_pos - 2
    deg = int(nmea_str[:deg_digits])
    minutes = float(nmea_str[deg_digits:])
    return deg + minutes / 60.0
```

**Issues:**
| Issue | Impact |
|-------|--------|
| No checksum validation on `$GPGGA`/`$GPRMC` sentences | Corrupted NMEA → wrong position silently |
| Assumes DDMM.MMM format; fails on DDDMM.MMM (lon > 100°) | Low — current area is 131°W, `dot_pos-2` works but fragile |
| Partial sentence in buffer → `split("\r\n")` may yield incomplete lines | `parse_nmea_latlon` returns `None`, handled gracefully |
| No handling of `$GPGLL`, `$GNGGA` (multi-constellation) | Misses valid position if talker ID differs |

**Overall:** Works for clean Raymarine/Standard Horizon output. Fragile on noisy serial.

### File Writing — **Non-Atomic**

**File:** `capture_v3.py:180-210` (JSON), `212-240` (MD)

```python
saved.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
saved.with_suffix(".md").write_text("\n".join(md_lines), encoding="utf-8")
```

**Problems:**
1. **No write-then-rename** — partial writes visible to analyzer
2. **JSON and MD written sequentially** — analyzer may see JSON but not MD (or vice versa)
3. **No fsync** — OS cache may delay persistence; power loss loses data

### Display Offset Hardcoded

**File:** `capture_v3.py:19-24`

```python
DISPLAY_OFFSET_X = 1920
DISPLAY_OFFSET_Y = 0
DISPLAY_WIDTH = 1920
DISPLAY_HEIGHT = 1080
```

**Risks:**
- Monitor reordering in Windows changes display numbering
- Resolution change (e.g., 2560x1440) breaks capture region
- Multi-GPU setups may have different coordinate space
- **No auto-detection** of TZ Pro window position

### Recommendations

| Priority | File | Line | Fix |
|----------|------|------|-----|
| P0 | `capture_v3.py` | 180-240 | **Atomic writes**: write to `.tmp`, `os.replace()` to final; write both files before returning |
| P0 | `capture_v3.py` | 55-70 | Add NMEA checksum validation (`*XX` suffix) |
| P1 | `capture_v3.py` | 19-24 | Make display config discoverable: enum monitors via `screeninfo` or config file |
| P1 | `capture_v3.py` | 100-130 | Add file lock (`.lock`) during write so analyzer can wait |
| P2 | `capture_v3.py` | 55-70 | Support multiple talker IDs (`GP`, `GN`, `GL`, `GA`) |

---

## Consolidated Priority Fix List

### P0 — Must Fix Before Unattended Deployment

| # | File | Line | Issue | Fix |
|---|------|------|-------|-----|
| 1 | `alerts.py` | 137-174 | NO_ANALYSIS spams every 60s | Stable alert ID for stale check |
| 2 | `alerts.py` | 57-85 | Ship Log POST failures lost | Retry queue with persistence |
| 3 | `capture_v3.py` | 180-240 | Non-atomic JSON/MD writes | Write-temp-rename + file lock |
| 4 | `analyzer.py` | 216-218 | Bare except swallows vocab errors | Specific exception + log |
| 5 | `analyzer.py` | 275-300 | No retry on Ship Log POST | 3× exponential backoff |
| 6 | `analyzer.py` | 340-347 | Race reading partial JSON | File stability check / lock |

### P1 — Strongly Recommended

| # | File | Line | Issue | Fix |
|---|------|------|-------|-----|
| 7 | `vocabulary.py` | 190-197 | Laplace inflates single-species confidence | Jeffreys prior or +1 unknown species |
| 8 | `vocabulary.py` | 42-45 | Hardcoded confidence thresholds | Configurable via config.py |
| 9 | `alerts.py` | 28 | Hardcoded `VOCAB_CONFIDENCE_MIN=0.7` | Configurable |
| 10 | `analyzer.py` | 19-48 | Hardcoded display crop coords | Load from config / detect dynamically |
| 11 | `capture_v3.py` | 19-24 | Hardcoded monitor offset | Auto-detect or config |
| 12 | `capture_v3.py` | 55-70 | NMEA parsing lacks checksum | Validate `*XX` suffix |

### P2 — Nice to Have

| # | File | Line | Issue | Fix |
|---|------|------|-------|-----|
| 13 | `alerts.py` | 45-55 | Alert state unbounded growth | TTL-based cleanup |
| 14 | `analyzer.py` | 458-468 | No circuit breaker on repeated failures | Back off + alert after N failures |
| 15 | `capture_v3.py` | 100-130 | No coordination between capture/analyzer | File lock protocol |

---

## Ship-Ready Score Breakdown

| Criterion | Score (1-10) | Notes |
|-----------|--------------|-------|
| **Reliability** | 3 | Race conditions, no retries, non-atomic writes |
| **Observability** | 6 | Good logging, Ship Log integration, but alert spam |
| **Configurability** | 2 | Almost everything hardcoded |
| **Data Integrity** | 4 | No write atomicity, no NMEA checksum |
| **Recoverability** | 5 | Watcher survives crashes, but alert state fragile |
| **Marine Hardening** | 3 | No watchdog, no power-loss safety, hardcoded display |

**Overall: 4/10** — Functional in lab, **not ready for unattended vessel deployment**.

### Minimum Viable Ship-Ready (Target: 7/10)
Complete all **P0** fixes + P0 config externalization. Estimated 8-12 hours focused work.

---

## Test Artifacts

- `inspect_db.py` — Database inspection script (created during test)
- `.vocabulary_cache.json` — Vocabulary state (1 label, 1 species)
- `.alert_state.json` — Alert dedup state (1 VOCABULARY_MATCH entry)