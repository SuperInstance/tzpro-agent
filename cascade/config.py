"""cascade/config.py — paths, models, thresholds. Env-overridable.

Defaults target the live workspace on F/V EILEEN. Everything tunable
lives here — no magic numbers inside the loops.
"""
from __future__ import annotations

import os
from pathlib import Path

# ── Workspace ────────────────────────────────────────────────────────
WORKSPACE = Path(os.environ.get(
    "TZPRO_WORKSPACE",
    r"C:\Users\casey\.openclaw\workspace\tzpro-agent",
))
CAPTURES = WORKSPACE / "captures" / "v3"
OUT = Path(os.environ.get("CASCADE_OUT", str(WORKSPACE / "cascade_out")))

DIR_NOVEL = OUT / "minute_notes" / "novel"   # retained M1 notes
DIR_RECORDS = OUT / "records"                # canonical M10 records
DIR_BRIEFINGS = OUT / "briefings"            # H1 briefings
DIR_LOGS = OUT / "logs"

GAZE_FILE = OUT / "gaze.json"
HEARTBEAT_FILE = OUT / "heartbeat.json"

# ── Models (local Ollama) ────────────────────────────────────────────
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

# M1 racehorse: tiny + fast. moondream recommended (~2GB, true minute-loop
# speed); falls back to the only installed vision model until pulled.
MODEL_M1 = os.environ.get("CASCADE_MODEL_M1", "moondream:latest")
MODEL_M1_FALLBACK = os.environ.get("CASCADE_MODEL_M1_FALLBACK", "gemma4:12b")

# M10 scribe / H1 analyst: medium local vision.
MODEL_M10 = os.environ.get("CASCADE_MODEL_M10", "gemma4:12b")
MODEL_H1 = os.environ.get("CASCADE_MODEL_H1", "gemma4:12b")

# ── Cadence (seconds) ────────────────────────────────────────────────
M1_INTERVAL = int(os.environ.get("CASCADE_M1_INTERVAL", "60"))
M10_INTERVAL = int(os.environ.get("CASCADE_M10_INTERVAL", "600"))
H1_INTERVAL = int(os.environ.get("CASCADE_H1_INTERVAL", "3600"))
HEARTBEAT_INTERVAL = 30

# ── Retention ────────────────────────────────────────────────────────
# Calibration study (docs/research/NOVELTY_CALIBRATION.md): score-only
# retention is broken — novelty scores compress into a 0.6-0.8 noise band.
# The OR-of-three rule keeps 26% on the 2026-07-19 corpus, in the 5-25% band.
NOVELTY_THRESHOLD = float(os.environ.get("CASCADE_NOVELTY_THRESHOLD", "0.85"))
RING_BUFFER_SIZE = 120          # M1 notes kept in memory for the scribe
GC_MINUTE_PNGS = os.environ.get("CASCADE_GC_MINUTE_PNGS", "0") == "1"  # off: keep frames

# OR-of-three retention rule clauses (calibrated 2026-07-19)
RETENTION_DEPTH_RE = r"(approximately|at)\s+\d+\s*(fm|fathoms?|m\b|met[er]+s?)"
RETENTION_DISTINCT_WORDS = ("distinct", "localized", "concentrated", "dense", "sharp", "hard", "sudden")
RETENTION_FEATURE_SET = ("blob school", "bottom hardness change", "thermocline break",
                         "surface noise", "dense schools")

# ── Inference limits ─────────────────────────────────────────────────
M1_MAX_TOKENS = 150             # racehorses wear blinders: short answers
M10_MAX_TOKENS = 600
H1_MAX_TOKENS = 1500
INFER_TIMEOUT_S = int(os.environ.get("CASCADE_INFER_TIMEOUT", "180"))


def ensure_dirs() -> None:
    for d in (DIR_NOVEL, DIR_RECORDS, DIR_BRIEFINGS, DIR_LOGS):
        d.mkdir(parents=True, exist_ok=True)
