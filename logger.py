#!/usr/bin/env python3
"""logger.py — Daily structured logging for tzpro-agent observations."""

from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

WORKSPACE = Path(__file__).parent.resolve()
MEMORY = WORKSPACE / "memory"
DAILY_LOG = MEMORY / "daily"
OBSERVATIONS = MEMORY / "observations"


def ensure_dirs():
    DAILY_LOG.mkdir(parents=True, exist_ok=True)
    OBSERVATIONS.mkdir(parents=True, exist_ok=True)


def log_observation(obs: dict) -> Path:
    """Append a structured observation to today's log."""
    ensure_dirs()
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_path = OBSERVATIONS / f"{date_str}.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obs, separators=(",", ":"), default=str) + "\n")
    return log_path


def write_daily_summary(header: str = "") -> Path:
    """Write or update today's markdown summary."""
    ensure_dirs()
    date_str = datetime.now().strftime("%Y-%m-%d")
    path = DAILY_LOG / f"{date_str}.md"
    path.write_text(
        f"# TzPro-Agent Daily Log — {date_str}\n\n"
        f"## Observations\n"
        f"{header}\n",
        encoding="utf-8",
    )
    return path


def get_today_observations() -> list:
    """Load all observations from today."""
    ensure_dirs()
    date_str = datetime.now().strftime("%Y-%m-%d")
    path = OBSERVATIONS / f"{date_str}.jsonl"
    if not path.exists():
        return []
    obs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                obs.append(json.loads(line))
    return obs


def summarize_day() -> dict:
    """Generate a summary of today's fishing activity."""
    obs = get_today_observations()
    if not obs:
        return {"date": datetime.now().strftime("%Y-%m-%d"), "observations": 0}
    
    depths = [o.get("sounder", {}).get("bottom_depth") for o in obs if o.get("sounder", {}).get("bottom_depth")]
    bottom_types = [o.get("sounder", {}).get("bottom_type") for o in obs if o.get("sounder", {}).get("bottom_type")]
    fish_detected = sum(1 for o in obs if o.get("sounder", {}).get("fish_returns"))
    
    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "total_observations": len(obs),
        "depth_range": [min(depths), max(depths)] if depths else None,
        "bottom_types": list(set(bottom_types)) if bottom_types else [],
        "fish_detected_count": fish_detected,
        "first_obs": obs[0].get("ts"),
        "last_obs": obs[-1].get("ts"),
    }


if __name__ == "__main__":
    import sys
    if "--summary" in sys.argv:
        print(json.dumps(summarize_day(), indent=2))
    elif "--count" in sys.argv:
        print(f"Today: {len(get_today_observations())} observations")
    else:
        print(f"Today: {len(get_today_observations())} observations")
        summary = summarize_day()
        if summary.get("observations", 1) > 1:
            print(f"Depth range: {summary['depth_range']}")
            print(f"Bottom types: {summary['bottom_types']}")
            print(f"Fish detected: {summary['fish_detected_count']} frames")
