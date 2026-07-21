"""cascade/roster.py — heartbeat roster for every daemon on the boat.

Extraction of the swarm-anchor pattern (docs/28): each agent writes its
own one-line heartbeat file; the directory IS the roster. No coordinator,
no consensus, inspectable with `cat`. Offline-proof, crash-proof.

Unlike swarm-anchor, heartbeats VALIDATE (boat rule: schemas first).
Corrupt files are quarantined, never fatal.

Usage:
    from cascade.roster import beat
    beat("cascade", role="perception", shell="murex",
         detail={"m1_seen": 42})           # write once / per cycle

    python -m cascade.roster              # print the roster table
    python -m cascade.roster --json       # machine-readable
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from . import config

ROSTER_DIR_NAME = "roster"

# Slim heartbeat contract (schemas-first, docs/06 discipline)
REQUIRED = {
    "agent": str,
    "ts_utc": str,
    "ts_epoch": (int, float),
    "pid": int,
}
STALE_AFTER_S = 120
DEAD_AFTER_S = 600


def _dir(workspace: Path | None = None) -> Path:
    ws = workspace or Path(config.WORKSPACE)
    d = ws / ROSTER_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def beat(agent: str, role: str = "", shell: str = "", detail: dict | None = None,
         workspace: Path | None = None) -> Path:
    """Write one heartbeat for `agent`. Atomic (temp + replace)."""
    hb = {
        "agent": agent,
        "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ts_epoch": time.time(),
        "pid": os.getpid(),
        "role": role,
        "shell": shell,
        "detail": detail or {},
    }
    out = _dir(workspace) / f"{agent}.heartbeat.json"
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(hb))
    tmp.replace(out)
    return out


def _validate(hb: dict) -> list[str]:
    errs = []
    for field, types in REQUIRED.items():
        if field not in hb:
            errs.append(f"missing {field}")
        elif not isinstance(hb[field], types):
            errs.append(f"{field} wrong type")
    return errs


def read_roster(workspace: Path | None = None, now: float | None = None) -> list[dict]:
    """Read all heartbeats with liveness classification.

    Returns rows: {agent, role, shell, age_s, status, detail, errors}.
    status: alive | stale | dead. Corrupt files → status='quarantined'.
    """
    now = now if now is not None else time.time()
    rows = []
    d = _dir(workspace)
    for f in sorted(d.glob("*.heartbeat.json")):
        row = {"agent": f.name.replace(".heartbeat.json", ""), "errors": []}
        try:
            hb = json.loads(f.read_text())
            errs = _validate(hb)
            if errs:
                row.update(status="quarantined", errors=errs, age_s=None,
                           role="", shell="", detail={})
            else:
                age = max(0.0, now - hb["ts_epoch"])
                status = "alive" if age < STALE_AFTER_S else ("stale" if age < DEAD_AFTER_S else "dead")
                row.update(status=status, age_s=int(age),
                           role=hb.get("role", ""), shell=hb.get("shell", ""),
                           detail=hb.get("detail", {}))
        except (json.JSONDecodeError, OSError) as e:
            row.update(status="quarantined", errors=[str(e)], age_s=None,
                       role="", shell="", detail={})
        rows.append(row)
    return rows


def format_table(rows: list[dict]) -> str:
    if not rows:
        return "roster: empty (no heartbeats yet)"
    lines = [f"{'AGENT':<22} {'STATUS':<11} {'AGE':>6}  {'SHELL':<7} ROLE"]
    for r in rows:
        age = f"{r['age_s']}s" if r["age_s"] is not None else "?"
        lines.append(f"{r['agent']:<22} {r['status']:<11} {age:>6}  {r['shell']:<7} {r['role']}")
    return "\n".join(lines)


def main() -> None:
    rows = read_roster()
    if "--json" in sys.argv:
        print(json.dumps(rows, indent=2))
    else:
        print(format_table(rows))


if __name__ == "__main__":
    main()
