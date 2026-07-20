# TZPro Day Scrubber

Local HTTP server for replaying fishing days with the tzpro-agent data twin.

## Running

```bash
# From the tzpro-agent repo root
python -m scrubber.serve

# Custom port/workspace
python -m scrubber.serve --port 9000 --workspace /path/to/workspace

# Then open http://127.0.0.1:8080
```

## Endpoints

### GET /api/day/<YYYY-MM-DD>

Get all frames and records for a day.

**Response (<300ms):**
```json
{
  "frames": [
    {
      "frame_id": "string",
      "ts_utc": 1234567890000,
      "lat": 55.123,
      "lon": -131.456,
      "sog": 2.1,
      "cog": 45.0,
      "sha256": "abcd...",
      "tier": "hot",
      "novelty": 0.85,
      "keep_reason": null
    }
  ],
  "records": [
    {
      "frame_id": "string",
      "record_json": "{\"schools\":[{\"depth_fm\":26}],\"bottom\":{\"depth_fm\":50}}",
      "confidence": 0.91,
      "ts_utc": 1234567890000,
      "lat": 55.123,
      "lon": -131.456
    }
  ]
}
```

### GET /api/day/<date>/highlight

Get the "holy shit" cursor: highest-novelty frame joined to a confident record.

**Response:**
```json
{
  "frame_id": "string",
  "ts_utc": 1234567890000,
  "lat": 55.123,
  "lon": -131.456,
  "sha256": "abcd...",
  "novelty": 0.95,
  "caption": "school at 26 fm, bottom at 50 fm, 91% conf"
}
```

On first load, the UI lands on this moment with a caption at the top.

### GET /api/blob/<sha256>

Get the PNG echogram image.

**Response:** `image/png` bytes from `memory/blobs/<sha[:2]>/<sha[2:4]>/<sha>.png`

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `←` / `→` | Step frame backward/forward |
| `Shift` + `←` / `→` | Step 10 minutes |
| `Space` | Play/pause |
| `[` / `]` | Previous/next event |
| `1` / `2` / `3` | Playback speed (1×, 2×, 10×) |
| `H` | Jump to highlight |

## UI Layout

```
┌──────────────────────────────────────────────────────────────────┐
│  ◀ Mon 19 Jul   14:30:12   55°47.6′N 131°40.1′W   2.1 kt   ⏯ ⏪⏩  │  ← HUD bar (48 px)
├──────────────────────────────────────────────────────────────────┤
│            ╭────────── ECHOGRAM PNG @ cursor ──────────╮         │
│            │  ░▒▓ school 26–27 fm ▓▒░  (overlay on)     │         │  ← Frame pane (~60%):
│            │       · · · cyan GPS track · · ·           │         │    70% grayscale,
│            ╰────────────────────────────────────────────╯         │    analysis overlay
│  [overlay ▓▓▓▓▓░░░]  [track ▓▓▓▓▓▓░░]   Minimal|Standard|Detailed │  ← big sliders + preset chips
├──────────────────────────────────────────────────────────────────┤
│ ▕━━━━━━━━━━━━━━━╋━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━▏           │  ← Timeline (bottom third):
│   06:00        ▲14:30        18:00    │tick marks: records,       │    drag-to-scrub,
│                cursor                 schools, catches, novelties │    variable-rate drag
└──────────────────────────────────────────────────────────────────┘
```

## Variable-Rate Drag

Drag along the timeline to scrub. Drag your finger/cursor **downward** to switch to progressively finer rates:

- 12h → 1h → 10min → frame

This single gesture covers both 12-hour sweeps and frame-precise landing. The playback speed buttons (1×, 2×, 10×) are **only for unattended playback**.

## Architecture

- `scrubber/serve.py` — stdlib-only HTTP server
- `scrubber/static/index.html` — single-file vanilla JS+CSS app
- Reads from `<workspace>/memory/meta.db` (default: `C:\Users\casey\.openclaw\workspace\tzpro-agent`)
- No external dependencies, no build step

## Design Principles

From `boat-agent/docs/22_SCRUBBER_DESIGN.md` and `docs/23_UX_DEEP_RESEARCH.md`:

- **≥64px primary targets** for touch (≥48px floor)
- **High-contrast sun-readable** styling (dark background, fat strokes, ≥18px text)
- **Keyboard fallback** for wet-screen days
- **Provenance-separated event tracks** (machine vs human marks)
- **No jog-wheel UI** (strongest negative result in research)
- **State survives restart** (localStorage)
