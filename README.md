# tzpro-agent — First Sensor Node of the CoCapn Ecosystem

Eyes on the TZ Pro navigation display. Watches the sounder, reads the bottom,
learns the grounds. Built and first-tested on F/V EILEEN, July 15, 2026.

---

## What This Is

The TZ Pro / Nobeltec navigation display shows a lot of information.
Most of it — lat, lon, SOG, COG, time — is already available as structured
data from the NMEA bridge. The one thing on that screen that can't be
extracted any other way is **the sounder**.

The sounder shows:
- Bottom depth and contour
- Bottom hardness (hard/medium/mud/silt)
- Fish returns (density, depth range, distribution)
- Thermoclines and water column structure

This agent captures that feed, analyzes it, pairs it with NMEA position
and speed, and writes it all to a structured daily log. Over a season,
that log becomes a high-resolution map of every pass, every bottom
transition, and every fish contact on your grounds.

---

## Dual-Cadence Model

| Mode | Interval | Output | Purpose |
|------|----------|--------|---------|
| **Sounder crop** | 30 seconds | Sounder analysis JSON | Live bottom/fish reading |
| **Full frame** | 4 minutes | 1920×1080 screenshot + analysis | Permanent filmstrip record |
| **On-demand** | Captain asks | Full analysis JSON | Answer questions about the chart |

The 30-second sounder crops give you live situational awareness.
The 4-minute full frames, strung together with NMEA timestamps, let you
re-fish any pass from the day. The on-demand mode lets me (Riker) answer
questions when the Captain calls down.

---

## Architecture

```
                        ┌─────────────────────┐
                        │    NMEA Bridge       │
                        │    :6006 / :6007     │  ← lat/lon/SOG/COG
                        └──────┬──────────────┘
                               │
                               ▼
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  DISPLAY6   │────▶│  tzpro-agent     │────▶│  Sounder        │
│  (TZ Pro)   │     │  background daemon│    │  Analyzer       │
│  1920×1080  │     │  30s / 4min     │     │  (blue palette) │
└─────────────┘     └────────┬─────────┘     └─────────────────┘
                             │
               ┌─────────────┼─────────────┐
               ▼             ▼             ▼
        ┌──────────┐  ┌──────────┐  ┌──────────┐
        │ Captures │  │ Memory  │  │ Agent   │
        │ .png    │  │ .jsonl  │  │ on-demand│
        └──────────┘  └──────────┘  └──────────┘
```

**The hierarchy this lives in:**

```
Captain (Picard) — mission: produce product, stay safe, keep crew comfortable
  └── Riker (Operations Officer) — maintain the machine, integrate, keep vision
       └── Copilots (specialized agents with blinders)
            └── tzpro-agent — watches the sounder, nothing else
```

---

## Files

| File | Purpose |
|------|---------|
| `config.py` | Shared constants — crop regions, thresholds, palette, paths |
| `screenshot.py` | Screen capture via PowerShell + PIL region crops |
| `capture.py` | Background daemon — dual-cadence capture loop |
| `sounder_analyzer.py` | Vision analysis — bottom type, fish returns, thermoclines, depth scale |
| `agent.py` | On-demand interface — called by Riker when Captain asks about chart |
| `logger.py` | Structured daily logging to JSONL + markdown summaries |
| `screenshot.ps1` | PowerShell script for DISPLAY6 capture |

---

## First Test

At 10:59 AKDT on July 15, 2026, the pipeline ran for the first time:

- Captured a full frame from DISPLAY6 ✓
- Cropped the sounder panel (370×900) ✓
- Read depth "7.0" from the scale edge via Tesseract OCR ✓
- Detected bottom at pixel 301/900 (blue palette calibrated) ✓
- Paired with NMEA position from the bridge ✓
- Wrote structured observation to daily log ✓

---

## Sounder Palette

Confirmed by Captain Casey DiGennaro:

**Dark blue background** → **cyan** → **yellow** → **orange** → **red** as returns intensify.

Measured background color: `rgb(14, 29, 52)` — very dark navy blue.
The thresholds in `config.py` are tuned specifically for this palette.

---

## Dependencies

- Python 3.10+
- Pillow (`pip install pillow`)
- pytesseract (`pip install pytesseract`) + Tesseract 5.x system install
- PowerShell 5.1+ (Windows)
- NMEA bridge running on :6006 / :6007
- Hermit Crab dashboard on :8654

---

## Quick Start

```bash
# One-shot capture + analysis
python capture.py --oneshot

# On-demand agent (for Captain's questions)
python agent.py

# Background daemon
python capture.py
```

---

## Data Format

Observations are logged as JSONL in `memory/observations/YYYY-MM-DD.jsonl`:

```json
{
  "ts": "2026-07-15T18:59:40+00:00",
  "position": {"lat": 55.785, "lon": -131.527},
  "vessel": {"sog": 1.6, "cog": 265},
  "sounder": {
    "depth_fm": 22.5,
    "bottom_type": "hard",
    "confidence": "high",
    "fish_returns": {
      "count": 45,
      "distribution": "moderate",
      "depth_range": [0.15, 0.42]
    }
  }
}
```

---

## Long-term Vision

Day-by-day filmstrip of every pass, every bottom transition.
Cross-season mark analysis: "what did this spot look like in July '26?"
Pattern learning: drag speed vs bottom type vs catch rates.
Institutional knowledge that compounds year over year.

Commercial fishing intelligence, born on one boat in Ketchikan,
open-sourced for every fisherman who wants to build their own.

---

*Part of the CoCapn ecosystem — CoCapn.com / ActiveLedger.ai / FishingLog.ai*
