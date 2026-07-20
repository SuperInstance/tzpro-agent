# twin — Local Data Twin

SQLite-based local storage for time-synced vessel data. Content-addressed blob storage with two-phase GC, tombstone semantics, and cascade perception loop integration.

## Disk Layout

```
memory/
├── meta.db              # SQLite (WAL mode, FK=ON)
├── blobs/               # Content-addressed PNGs: <xx>/<yy>/<sha256>.png
├── manifests/           # Per-day verification units
├── exports/             # Parquet exports
└── gc/
    └── pending.json     # Staged GC candidates (24h grace)
```

## Schema Summary

- **frames** — frame_id (PK), ts_utc, lat/lon/sog/cog, sha256→blobs, tier, cadence, novelty, keep_reason, display_geom
- **blobs** — sha256 (PK), path, bytes, tier, created
- **echogram_records** — frame_id→frames, ts_utc, depth_top_m/bot_m, record_json, vocab_terms, model, confidence
- **notes** — note_id (PK), ts_utc, frame_id→frames, body, novelty, retained
- **briefings** — briefing_id (PK), ts_utc, period_start/end, body, body_sha256, model
- **labels** — (frame_id, label, labeler) PK, ts_utc, provenance

## Quick Start

```python
from pathlib import Path
from twin import Twin

# Open/create twin
twin = Twin(Path("memory"))
twin.open()

# Add frame (PNG + metadata)
result = twin.add_frame(
    png_path=Path("capture.png"),
    sidecar={"ts_utc": 1721400000000, "lat": 45.5, "lon": -122.5, "sog": 5.2, "cog": 180.0},
    cadence="10min-canonical"
)
print(result.frame_id, result.sha256, result.is_new)

# Attach echogram record
twin.add_record(result.frame_id, {
    "depth_top_m": 15.0, "depth_bot_m": 45.0,
    "vocab_terms": "fish school", "model": "claude-3", "confidence": 0.92
})

# Query frames since timestamp
for row in twin.frames_since(1721400000000):
    print(row["frame_id"], row["lat"], row["lon"])
```

## GC & Tombstones

- **Never delete rows** — GC sets `tier='gone'` (tombstone)
- Two-phase: stage in `gc/pending.json` → 24h grace → delete blob file
- Grace deletion requires: `final_read_flag=True` AND `verified_copies >= required_copies`
- Protected from GC: `keep_reason` IS NOT NULL, has labels, tier != 'hot'

```python
from twin.gc import GCScheduler

scheduler = GCScheduler(twin, required_copies=1)
staged = scheduler.stage_candidates(tier="hot")  # Find eligible frames
result = scheduler.finalize_grace_period(final_read_flag=True, verified_copies=1)
```

## Cascade Integration

Cascade loops write to the twin via `cascade/twin_sink.py`:

```python
import cascade.twin_sink as sink

frame_id = sink.add_frame(png_path, sidecar)  # Returns None if twin down
sink.add_note({"body": "...", "frame_id": frame_id, "novelty": 0.9})
sink.add_record({"frame_id": frame_id, "depth_top_m": 20.0, ...})
sink.add_briefing(body_md="# Fishing Report", model="claude-3")
```

**Non-fatal contract**: If twin is unavailable, cascade continues with file outputs only.

## Running Tests

```bash
# Unit tests
python -m unittest twin.test_twin -v

# Integration tests (cascade→twin)
python -m unittest twin.test_integration -v

# Importer CLI
python -m twin.importer <captures_dir> <memory_dir>

# GC CLI
python -m twin.gc <memory_dir> [--dry-run]

# Reconcile CLI (startup sweep)
python -m twin.reconcile <memory_dir>
```

## Operational Rules

1. **No row deletions** — Use tombstones (`tier='gone'`)
2. **Atomic writes** — All blob writes use temp + `os.replace`
3. **Provenance required** — Every note/record includes source
4. **Idempotent by SHA256** — Same content returns existing `frame_id`
5. **Reconcile on startup** — Run `twin.reconcile` to cleanup orphan blobs
6. **Degrade gracefully** — If FTS5/RTree missing, twin still works
