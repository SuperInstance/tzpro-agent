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
    Uses Ollama's chat API to process observations through qwen3:4b.
    Maintains a rolling context window of recent observations for pattern detection.
    Archives monologue entries to JSONL for later review.

Usage:
    python monologue.py                    # Background loop
    python monologue.py --oneshot          # Single observation, print monologue
    python monologue.py --loop N           # Run N monologue cycles, print summary
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

import urllib.error
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
OLLAMA_TIMEOUT = 120  # seconds to wait for Ollama response


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
    """Send a prompt to Ollama and return the response text.

    Uses the generate API with raw=True to bypass the model's thinking
    template (qwen3 defaults to thinking mode in the chat template).
    Response is trimmed to the first meaningful sentence. Retries once
    on transient errors.
    """
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "raw": True,
        "stream": False,
        "options": {
            "temperature": 0.5,
            "num_predict": 100,
        },
    }).encode()

    for attempt in (1, 2):
        try:
            req = urllib.request.Request(
                OLLAMA_URL,
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
                result = json.loads(resp.read().decode())
                response = result.get("response", "").strip()

                if response:
                    # Strip special tokens
                    response = (
                        response.replace("<|im_start|>", "")
                        .replace("<|im_end|>", "")
                        .replace("<think>", "")
                        .replace("</think>", "")
                        .strip()
                    )
                    # Remove leading/trailing quotes and whitespace the model sometimes echoes
                    response = response.strip().strip('\" \'\n\t')
                    # If the model starts meta-commentary (double newline after response),
                    # take only up to that point.
                    if "\n\n" in response:
                        response = response.split("\n\n")[0]
                    # Ensure we end with sentence-ending punctuation
                    if response and response[-1] not in (".", "!", "?"):
                        # Find a good sentence break
                        for delim in (". ", "! ", "? "):
                            idx = response.find(delim)
                            if idx > 0:
                                response = response[: idx + 1]
                                break
                    return response.strip()

                if attempt == 1:
                    log.debug("Ollama returned empty response, retrying...")
                    continue
                log.warning("Ollama returned empty after retry")
                return ""

        except urllib.error.URLError as e:
            if attempt == 1:
                log.debug("Ollama transient error (attempt 1/2): %s", e)
                time.sleep(5)
                continue
            log.warning("Ollama unreachable after 2 attempts: %s", e)
            return ""
        except json.JSONDecodeError as e:
            if attempt == 1:
                log.debug("Ollama bad response (attempt 1/2): %s", e)
                continue
            log.warning("Ollama bad JSON after retry: %s", e)
            return ""
        except Exception as e:
            if attempt == 1:
                log.debug("Ollama error (attempt 1/2): %s", e)
                time.sleep(5)
                continue
            log.warning("Ollama failed after 2 attempts: %s", e)
            return ""

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
    
    prompt = (
        f"F/V EILEEN at {position.get('lat', '?')}N {position.get('lon', '?')}W, "
        f"depth {current.get('depth_fm', '?'):.0f}fm, "
        f"gear clearance {current.get('clearance', '?'):.0f}fm, "
        f"forward {profile_summary}, "
        f"{current.get('anomaly_count', 0)} anomalies logged."
    )
    if alerts:
        prompt += f" Alert: {alerts[0].get('message', '')}"

    prompt += "\nOne-sentence ship's officer monologue note:"
    
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


def loop_mode(count: int):
    """Run N monologue cycles back-to-back, logging each and printing a summary."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    
    results = []
    for i in range(1, count + 1):
        log.info("Cycle %d/%d — reading sensors...", i, count)
        sensors = read_sensors()
        
        if "error" in sensors:
            log.warning("Cycle %d: sensor error: %s", i, sensors["error"])
            results.append({"cycle": i, "success": False, "error": sensors["error"]})
            continue
        
        entry = think(sensors)
        if entry:
            archive(entry)
            results.append({
                "cycle": i,
                "success": True,
                "category": entry.category,
                "text": entry.text,
                "ts": entry.ts,
            })
            icon = {"alert": "🚨", "change": "🔄", "steady_state": "✅", "curiosity": "🤔"}.get(entry.category, "🧠")
            log.info("%s [%s] %s", icon, entry.category, entry.text)
        else:
            log.warning("Cycle %d: no monologue generated (model silent)", i)
            results.append({"cycle": i, "success": False, "error": "no monologue generated"})
        
        if i < count:
            time.sleep(POLL_INTERVAL)
    
    # ── Summary ────────────────────────────────────────
    successes = [r for r in results if r.get("success")]
    failures = [r for r in results if not r.get("success")]
    
    print()
    print("=" * 56)
    print("  MONOLOGUE LOOP SUMMARY")
    print("=" * 56)
    print(f"  Cycles run:    {count}")
    print(f"  Successful:    {len(successes)}")
    print(f"  Failures:      {len(failures)}")
    print()
    if successes:
        categories = {}
        for r in successes:
            cat = r.get("category", "unknown")
            categories[cat] = categories.get(cat, 0) + 1
        print(f"  Categories:    {categories}")
        print()
        print("  Entries:")
        for r in successes:
            print(f"    [{r['ts'][:19]}] [{r['category']}] {r['text']}")
    if failures:
        print()
        print("  Failures:")
        for r in failures:
            print(f"    Cycle {r['cycle']}: {r.get('error', 'unknown')}")
    print()


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
    elif "--loop" in sys.argv:
        count = 3  # default
        for i, a in enumerate(sys.argv):
            if a == "--loop" and i + 1 < len(sys.argv):
                try:
                    count = int(sys.argv[i + 1])
                except ValueError:
                    pass
        loop_mode(count)
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
