"""companion/bridge.py — cascade → ship-log-search ingester.

Polls `cascade_out/briefings/` every POLL_INTERVAL_S for new H1 briefing
JSON sidecars and D1 daily-report JSON sidecars, transforms each into a
ship-log-search log entry, and POSTs to `{COMPANION_URL}/api/ingest`.

Idempotency: tracks sent capture IDs in `.sent_ids.json`. Restart-safe.

Configuration: companion/config.toml (or env vars — see CONFIG_SPEC below).

Logging: appends to companion/bridge.log and to stderr.

Usage:
    python bridge.py                     # foreground
    python bridge.py --once              # run one cycle and exit (for cron)
    python bridge.py --dry-run           # print what would be sent, don't POST
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

import requests  # noqa: F401  (imported for type clarity; actual usage below)

# ── Paths ──────────────────────────────────────────────────────────────
HERE = Path(__file__).parent.resolve()
SENT_IDS_FILE = HERE / ".sent_ids.json"
LOG_FILE = HERE / "bridge.log"
CONFIG_FILE = HERE / "config.toml"

# Default cascade path (matches cascade/config.py default with TZPRO_WORKSPACE)
DEFAULT_CASCADE_BRIEFINGS = (
    Path(os.environ.get(
        "TZPRO_WORKSPACE",
        r"C:\Users\casey\.openclaw\workspace\tzpro-agent",
    ))
    / "cascade_out"
    / "briefings"
)

# ── Defaults ───────────────────────────────────────────────────────────
DEFAULT_COMPANION_URL = "http://127.0.0.1:8787"
DEFAULT_COMPANION_KEY = ""  # read from COMPANION_KEY env or config.toml
DEFAULT_POLL_INTERVAL_S = 30
DEFAULT_TIMEOUT_S = 10

# ── Logging ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ],
)
log = logging.getLogger("companion.bridge")

# ── Config ─────────────────────────────────────────────────────────────

def load_config() -> dict:
    """Load config.toml if present, env vars override, defaults fill gaps."""
    cfg = {
        "companion_url": DEFAULT_COMPANION_URL,
        "companion_key": DEFAULT_COMPANION_KEY,
        "cascade_briefings": str(DEFAULT_CASCADE_BRIEFINGS),
        "poll_interval_s": DEFAULT_POLL_INTERVAL_S,
        "timeout_s": DEFAULT_TIMEOUT_S,
    }
    if CONFIG_FILE.exists():
        try:
            import tomllib  # py3.11+
        except ImportError:
            try:
                import tomli as tomllib  # type: ignore
            except ImportError:
                log.warning("tomllib/tomli not available; skipping %s", CONFIG_FILE)
                tomllib = None  # type: ignore
        if tomllib is not None:
            try:
                with open(CONFIG_FILE, "rb") as f:
                    disk_cfg = tomllib.load(f)
                cfg.update({k: v for k, v in disk_cfg.items() if v is not None})
            except Exception as e:
                log.warning("failed to parse %s: %s", CONFIG_FILE, e)

    # Env var overrides
    cfg["companion_url"] = os.environ.get("COMPANION_URL", cfg["companion_url"])
    cfg["companion_key"] = os.environ.get("COMPANION_KEY", cfg["companion_key"])
    return cfg


# ── Sent-IDs tracking ──────────────────────────────────────────────────

def load_sent_ids() -> set[str]:
    if SENT_IDS_FILE.exists():
        try:
            with open(SENT_IDS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.get("ids", []))
        except Exception as e:
            log.warning("failed to load %s: %s", SENT_IDS_FILE, e)
    return set()


def save_sent_ids(ids: set[str]) -> None:
    tmp = SENT_IDS_FILE.with_suffix(".json.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"ids": sorted(ids), "updated": time.time()}, f)
        tmp.replace(SENT_IDS_FILE)
    except Exception as e:
        log.warning("failed to save %s: %s", SENT_IDS_FILE, e)


# ── Category derivation ────────────────────────────────────────────────

CATEGORY_KEYWORDS = {
    "catch": [
        r"\b(catch|harvest|kept|landed|sockeye|chinook|coho|pink|chum|halibut)\b",
        r"\b\d+\s*(lbs?|fish)\b",
        r"\b(soak|set|retrieve|haul)\b",
    ],
    "weather": [
        r"\b(wind|gust|sea state|swell|wave|fog|visibility|barometer|pressure)\b",
        r"\b(north wind|south wind|east wind|west wind)\b",
    ],
    "navigation": [
        r"\b(course|heading|position|drift|anchor|waypoint|rendezvous)\b",
        r"\b\d+\s*(°|deg)\b",
    ],
    "maintenance": [
        r"\b(engine|hydraulic|repair|service|replace|filter|oil|hose|fitting)\b",
        r"\b(breakdown|failure|leak)\b",
    ],
}


def derive_category(text: str) -> str:
    """Pick the category with the most keyword hits, default to 'observation'."""
    if not text:
        return "observation"
    scores = {}
    for cat, patterns in CATEGORY_KEYWORDS.items():
        scores[cat] = sum(
            len(re.findall(p, text, flags=re.IGNORECASE)) for p in patterns
        )
    best = max(scores.items(), key=lambda kv: kv[1])
    return best[0] if best[1] > 0 else "observation"


# ── File → log-entry transformation ────────────────────────────────────

# Files we care about:
#   _briefing_<UTC_TS>.json     → H1 hourly structured sidecar
#   day_<YYYY-MM-DD>.json       → D1 daily structured sidecar
H1_RE = re.compile(r"^_briefing_(\d{8}T\d{6})Z?\.json$")
D1_RE = re.compile(r"^day_(\d{4}-\d{2}-\d{2})\.json$")


def build_id(filename: str, kind: str) -> str:
    """Stable, idempotent log ID. Never collides across kinds."""
    stem = Path(filename).stem  # strip .json
    return f"tzpro-{kind}-{stem}"


def truncate(s: str, max_chars: int = 4000) -> str:
    if not s:
        return ""
    return s if len(s) <= max_chars else s[: max_chars - 1] + "."


def h1_to_log_entry(path: Path) -> Optional[dict]:
    """Transform H1 _briefing_<ts>.json into a ship-log-search log entry."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            sidecar = json.load(f)
    except Exception as e:
        log.warning("could not read %s: %s", path.name, e)
        return None

    # H1 JSON shape (from cascade/hourly_loop.py):
    #   {summary, tide, weather, retention_stats, structured_minimal, ts_utc}
    text = (
        sidecar.get("summary", "")
        or sidecar.get("structured_minimal", {}).get("summary", "")
        or ""
    )
    if not text.strip():
        log.info("skipping %s: empty summary", path.name)
        return None

    # Extract position from any first capture referenced (rare in H1; usually None)
    lat = sidecar.get("lat")
    lon = sidecar.get("lon")
    location_name = sidecar.get("location_name")

    ts = sidecar.get("ts_utc") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    return {
        "id": build_id(path.name, "h1"),
        "text": truncate(text),
        "category": derive_category(text),
        "timestamp": ts,
        "lat": lat,
        "lon": lon,
        "location_name": location_name,
        "metadata": {
            "kind": "h1_briefing",
            "source_file": path.name,
            "tide": sidecar.get("tide"),
            "weather": sidecar.get("weather"),
            "retention_stats": sidecar.get("retention_stats"),
        },
    }


def d1_to_log_entry(path: Path) -> list[dict]:
    """Transform D1 day_<DATE>.json into one log entry per key event.

    The D1 daily report aggregates many events. To preserve searchability,
    we emit one ship-log-search log entry per event with a stable ID,
    plus one 'summary' entry per day for high-level queries.

    Returns an empty list if the file is unreadable, has no usable date,
    has no summary and no events and no anomalies. Never returns None.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            sidecar = json.load(f)
    except Exception as e:
        log.warning("could not read %s: %s", path.name, e)
        return None

    date = sidecar.get("date") or re.search(r"day_(\d{4}-\d{2}-\d{2})", path.name)
    date = date if isinstance(date, str) else (date.group(1) if date else None)
    if not date:
        log.warning("could not extract date from %s", path.name)
        return []  # unreadable / no-date → empty list, not None

    entries = []

    # 1) Day-level summary entry
    summary_text = sidecar.get("summary") or sidecar.get("narrative") or ""
    if summary_text.strip():
        entries.append({
            "id": build_id(f"day_{date}", "d1-summary"),
            "text": truncate(summary_text),
            "category": derive_category(summary_text),
            "timestamp": f"{date}T23:59:00Z",
            "lat": sidecar.get("lat"),
            "lon": sidecar.get("lon"),
            "location_name": sidecar.get("location_name"),
            "metadata": {
                "kind": "d1_summary",
                "source_file": path.name,
                "hotspots": sidecar.get("hotspots", []),
                "anomalies": sidecar.get("anomalies", []),
                "counts": sidecar.get("counts", {}),
            },
        })

    # 2) Per-key-event entries (more searchable for the captain)
    for i, ev in enumerate(sidecar.get("key_events", []) or []):
        ev_text = ev.get("narrative") or ev.get("text") or ev.get("description") or ""
        if not ev_text.strip():
            continue
        ev_ts = ev.get("timestamp") or f"{date}T12:00:00Z"
        entries.append({
            "id": build_id(f"day_{date}_ev{i}", "d1-event"),
            "text": truncate(ev_text),
            "category": derive_category(ev_text),
            "timestamp": ev_ts,
            "lat": ev.get("lat") or sidecar.get("lat"),
            "lon": ev.get("lon") or sidecar.get("lon"),
            "location_name": ev.get("location_name") or sidecar.get("location_name"),
            "metadata": {
                "kind": "d1_event",
                "source_file": path.name,
                "event_index": i,
                "tags": ev.get("tags", []),
            },
        })

    # 3) Per-anomaly entries (anomalies are the most-searched-for kind)
    for i, an in enumerate(sidecar.get("anomalies", []) or []):
        an_text = an.get("description") or an.get("narrative") or an.get("text") or ""
        if not an_text.strip():
            continue
        an_ts = an.get("timestamp") or f"{date}T12:00:00Z"
        entries.append({
            "id": build_id(f"day_{date}_an{i}", "d1-anomaly"),
            "text": truncate(an_text),
            "category": "observation",  # anomalies are explicitly observational
            "timestamp": an_ts,
            "lat": an.get("lat") or sidecar.get("lat"),
            "lon": an.get("lon") or sidecar.get("lon"),
            "location_name": an.get("location_name") or sidecar.get("location_name"),
            "metadata": {
                "kind": "d1_anomaly",
                "source_file": path.name,
                "anomaly_index": i,
                "severity": an.get("severity", "unknown"),
            },
        })

    return entries  # empty list when no summary and no events and no anomalies


# Returns either a single dict (H1) or a list of dicts (D1), or None to skip.
def path_to_log_entry(path: Path) -> Optional[dict | list[dict]]:
    if H1_RE.match(path.name):
        return h1_to_log_entry(path)
    if D1_RE.match(path.name):
        return d1_to_log_entry(path)
    return None  # not a file we care about (e.g., .md sidecar or _structured)


# ── Posting ────────────────────────────────────────────────────────────

def post_entry(entry: dict, url: str, key: str, timeout_s: int) -> bool:
    """POST a single entry via /api/ingest. Returns True on success."""
    body = {
        "documents": [{
            "id": entry["id"],
            "text": entry["text"],
            "category": entry.get("category", "observation"),
            "timestamp": entry["timestamp"],
            "lat": entry.get("lat"),
            "lon": entry.get("lon"),
            "location_name": entry.get("location_name"),
            "metadata": entry.get("metadata", {}),
        }],
    }
    headers = {"Content-Type": "application/json"}
    if key:
        headers["X-Log-Key"] = key
    try:
        r = requests.post(
            f"{url.rstrip('/')}/api/ingest",
            json=body,
            headers=headers,
            timeout=timeout_s,
        )
    except requests.RequestException as e:
        log.warning("POST %s failed (network): %s", entry["id"], e)
        return False

    if 200 <= r.status_code < 300:
        log.info("ingested %s (%d bytes text)", entry["id"], len(entry["text"]))
        return True
    if 400 <= r.status_code < 500:
        # Client error: don't retry, log and skip
        log.warning("POST %s rejected (%d): %s",
                    entry["id"], r.status_code, r.text[:200])
        return False
    # 5xx: caller will retry
    log.warning("POST %s server error (%d): %s",
                entry["id"], r.status_code, r.text[:200])
    return False


# ── Main loop ──────────────────────────────────────────────────────────

def discover_files(briefings_dir: Path) -> list[Path]:
    if not briefings_dir.exists():
        return []
    return sorted(p for p in briefings_dir.iterdir() if p.is_file())


def run_once(cfg: dict, sent_ids: set[str], dry_run: bool = False) -> set[str]:
    """One poll cycle. Returns the updated sent_ids set."""
    briefings_dir = Path(cfg["cascade_briefings"])
    files = discover_files(briefings_dir)
    if not files:
        log.debug("no briefing files in %s", briefings_dir)
        return sent_ids

    url = cfg["companion_url"]
    key = cfg["companion_key"]
    timeout_s = int(cfg["timeout_s"])

    for path in files:
        entry_or_list = path_to_log_entry(path)
        if entry_or_list is None:
            continue
        entries = entry_or_list if isinstance(entry_or_list, list) else [entry_or_list]
        for entry in entries:
            if entry["id"] in sent_ids:
                continue
            if dry_run:
                log.info("[dry-run] would POST %s (%d chars)",
                         entry["id"], len(entry["text"]))
                sent_ids.add(entry["id"])
                continue
            ok = post_entry(entry, url, key, timeout_s)
            if ok:
                sent_ids.add(entry["id"])
            else:
                # Don't mark as sent; retry next cycle (5xx) or skip (4xx)
                # 4xx already logged; nothing more to do here.
                pass

    return sent_ids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true",
                        help="Run one cycle and exit (for cron / smoke test).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be sent, don't actually POST.")
    args = parser.parse_args()

    cfg = load_config()
    log.info("bridge starting: url=%s, dir=%s, interval=%ss",
             cfg["companion_url"], cfg["cascade_briefings"],
             cfg["poll_interval_s"])

    sent_ids = load_sent_ids()
    log.info("loaded %d previously-sent IDs", len(sent_ids))

    try:
        if args.once or args.dry_run:
            new_ids = run_once(cfg, sent_ids, dry_run=args.dry_run)
            save_sent_ids(new_ids)
            log.info("one cycle complete: %d sent total", len(new_ids))
            return 0

        while True:
            sent_ids = run_once(cfg, sent_ids)
            save_sent_ids(sent_ids)
            time.sleep(int(cfg["poll_interval_s"]))
    except KeyboardInterrupt:
        log.info("interrupted, saving state")
        save_sent_ids(sent_ids)
        return 0


if __name__ == "__main__":
    sys.exit(main())