#!/usr/bin/env python3
"""alerts.py — Real-time alert system for the tzpro-agent capture pipeline.

Watches the analysis pipeline for:
  1. VOCABULARY_MATCH  — high-confidence species-at-depth blob clusters
  2. BOTTOM_CHANGE     — significant depth shifts (>5 fm between captures)
  3. INTENSITY_SPIKE   — mid-zone intensity >2x rolling average
  4. NO_ANALYSIS       — no new capture written in >15 minutes

Each rule returns a standardised alert dict; check_alerts() runs them all.

CLI:
    python alerts.py --oneshot          # check once, print triggers
    python alerts.py --daemon           # loop every 60s, only notify on new
    python alerts.py --daemon --dry-run # same but no Ship Log POST

Integration:
    - Called by analyzer.py after each successful analysis
    - POSTs alerts to Ship Log Search for semantic browsing
    - Deduplicates via .alert_state.json to avoid spam
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ── Config ─────────────────────────────────────────────────────────
WORKSPACE = Path(__file__).parent.resolve()
CAPTURES_DIR = WORKSPACE / "captures" / "v3"
VOCAB_CACHE = WORKSPACE / ".vocabulary_cache.json"
ALERT_STATE = WORKSPACE / ".alert_state.json"
SHIP_LOG_URL = "https://ship-log-search.casey-digennaro.workers.dev/api/log"
SHIP_LOG_TIMEOUT_S = 5
STALE_MINUTES = 15

# Vocabulary confidence threshold for alerting
VOCAB_CONFIDENCE_MIN = 0.7
BLOB_CLUSTER_MIN = 3  # minimum high-confidence blobs to trigger

# Bottom-change threshold (fm)
BOTTOM_DELTA_FM = 5.0

# Intensity spike: newest must exceed rolling average by this factor
INTENSITY_SPIKE_FACTOR = 2.0
INTENSITY_ROLLING_WINDOW = 6  # captures

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("alerts")


# ══════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════

def _hashid(rule_name: str, trigger_data: str) -> str:
    """Build a dedup ID: {rule_name}_{first 8 hex chars of sha256}."""
    h = hashlib.sha256(trigger_data.encode("utf-8")).hexdigest()[:8]
    return f"{rule_name}_{h}"


def _load_state() -> dict:
    """Load the dedup / acknowledgement state from disk."""
    if not ALERT_STATE.exists():
        return {}
    try:
        return json.loads(ALERT_STATE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(state: dict) -> None:
    """Atomically persist alert state."""
    try:
        tmp = ALERT_STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
        tmp.replace(ALERT_STATE)
    except OSError as e:
        log.warning("Failed to save alert state: %s", e)


def _already_sent(alert_id: str, state: dict) -> bool:
    """Return True if this alert was already dispatched and not acknowledged."""
    entry = state.get(alert_id)
    if entry is None:
        return False
    # Re-fire if the Captain acknowledged it (explicit clear)
    if entry.get("acknowledged", False):
        return False
    return True


def _post_to_ship_log(
    alert_type: str,
    severity: str,
    message: str,
    details: dict,
) -> None:
    """POST alert metadata to Ship Log Search for semantic browsing."""
    try:
        payload = {
            "text": message,
            "category": "observation",
            "subcategory": "alert",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "alert_type": alert_type,
                "severity": severity,
                "trigger_data": details,
            },
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            SHIP_LOG_URL,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36"
                ),
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=SHIP_LOG_TIMEOUT_S)
        log.info("Alert posted to Ship Log: %s", alert_type)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        log.warning("Ship Log alert post failed (non-blocking): %s", e)


# ══════════════════════════════════════════════════════════════════════
#  Capture discovery (no DB required — scan captures/v3/ directly)
# ══════════════════════════════════════════════════════════════════════

def _iter_captures(
    limit: Optional[int] = None,
) -> list[dict]:
    """Scan captures/v3/ for JSON metadata files, sorted by mtime desc.

    Searches both top-level captures/v3/*.json and captures/v3/<day_dir>/*.json.
    Each result is the full capture meta dict with extra '_json_path' and '_mtime' keys.
    """
    if not CAPTURES_DIR.exists():
        return []

    # Collect all candidate JSON files (skip helper files starting with __)
    candidates: list[tuple[Path, float]] = []
    for entry in CAPTURES_DIR.iterdir():
        if entry.is_dir():
            for js_file in entry.glob("*.json"):
                try:
                    candidates.append((js_file, js_file.stat().st_mtime))
                except OSError:
                    continue
        elif entry.is_file() and entry.suffix == ".json" and not entry.name.startswith("__"):
            try:
                candidates.append((entry, entry.stat().st_mtime))
            except OSError:
                continue

    # Sort by mtime descending
    candidates.sort(key=lambda x: x[1], reverse=True)
    if limit:
        candidates = candidates[:limit]

    results: list[dict] = []
    for js_file, mtime in candidates:
        try:
            meta = json.loads(js_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        meta["_json_path"] = str(js_file)
        meta["_mtime"] = mtime
        results.append(meta)

    return results


def _most_recent_capture() -> Optional[dict]:
    """Return the single most recent capture (by file mtime)."""
    results = _iter_captures(limit=1)
    return results[0] if results else None


# ══════════════════════════════════════════════════════════════════════
#  Rule 1: VOCABULARY_MATCH
# ══════════════════════════════════════════════════════════════════════

def check_vocabulary_match(
    conn: Optional[sqlite3.Connection] = None,
    vocab_cache_path: Optional[str] = None,
) -> Optional[dict]:
    """Check if the latest capture has a high-confidence vocabulary-match cluster.

    Reads latest capture's blobs, groups high-confidence predictions
    (> VOCAB_CONFIDENCE_MIN) by species + depth zone. Triggers when any
    group has > BLOB_CLUSTER_MIN blobs.
    """
    vocab_path = Path(vocab_cache_path) if vocab_cache_path else VOCAB_CACHE
    if not vocab_path.exists():
        log.debug("Vocabulary cache missing — skipping vocabulary match check")
        return None

    capture = _most_recent_capture()
    if not capture:
        return None

    analysis = capture.get("analysis") or {}
    heuristic = analysis.get("heuristic") or {}
    lf = heuristic.get("lf") or {}
    blobs = lf.get("blobs") or []

    if not blobs:
        return None

    # Group high-confidence predictions by species + depth zone
    groups: dict[tuple[str, str], list[dict]] = {}
    for blob in blobs:
        pred = blob.get("prediction")
        if not pred:
            continue
        confidence = pred.get("confidence", 0)
        if confidence < VOCAB_CONFIDENCE_MIN:
            continue
        species = pred.get("species", "unknown")
        depth = blob.get("centroid_depth_fm", 0)

        # Map depth to zone
        if depth < 5:
            zone = "surface"
        elif depth < 20:
            zone = "upper"
        elif depth < 40:
            zone = "mid"
        elif depth < 55:
            zone = "lower"
        else:
            zone = "floor"

        groups.setdefault((species, zone), []).append(blob)

    # Find largest cluster
    best = None
    best_count = 0
    for (species, zone), cluster_blobs in groups.items():
        if len(cluster_blobs) > best_count:
            best_count = len(cluster_blobs)
            best = (species, zone, cluster_blobs)

    if best is None or best_count < BLOB_CLUSTER_MIN:
        return None

    species, zone, cluster_blobs = best
    depths = sorted(b["centroid_depth_fm"] for b in cluster_blobs)
    depth_range = f"{int(depths[0])}-{int(depths[-1])}"

    pos = capture.get("position", {})
    trigger_data = (
        f"species={species}|zone={zone}|count={best_count}|"
        f"depths={depth_range}|capture_id={capture.get('capture_id', '?')}"
    )

    return {
        "triggered": True,
        "severity": "warning",
        "message": (
            f"High-confidence {species} cluster at {depth_range} fm, "
            f"{best_count} blobs."
        ),
        "details": {
            "species": species,
            "zone": zone,
            "blob_count": best_count,
            "depth_range_fm": depth_range,
            "blob_depths": depths,
            "capture_id": capture.get("capture_id"),
            "capture_ts": capture.get("ts_utc"),
            "position": pos,
            "trigger_data": trigger_data,
        },
        "rule_name": "VOCABULARY_MATCH",
    }


# ══════════════════════════════════════════════════════════════════════
#  Rule 2: BOTTOM_CHANGE
# ══════════════════════════════════════════════════════════════════════

def check_bottom_change(
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[dict]:
    """Compare bottom_depth_fm of the last 2 captures; alert if delta > 5 fm."""
    captures = _iter_captures(limit=2)
    if len(captures) < 2:
        return None

    newest, previous = captures[0], captures[1]

    def _extract_bottom(meta: dict) -> Optional[float]:
        analysis = meta.get("analysis") or {}
        heuristic = analysis.get("heuristic") or {}
        for band in ("lf", "hf"):
            bottom = heuristic.get(band, {}).get("bottom")
            if bottom:
                return bottom.get("bottom_depth_fm")
        return None

    depth_new = _extract_bottom(newest)
    depth_old = _extract_bottom(previous)

    if depth_new is None or depth_old is None:
        return None

    delta = abs(depth_new - depth_old)
    if delta <= BOTTOM_DELTA_FM:
        return None

    pos = newest.get("position", {})
    trigger_data = (
        f"old={depth_old:.1f}|new={depth_new:.1f}|delta={delta:.1f}|"
        f"capture_id={newest.get('capture_id', '?')}"
    )

    return {
        "triggered": True,
        "severity": "info",
        "message": (
            f"Bottom depth changed from {depth_old:.1f} to {depth_new:.1f} fm "
            f"— structural feature."
        ),
        "details": {
            "previous_depth_fm": depth_old,
            "current_depth_fm": depth_new,
            "delta_fm": delta,
            "capture_id": newest.get("capture_id"),
            "previous_capture_id": previous.get("capture_id"),
            "capture_ts": newest.get("ts_utc"),
            "position": pos,
            "trigger_data": trigger_data,
        },
        "rule_name": "BOTTOM_CHANGE",
    }


# ══════════════════════════════════════════════════════════════════════
#  Rule 3: INTENSITY_SPIKE
# ══════════════════════════════════════════════════════════════════════

def check_intensity_spike(
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[dict]:
    """Check if mid-zone mean_intensity in the latest capture exceeds 2× the
    rolling average of the previous 5 captures."""
    captures = _iter_captures(limit=INTENSITY_ROLLING_WINDOW)
    if len(captures) < INTENSITY_ROLLING_WINDOW:
        log.debug(
            "Only %d captures — need %d for intensity spike check",
            len(captures), INTENSITY_ROLLING_WINDOW,
        )
        return None

    def _extract_mid_intensity(meta: dict) -> Optional[float]:
        analysis = meta.get("analysis") or {}
        heuristic = analysis.get("heuristic") or {}
        lf = heuristic.get("lf") or {}
        mid = lf.get("zone_profiles", {}).get("mid", {})
        return mid.get("mean_intensity")

    intensities = []
    for cap in captures:
        mi = _extract_mid_intensity(cap)
        if mi is not None:
            intensities.append(mi)

    if len(intensities) < INTENSITY_ROLLING_WINDOW:
        return None

    newest = intensities[0]
    rolling_avg = sum(intensities[1:]) / (len(intensities) - 1)

    if rolling_avg <= 0:
        return None

    if newest <= INTENSITY_SPIKE_FACTOR * rolling_avg:
        return None

    pos = captures[0].get("position", {})
    trigger_data = (
        f"newest={newest:.1f}|rolling_avg={rolling_avg:.1f}|"
        f"ratio={newest / rolling_avg:.1f}|"
        f"capture_id={captures[0].get('capture_id', '?')}"
    )

    return {
        "triggered": True,
        "severity": "warning",
        "message": (
            f"Mid-zone intensity spike ({newest:.0f} vs rolling avg "
            f"{rolling_avg:.0f}) — dense biomass entering zone."
        ),
        "details": {
            "mid_zone_intensity": newest,
            "rolling_average": rolling_avg,
            "ratio": round(newest / rolling_avg, 1),
            "window_size": INTENSITY_ROLLING_WINDOW,
            "capture_id": captures[0].get("capture_id"),
            "capture_ts": captures[0].get("ts_utc"),
            "position": pos,
            "trigger_data": trigger_data,
        },
        "rule_name": "INTENSITY_SPIKE",
    }


# ══════════════════════════════════════════════════════════════════════
#  Rule 4: NO_ANALYSIS (stale)
# ══════════════════════════════════════════════════════════════════════

def check_stale_analysis(
    captures_dir: Optional[str] = None,
) -> Optional[dict]:
    """Check if the most recent capture.json was written > STALE_MINUTES ago."""
    cap_dir = Path(captures_dir) if captures_dir else CAPTURES_DIR

    # Find newest capture JSON by mtime across all day-dirs
    newest_path: Optional[Path] = None
    newest_mtime: float = 0

    if not cap_dir.exists():
        return {
            "triggered": True,
            "severity": "critical",
            "message": f"Captures directory not found — check pipeline.",
            "details": {
                "captures_dir": str(cap_dir),
                "reason": "directory_missing",
                "trigger_data": f"dir={cap_dir}|reason=missing",
            },
            "rule_name": "NO_ANALYSIS",
        }

    # Scan both top-level and subdirectory capture JSONs
    for entry in cap_dir.iterdir():
        if entry.is_dir():
            for js_file in entry.glob("*.json"):
                try:
                    mtime = js_file.stat().st_mtime
                except OSError:
                    continue
                if mtime > newest_mtime:
                    newest_mtime = mtime
                    newest_path = js_file
        elif entry.is_file() and entry.suffix == ".json" and not entry.name.startswith("__"):
            try:
                mtime = entry.stat().st_mtime
            except OSError:
                continue
            if mtime > newest_mtime:
                newest_mtime = mtime
                newest_path = entry

    if newest_path is None:
        return {
            "triggered": True,
            "severity": "critical",
            "message": (
                f"{STALE_MINUTES} min since last capture (empty dir) — "
                f"check daemon or connectivity."
            ),
            "details": {
                "captures_dir": str(cap_dir),
                "reason": "empty",
                "trigger_data": f"dir={cap_dir}|reason=empty",
            },
            "rule_name": "NO_ANALYSIS",
        }

    age_seconds = time.time() - newest_mtime
    age_minutes = age_seconds / 60.0

    if age_minutes > STALE_MINUTES:
        trigger_data = (
            f"last_file={newest_path.name}|age_min={age_minutes:.0f}|"
            f"threshold={STALE_MINUTES}"
        )
        return {
            "triggered": True,
            "severity": "critical",
            "message": (
                f"{age_minutes:.0f} min since last capture — "
                f"check daemon or connectivity."
            ),
            "details": {
                "last_capture_file": newest_path.name,
                "age_minutes": round(age_minutes, 1),
                "threshold_minutes": STALE_MINUTES,
                "last_mtime_iso": datetime.fromtimestamp(
                    newest_mtime, tz=timezone.utc
                ).isoformat(),
                "trigger_data": trigger_data,
            },
            "rule_name": "NO_ANALYSIS",
        }

    return None


# ══════════════════════════════════════════════════════════════════════
#  Rule 5: BOAT_PROXIMITY (sounder interference)
# ══════════════════════════════════════════════════════════════════════

def check_boat_proximity() -> Optional[dict]:
    """Check latest capture for sounder interference from nearby boats.

    Thresholds:
      few=1-4, several=5-11, many=12-24, dense=25+
      Alerts fire at "several" (5+) for info, "many" (12+) for warning.
    """
    capture = _most_recent_capture()
    if not capture:
        return None

    analysis = capture.get("analysis") or {}
    heuristic = analysis.get("heuristic") or {}
    lf = heuristic.get("lf") or {}
    boats = lf.get("boat_proximity") or {}

    n_lines = boats.get("vertical_line_count", 0)
    severity = boats.get("severity", "none")

    if n_lines < 5:
        return None

    pos = capture.get("position", {})
    trigger_data = (
        f"vertical_lines={n_lines}|severity={severity}|"
        f"capture_id={capture.get('capture_id', '?')}"
    )

    # Classify alert level
    if n_lines >= 12:
        alert_severity = "warning"
        message = (
            f"Heavy sounder interference: {n_lines} vertical lines "
            f"({severity}) — multiple boats very close, expect competition."
        )
    else:
        alert_severity = "info"
        message = (
            f"Nearby vessel detected: {n_lines} vertical line"
            f"{'s' if n_lines != 1 else ''} of sounder interference."
        )

    return {
        "triggered": True,
        "severity": alert_severity,
        "message": message,
        "details": {
            "vertical_line_count": n_lines,
            "severity": severity,
            "lines_per_zone": boats.get("lines_per_zone", {}),
            "max_span_fm": boats.get("max_vertical_span_fm"),
            "capture_id": capture.get("capture_id"),
            "capture_ts": capture.get("ts_utc"),
            "position": pos,
            "trigger_data": trigger_data,
        },
        "rule_name": "BOAT_PROXIMITY",
    }


# ══════════════════════════════════════════════════════════════════════
#  Orchestrator
# ══════════════════════════════════════════════════════════════════════

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


def check_alerts(db_path: Optional[str] = None) -> list[dict]:
    """Run all alert rules and return triggered alerts, sorted by severity.

    Opens SQLite if db_path given, otherwise scans captures/v3/ directly.
    Deduplicates using .alert_state.json — only returns alerts that
    haven't already been sent.
    """
    conn = None
    if db_path:
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
        except sqlite3.Error as e:
            log.warning("Cannot open DB at %s: %s — falling back to file scan", db_path, e)
            conn = None

    try:
        raw: list[dict] = []

        # Rule 1
        alert = check_vocabulary_match(conn)
        if alert:
            raw.append(alert)

        # Rule 2
        alert = check_bottom_change(conn)
        if alert:
            raw.append(alert)

        # Rule 3
        alert = check_intensity_spike(conn)
        if alert:
            raw.append(alert)

        # Rule 4
        alert = check_stale_analysis()
        if alert:
            raw.append(alert)

        # Rule 5
        alert = check_boat_proximity()
        if alert:
            raw.append(alert)

    finally:
        if conn:
            conn.close()

    # Deduplicate
    state = _load_state()
    triggered: list[dict] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for alert in raw:
        rule_name = alert["rule_name"]
        trigger_data = alert["details"].get("trigger_data", "")
        alert_id = _hashid(rule_name, trigger_data)

        if _already_sent(alert_id, state):
            log.debug("Skipping duplicate alert: %s", alert_id)
            continue

        state[alert_id] = {
            "triggered_at": now_iso,
            "acknowledged": False,
        }
        alert["alert_id"] = alert_id
        triggered.append(alert)

    if triggered:
        _save_state(state)

    # Sort by severity
    triggered.sort(key=lambda a: SEVERITY_ORDER.get(a.get("severity", "info"), 99))
    return triggered


# ══════════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════════

def _print_alerts(alerts: list[dict]) -> None:
    """Pretty-print triggered alerts."""
    if not alerts:
        print("OK: No alerts triggered.")
        return

    print(f"{len(alerts)} alert(s) triggered:\n")
    for a in alerts:
        sev_icon = {"critical": "[!!!]", "warning": "[!]", "info": "[* ]"}
        icon = sev_icon.get(a.get("severity", "info"), "[?]")
        print(f"  {icon} [{a.get('severity', '?').upper()}] {a['rule_name']}")
        print(f"     {a['message']}")
        print()


def cli() -> None:
    """CLI entry point — oneshot or daemon mode."""
    import sys

    if "--help" in sys.argv or "-h" in sys.argv:
        print("Usage:")
        print("  python alerts.py --oneshot          Check once, print triggers")
        print("  python alerts.py --daemon           Loop every 60s, notify on new")
        print("  python alerts.py --daemon --dry-run Same but no Ship Log POST")
        print("  python alerts.py --acknowledge <id> Mark alert as acknowledged")
        print("  python alerts.py --list-state       Show dedup state")
        print("  python alerts.py --clear-state      Clear all alert state")
        return

    if "--list-state" in sys.argv:
        state = _load_state()
        if not state:
            print("No alert state (empty).")
        else:
            print(json.dumps(state, indent=2))
        return

    if "--clear-state" in sys.argv:
        _save_state({})
        print("Alert state cleared.")
        return

    if "--acknowledge" in sys.argv:
        idx = sys.argv.index("--acknowledge") + 1
        if idx < len(sys.argv):
            alert_id = sys.argv[idx]
            state = _load_state()
            if alert_id in state:
                state[alert_id]["acknowledged"] = True
                _save_state(state)
                print(f"Alert {alert_id} acknowledged.")
            else:
                print(f"Alert id not found: {alert_id}")
        return

    dry_run = "--dry-run" in sys.argv

    if "--daemon" in sys.argv:
        log.info("=" * 50)
        log.info("alerts.py daemon starting")
        log.info("Check interval: 60s")
        log.info("Ship Log POST: %s", "OFF (dry-run)" if dry_run else "ON")
        log.info("=" * 50)

        while True:
            try:
                alerts = check_alerts()
                if alerts:
                    _print_alerts(alerts)
                    for alert in alerts:
                        log.warning(
                            "ALERT [%s] %s: %s",
                            alert.get("severity", "info"),
                            alert.get("rule_name", "?"),
                            alert.get("message", ""),
                        )
                        if not dry_run:
                            _post_to_ship_log(
                                alert_type=alert["rule_name"],
                                severity=alert["severity"],
                                message=alert["message"],
                                details=alert["details"],
                            )
                else:
                    log.debug("No new alerts")
            except Exception as e:
                log.error("Daemon loop error: %s", e, exc_info=True)

            time.sleep(60)

    elif "--oneshot" in sys.argv:
        alerts = check_alerts()
        _print_alerts(alerts)
        # In oneshot mode we don't persist dedup by default —
        # but check_alerts already updated state for anything new.
    else:
        print("Specify --oneshot, --daemon, or see --help")


if __name__ == "__main__":
    cli()
