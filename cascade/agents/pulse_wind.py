"""cascade/agents/pulse_wind.py — PULSE, the wind watcher.

FIRST git-agent of the docs/27 roster — the reference implementation of
the five-channel contract: pulse in / gaze / trigger / record / heartbeat.

Narrow by design: wind pulses in, pattern records out. Routine hours
write NOTHING — silence is the correct output (docs/26).

CLI:
    python -m cascade.agents.pulse_wind --once     # one sense+analyze cycle
    python -m cascade.agents.pulse_wind --status   # baselines summary
"""
from __future__ import annotations

import json
import logging
import math
import sys
import time
import urllib.request
from pathlib import Path

from .. import config, roster

log = logging.getLogger("cascade.pulse_wind")

AGENT = "pulse_wind"
RAMP_KN_PER_HR = 5.0
VEER_DEG_PER_HR = 45.0
DIVERGENCE_KN = 7.0
WINDOW_S = 3600 * 3  # 3h rolling window for gust structure
BASELINE_BLOCKS = 8  # 3-hour blocks per day


# ── state (git-native files, atomic writes) ──────────────────────────

def state_dir() -> Path:
    d = Path(config.OUT) / "agents" / AGENT
    (d / "records").mkdir(parents=True, exist_ok=True)
    return d


def _atomic_json(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(path)


def load_pulses() -> list[dict]:
    f = state_dir() / "pulses.jsonl"
    if not f.exists():
        return []
    out = []
    for line in f.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # quarantine: skip, never fatal
    return out


def append_pulse(p: dict) -> bool:
    """Append if new (dedupe by ts). Returns True if appended."""
    f = state_dir() / "pulses.jsonl"
    existing = {q["ts"] for q in load_pulses()[-50:]}
    if p["ts"] in existing:
        return False
    with f.open("a") as fh:
        fh.write(json.dumps(p) + "\n")
    return True


# ── SENSE (pulse in) ─────────────────────────────────────────────────

def sense(lat: float, lon: float) -> dict | None:
    """Fetch latest wind observation near (lat, lon) from weather.gov.
    Offline returns None (never raises — boat rule)."""
    try:
        req = urllib.request.Request(
            f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}",
            headers={"User-Agent": "(boat-agent pulse_wind, contact)"})
        with urllib.request.urlopen(req, timeout=10) as r:
            points = json.loads(r.read().decode())
        stations_url = points["properties"]["observationStations"]
        with urllib.request.urlopen(urllib.request.Request(
                stations_url, headers={"User-Agent": "(boat-agent pulse_wind, contact)"}), timeout=10) as r:
            stations = json.loads(r.read().decode())
        obs_url = stations["features"][0]["id"] + "/observations/latest"
        with urllib.request.urlopen(urllib.request.Request(
                obs_url, headers={"User-Agent": "(boat-agent pulse_wind, contact)"}), timeout=10) as r:
            obs = json.loads(r.read().decode())
        props = obs["properties"]
        speed = (props.get("windSpeed") or {}).get("value")  # km/h
        direc = (props.get("windDirection") or {}).get("value")
        if speed is None or direc is None:
            return None
        return {
            "ts": props.get("timestamp", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
            "ts_epoch": time.time(),
            "lat": lat, "lon": lon,
            "speed_kn": round(speed * 0.539957, 1),
            "dir_deg": float(direc),
            "source": "weather.gov",
            "provenance": "measured",
        }
    except Exception as e:
        log.info("sense offline: %s", e)
        return None


def vessel_position() -> tuple[float, float]:
    """Mean position from today's twin frames; fallback Ketchikan area."""
    try:
        import sqlite3
        db = Path(config.WORKSPACE) / "memory" / "meta.db"
        conn = sqlite3.connect(str(db))
        row = conn.execute(
            "SELECT AVG(lat), AVG(lon) FROM frames WHERE lat IS NOT NULL"
        ).fetchone()
        conn.close()
        if row and row[0] and row[1]:
            return float(row[0]), float(row[1])
    except Exception:
        pass
    return 55.787, -131.70


# ── ANALYZE (patterns, no LLM) ───────────────────────────────────────

def _ang_diff(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def detect_patterns(pulses: list[dict]) -> list[dict]:
    """Detect ramp / veer / gust structure over the pulse window."""
    if len(pulses) < 2:
        return []
    patterns = []
    first, last = pulses[0], pulses[-1]
    span_hr = max((last["ts_epoch"] - first["ts_epoch"]) / 3600.0, 1e-6)

    ramp = (last["speed_kn"] - first["speed_kn"]) / span_hr
    if abs(ramp) > RAMP_KN_PER_HR:
        patterns.append({
            "pattern": "wind_ramp_up" if ramp > 0 else "wind_ramp_down",
            "detail": f"{ramp:+.1f} kn/hr over {span_hr:.1f}h ({first['speed_kn']}→{last['speed_kn']} kn)",
            "provenance": "measured",
        })

    veer = _ang_diff(last["dir_deg"], first["dir_deg"]) / span_hr
    if veer > VEER_DEG_PER_HR:
        patterns.append({
            "pattern": "wind_veer",
            "detail": f"{veer:.0f}°/hr shift ({first['dir_deg']:.0f}°→{last['dir_deg']:.0f}°) over {span_hr:.1f}h",
            "provenance": "measured",
        })

    speeds = [p["speed_kn"] for p in pulses]
    if len(speeds) >= 3:
        mean = sum(speeds) / len(speeds)
        var = sum((s - mean) ** 2 for s in speeds) / len(speeds)
        if mean > 5 and math.sqrt(var) / mean > 0.35:
            patterns.append({
                "pattern": "gusty",
                "detail": f"gust spread σ/mean = {math.sqrt(var)/mean:.2f} over {len(speeds)} pulses (mean {mean:.0f} kn)",
                "provenance": "measured",
            })
    return patterns


def update_baselines(pulse: dict) -> None:
    """Weekly norms per 3-hour block (simple moving mean)."""
    bf = state_dir() / "baselines.json"
    base = json.loads(bf.read_text()) if bf.exists() else {}
    block = time.strftime("%w-%H", time.gmtime(pulse["ts_epoch"] / 1))
    block_key = f"{int(block[0])}_{int(block[2:]) // 3}"
    entry = base.get(block_key, {"n": 0, "mean": 0.0})
    entry["mean"] = (entry["mean"] * entry["n"] + pulse["speed_kn"]) / (entry["n"] + 1)
    entry["n"] += 1
    base[block_key] = entry
    _atomic_json(bf, base)


# ── RECORD (out) ─────────────────────────────────────────────────────

def record(patterns: list[dict], pulse: dict) -> None:
    for p in patterns:
        rec = {
            "spec": "wind_record/1",
            "agent": AGENT,
            "ts_utc": pulse["ts"],
            "lat": pulse["lat"], "lon": pulse["lon"],
            "pattern": p["pattern"],
            "detail": p["detail"],
            "provenance": p["provenance"],
        }
        out = state_dir() / "records" / f"{rec['ts_utc'].replace(':', '')}_{p['pattern']}.json"
        _atomic_json(out, rec)
        log.info("record: %s — %s", p["pattern"], p["detail"])


# ── the loop ─────────────────────────────────────────────────────────

def run_once() -> dict:
    lat, lon = vessel_position()
    pulse = sense(lat, lon)
    if pulse is None:
        roster.beat(AGENT, role="wind", shell="conch", detail={"offline": True})
        return {"offline": True}

    appended = append_pulse(pulse)
    window = [p for p in load_pulses() if pulse["ts_epoch"] - p["ts_epoch"] <= WINDOW_S]
    patterns = detect_patterns(window)
    if appended:
        update_baselines(pulse)
        if patterns:
            record(patterns, pulse)

    roster.beat(AGENT, role="wind", shell="conch",
                detail={"pulses": len(load_pulses()), "patterns_fired": len(patterns)})
    return {"pulse": pulse, "appended": appended, "patterns": patterns}


def status() -> str:
    bf = state_dir() / "baselines.json"
    base = json.loads(bf.read_text()) if bf.exists() else {}
    pulses = load_pulses()
    lines = [f"pulse_wind: {len(pulses)} pulses on file, {len(base)} baseline blocks"]
    for k in sorted(base):
        lines.append(f"  block {k}: mean {base[k]['mean']:.1f} kn (n={base[k]['n']})")
    return "\n".join(lines)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
    if "--status" in sys.argv:
        print(status())
    else:
        print(json.dumps(run_once(), indent=2, default=str))


if __name__ == "__main__":
    main()
