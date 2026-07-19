"""cascade/gaze.py — the downward attention channel (docs/17).

Any tier may steer the racehorses' blinders. Priority: human > H1 > M10.
Expired directives vanish. One file, atomic writes, that's the contract.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import config

_PRIORITY = {"human": 3, "H1": 2, "M10": 1}


def _read_raw() -> dict | None:
    try:
        return json.loads(config.GAZE_FILE.read_text())
    except Exception:
        return None


def current() -> dict | None:
    """The live gaze directive, or None if unset/expired."""
    g = _read_raw()
    if not g:
        return None
    if time.time() > g.get("ts_epoch", 0) + g.get("ttl_s", 3600):
        return None
    return g


def set_gaze(focus: str, set_by: str = "human", ttl_s: int = 3600) -> dict:
    """Write a directive. Lower priority never overrides higher live priority."""
    existing = current()
    if existing and _PRIORITY.get(existing.get("set_by"), 0) > _PRIORITY.get(set_by, 0):
        return existing  # refuse quietly — higher authority holds the gaze
    g = {
        "focus": focus,
        "set_by": set_by,
        "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ts_epoch": time.time(),
        "ttl_s": ttl_s,
    }
    tmp = config.GAZE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(g, indent=2))
    tmp.replace(config.GAZE_FILE)  # atomic
    return g


def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Read or set the perception gaze")
    p.add_argument("--set", dest="focus", help="focus directive text")
    p.add_argument("--by", default="human", choices=["human", "H1", "M10"])
    p.add_argument("--ttl", type=int, default=3600)
    a = p.parse_args()
    config.ensure_dirs()
    if a.focus:
        print(json.dumps(set_gaze(a.focus, a.by, a.ttl), indent=2))
    else:
        print(json.dumps(current(), indent=2))


if __name__ == "__main__":
    main()
