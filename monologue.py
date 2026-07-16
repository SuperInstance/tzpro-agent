#!/usr/bin/env python3
"""
monologue.py — The boat's internal monologue.

An always-on awareness layer that reads the latest observations, processes them
through a local LLM (via Ollama), generates structured observations, and archives
them as a continuous timeline.

The monologue is the boat thinking to itself. Most of what it produces is noise —
"depth stable, nothing to report" — but the moments when it breaks that silence
are the moments worth surfacing to the Captain.

Design:
    Runs as a background loop alongside agent_loop.py.
    Uses Ollama's API to process observations through qwen3:4b.
    Maintains a rolling context window of recent observations for pattern detection.
    Archives monologue entries to JSONL for later review.

Usage:
    python monologue.py                    # Background loop
    python monologue.py --oneshot          # Single observation, print monologue
    python monologue.py --review           # Review last 24h of monologue
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import urllib.request

# Local
from config import WORKSPACE, NMEA_VESSEL_URL
from contour_query import get_depth_fm, get_gear_clearance
from forward_look import predict_ahead
from anomaly_logger import log_anomaly, stats as anomaly_stats

log = logging.getLogger("tzpro.monologue")

# ── Paths ──────────────────────────────────────────────────────────
MONOLOGUE_DIR = WORKSPACE / "memory" / "monologue"
MONOLOGUE_DIR.mkdir(parents=True, exist_ok=True)
CONTEXT_FILE = MONOLOGUE_DIR / "context.json"

# ── Ollama Config ──────────────────────────────────────────────────
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
MONOLOGUE_MODEL = "qwen3:4b"  # always-on, CPU-friendly
DEEP_MODEL = "qwen3:8b"       # swapped in when GPU is available

# ── Monologue Config ───────────────────────────────────────────────
POLL_INTERVAL = 60  # seconds between monologue cycles
CONTEXT_WINDOW = 20  # number of recent observations to keep in context


class MonologueEntry:
    """A single monologue observation — what the boat noticed."""
    
    def __init__(self, text: str, observation: dict, model: str):
        self.ts = datetime.now(timezone.utc).isoformat()
        self.text = text
        self.observation = observation
        self.model = model
        self.category = self._classify(text)
    
    @staticmethod
    def _classify(text: str) -> str:
        """Classify monologue entry by content."""
        text_lower = text.lower()
        if any(w in text_lower for w in ["alert", "warning", "hazard", "grounding", "critical"]):
            return "alert"
        elif any(w in text_lower for w in ["change", "transition", "shift", "different"]):
            return "change"
        elif any(w in text_lower for w in ["stable", "normal", "clear", "nothing"]):
            return "steady_state"
        elif any(w in text_lower for w in ["question", "what", "why", "how", "interesting"]):
            return "curiosity"
        else:
            return "observation"
    
    def to_dict(self) -> dict:
        return {
            "ts": self.ts,
            "text": self.text,
            "category": self.category,
            "model": self.model,
            "observation_summary": {
                "depth_fm": self.observation.get("depth_fm"),
                "gear_clearance": self.observation.get("gear_clearance"),
                "alert_count": len(self.observation.get("alerts", [])),
            },
        }
    
    def __repr__(self) -> str:
        return f"[{self.category}] {self.text[:80]}"


def _ollama_generate(prompt: str, model: str = MONOLOGUE_MODEL) -> str:
    """Send a prompt to Ollama and return the response text."""
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.7,
            "max_tokens": 200,
        },
    }).encode()
    
    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode())
            return result.get("response", "").strip()
    except Exception as e:
        log.debug("Ollama: %s", e)
        return ""


def _build_monologue_prompt(current: dict) -> str:
    """Build the prompt for the internal monologue model.
    
    The model receives a structured observation and generates a brief
    natural-language note about what it notices.
    """
    position = current.get("position", {})
    alerts = current.get("alerts", [])
    profile = current.get("profile", [])
    anomaly = current.get("anomaly", {})
    
    # Summarize forward profile
    if profile:
        far = profile[-1]
        near = profile[0]
        trend = "shallowing" if far["depth_fm"] < near["depth_fm"] else "deepening"
        profile_summary = f"{trend} from {near['depth_fm']:.0f}fm to {far['depth_fm']:.0f}fm over {far['distance_m']}m"
    else:
        profile_summary = "no forward data"
    
    prompt = f"""You are the internal monologue of F/V EILEEN. You observe sensor data and generate a brief, natural-language note about what you notice.

Current observation:
- Position: {position.get('lat', '?')}, {position.get('lon', '?')}
- Depth: {current.get('depth_fm', '?')} fm
- Gear clearance: {current.get('clearance', '?')} fm
- Forward profile: {profile_summary}
- Anomalies: {current.get('anomaly_count', 0)} total logged

Alerts ({len(alerts)}):
{chr(10).join(a.get('message', '') for a in alerts[:3])}

Generate ONE short sentence in the voice of a ship's officer noting something useful. Be concise. If nothing notable, say "Nothing needs attention." If something is changing, say what."""
    
    return prompt


def read_sensors() -> dict:
    """Read all available sensor data for the monologue."""
    # Position from NMEA
    try:
        req = urllib.request.Request(NMEA_VESSEL_URL)
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        data = {}
    
    position = {
        "lat": data.get("position", {}).get("lat"),
        "lon": data.get("position", {}).get("lon"),
        "sog": data.get("position", {}).get("sog"),
        "cog": data.get("position", {}).get("cog", 0),
    }
    
    if not position.get("lat"):
        return {"error": "No position"}
    
    # Contour query
    depth = get_depth_fm(position["lat"], position["lon"])
    gear = get_gear_clearance(position["lat"], position["lon"])
    
    # Forward look
    fwd = predict_ahead(
        position["lat"], position["lon"],
        float(position.get("cog", 0) or 0),
        float(position.get("sog", 0) or 0),
    )
    
    # Anomaly stats
    astats = anomaly_stats()
    
    return {
        "position": position,
        "depth_fm": depth,
        "clearance": gear.get("clearance_fm") if isinstance(gear, dict) else None,
        "gear_status": gear.get("status") if isinstance(gear, dict) else None,
        "profile": fwd.get("profile", []),
        "alerts": fwd.get("alerts", []),
        "anomaly_count": astats.get("total", 0),
        "anomaly": {
            "largest_delta": astats.get("largest_negative_fm"),
            "avg_magnitude": astats.get("avg_magnitude_fm"),
        },
    }


def think(sensors: dict) -> Optional[MonologueEntry]:
    """Process one observation cycle through the LLM.
    
    Returns a MonologueEntry if the model responded, None otherwise.
    """
    if "error" in sensors:
        return None
    
    prompt = _build_monologue_prompt(sensors)
    response = _ollama_generate(prompt)
    
    if not response:
        return None
    
    return MonologueEntry(response, sensors, MONOLOGUE_MODEL)


def archive(entry: MonologueEntry) -> None:
    """Write monologue entry to the daily log."""
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_path = MONOLOGUE_DIR / f"{date}.jsonl"
    
    with open(log_path, "a") as f:
        f.write(json.dumps(entry.to_dict()) + "\n")


def load_recent_context(hours: int = 24) -> list[dict]:
    """Load recent monologue entries for context."""
    entries = []
    now = time.time()
    
    for f in sorted(MONOLOGUE_DIR.glob("*.jsonl"), reverse=True):
        with open(f) as fh:
            for line in fh:
                try:
                    entry = json.loads(line)
                    ts = datetime.fromisoformat(entry["ts"])
                    if (now - ts.timestamp()) < hours * 3600:
                        entries.append(entry)
                except (json.JSONDecodeError, ValueError):
                    continue
        if len(entries) >= CONTEXT_WINDOW:
            break
    
    return entries[-CONTEXT_WINDOW:]


def main_loop():
    """Background monologue loop."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    
    log.info("Internal monologue starting — model: %s, interval: %ds",
             MONOLOGUE_MODEL, POLL_INTERVAL)
    
    cycle = 0
    while True:
        cycle += 1
        sensors = read_sensors()
        
        if "error" in sensors:
            log.debug("No sensors — sleeping")
            time.sleep(POLL_INTERVAL)
            continue
        
        entry = think(sensors)
        if entry:
            archive(entry)
            if entry.category in ("alert", "change", "curiosity"):
                log.info("🧠 %s", entry.text)
            elif cycle % 5 == 0:
                log.debug("🧠 %s", entry.text)
        
        time.sleep(POLL_INTERVAL)


def oneshot():
    """Single monologue cycle, print result."""
    sensors = read_sensors()
    if "error" in sensors:
        print(json.dumps({"error": sensors["error"]}))
        return
    
    entry = think(sensors)
    result = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "sensors": {k: v for k, v in sensors.items() if k != "profile"},
        "monologue": entry.to_dict() if entry else None,
    }
    print(json.dumps(result, indent=2, default=str))


def review(hours: int = 24):
    """Print a summary of recent monologue activity."""
    entries = load_recent_context(hours)
    
    if not entries:
        print(f"No monologue entries in the last {hours}h")
        return
    
    categories = {}
    for e in entries:
        cat = e.get("category", "unknown")
        categories[cat] = categories.get(cat, 0) + 1
    
    print(f"=== Monologue Review — Last {hours}h ===")
    print(f"Total entries: {len(entries)}")
    print(f"Categories: {categories}")
    print()
    
    # Show interesting entries
    for e in entries:
        if e.get("category") in ("alert", "change", "curiosity"):
            print(f"  [{e['ts'][:19]}] {e['text']}")
    
    print()
    print(f"Full log: {MONOLOGUE_DIR}")


if __name__ == "__main__":
    import sys
    
    if "--oneshot" in sys.argv:
        oneshot()
    elif "--review" in sys.argv:
        hours = 24
        for i, a in enumerate(sys.argv):
            if a == "--review" and i + 1 < len(sys.argv):
                try:
                    hours = int(sys.argv[i + 1])
                except ValueError:
                    pass
        review(hours)
    else:
        main_loop()
