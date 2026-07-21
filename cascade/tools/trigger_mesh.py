"""cascade/tools/trigger_mesh.py — the trigger mesh (docs/27).

Correlation wake-ups between git-agents. Triggers are DATA (JSON,
versionable in the agent's repo), never code. Every firing is logged
with reasons. No eval/exec anywhere.

Spec (cascade_out/agents/<agent>/triggers.json):
{
  "triggers": [{
    "id": "wind_ramp_alert",
    "when": {"metric": "pulse.wind.speed_kn", "op": ">", "value": 15},
    "and":  {"metric": "vessel.near_island", "op": "==", "value": true},
    "then": {"action": "analyze", "params": {"lee_profile": true}},
    "cooldown_s": 3600
  }]
}

CLI:
    python -m cascade.tools.trigger_mesh --check   # evaluate all
    python -m cascade.tools.trigger_mesh --demo    # demo fire
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

from .. import config, roster

log = logging.getLogger("cascade.trigger_mesh")

OPS = {
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}

_METRICS: dict[str, callable] = {}
_ACTIONS: dict[str, callable] = {}


def register_metric(name: str, fn: callable) -> None:
    _METRICS[name] = fn


def register_action(name: str, fn: callable) -> None:
    _ACTIONS[name] = fn


# ── built-in metric providers ────────────────────────────────────────

def _wind_metric(field: str):
    def _get():
        f = Path(config.OUT) / "agents" / "pulse_wind" / "pulses.jsonl"
        if not f.exists():
            return None
        lines = f.read_text().splitlines()
        if not lines:
            return None
        try:
            return json.loads(lines[-1]).get(field)
        except json.JSONDecodeError:
            return None
    return _get


def _roster_metric(field: str):
    def _get():
        rows = roster.read_roster()
        if field == "alive_count":
            return sum(1 for r in rows if r["status"] == "alive")
        if field == "dead_count":
            return sum(1 for r in rows if r["status"] in ("dead", "quarantined"))
        return None
    return _get


def _twin_records_today() -> int:
    import sqlite3
    db = Path(config.WORKSPACE) / "memory" / "meta.db"
    if not db.exists():
        return 0
    day_start = int(time.time() - (time.time() % 86400)) * 1000
    conn = sqlite3.connect(str(db))
    n = conn.execute("SELECT COUNT(*) FROM echogram_records WHERE ts_utc >= ?",
                     (day_start,)).fetchone()[0]
    conn.close()
    return n


def _register_builtins() -> None:
    register_metric("pulse.wind.speed_kn", _wind_metric("speed_kn"))
    register_metric("pulse.wind.dir_deg", _wind_metric("dir_deg"))
    register_metric("roster.alive_count", _roster_metric("alive_count"))
    register_metric("roster.dead_count", _roster_metric("dead_count"))
    register_metric("twin.records.count", _twin_records_today)


# ── engine ───────────────────────────────────────────────────────────

def _state_path() -> Path:
    return Path(config.OUT) / "agents" / "mesh_state.json"


def _load_state() -> dict:
    p = _state_path()
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _save_state(state: dict) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(p)


def _eval_condition(cond: dict, errors: list[str]) -> bool:
    metric = cond.get("metric")
    fn = _METRICS.get(metric)
    if fn is None:
        errors.append(f"unknown metric: {metric}")
        return False
    value = fn()
    if value is None:
        return False
    op = OPS.get(cond.get("op"))
    if op is None:
        errors.append(f"unknown op: {cond.get('op')}")
        return False
    try:
        return bool(op(value, cond.get("value")))
    except TypeError:
        errors.append(f"type error on {metric}: {value!r} vs {cond.get('value')!r}")
        return False


def check(triggers_path: Path, now: float | None = None) -> list[dict]:
    """Evaluate all triggers. Returns firing reports (also logged)."""
    now = now if now is not None else time.time()
    if not triggers_path.exists():
        return []
    spec = json.loads(triggers_path.read_text())
    state = _load_state()
    fired = []

    for trig in spec.get("triggers", []):
        tid = trig.get("id", "?")
        last = state.get(tid, 0.0)
        if now - last < trig.get("cooldown_s", 0):
            continue
        errors: list[str] = []
        ok = _eval_condition(trig.get("when", {}), errors)
        if ok and "and" in trig:
            ok = _eval_condition(trig["and"], errors)
        if errors:
            log.warning("trigger %s: %s", tid, "; ".join(errors))
        if not ok:
            continue

        action = (trig.get("then") or {}).get("action")
        hook = _ACTIONS.get(action)
        report = {
            "id": tid,
            "ts_epoch": now,
            "action": action,
            "params": (trig.get("then") or {}).get("params", {}),
            "fired": hook is not None,
            "reason": f"conditions met (cooldown {trig.get('cooldown_s', 0)}s)",
        }
        if hook:
            hook(report)
        else:
            log.warning("trigger %s fired but no action hook for %r", tid, action)
        fired.append(report)
        state[tid] = now

    if fired:
        _save_state(state)
    return fired


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
    _register_builtins()

    if "--demo" in sys.argv:
        register_metric("demo.value", lambda: 42)
        register_action("demo_action", lambda r: print("ACTION FIRED:", json.dumps(r)))
        demo_path = Path(config.OUT) / "agents" / "demo" / "triggers.json"
        demo_path.parent.mkdir(parents=True, exist_ok=True)
        demo_path.write_text(json.dumps({"triggers": [{
            "id": "demo_trigger",
            "when": {"metric": "demo.value", "op": ">", "value": 10},
            "then": {"action": "demo_action"},
            "cooldown_s": 0,
        }]}))
        for r in check(demo_path):
            print("fired:", r["id"], "->", r["action"])
        return

    agents_dir = Path(config.OUT) / "agents"
    any_fired = False
    for spec in sorted(agents_dir.glob("*/triggers.json")):
        for r in check(spec):
            print(f"FIRED {r['id']} -> {r['action']} {r['params']}")
            any_fired = True
    if not any_fired:
        print("mesh: no triggers fired")


if __name__ == "__main__":
    main()
