#!/usr/bin/env python3
"""catch_link.py — Link Captain's catch reports to echogram captures.

Phase 4 of the capture pipeline. When the Captain reports a catch
("chum at 35 fm, 15 fish"), this module:

1. Finds the nearest echogram capture in time/space
2. Annotates the capture JSON with the catch report as a supervised label
3. Re-POSTs the annotated capture to Ship Log Search
4. Feeds the labeled data into analyzer.py's vocabulary builder

DESIGN:
- Labels are additive, never overwritten (schema_version increments)
- Multiple catch reports can link to the same capture (different species/depths)
- Time proximity is primary; spatial proximity is tiebreaker
- The vocabulary graduates from "unidentified blob at 35 fm" to
  "probable chum at 35 fm, conf 0.73" through Bayesian accumulation

USAGE:
    python catch_link.py link <species> <depth_fm> <count> [--ts <timestamp>]
    python catch_link.py link --interactive   (prompts)

EXAMPLES:
    python catch_link.py link chum 35 15
    python catch_link.py link sockeye 25 8 --ts "2026-07-17T20:40:00Z"
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ── Config ─────────────────────────────────────────────────────────
CAPTURES_DIR = Path(__file__).parent.resolve() / "captures" / "v3"
SHIP_LOG_URL = "https://ship-log-search.casey-digennaro.workers.dev/api/log"
SHIP_LOG_SEARCH_URL = "https://ship-log-search.casey-digennaro.workers.dev/api/timeline"
SHIP_LOG_TIMEOUT_S = 5

LOCAL_TZ = timezone(timedelta(hours=-8))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("catch_link")

# Species aliases (Captain's terminology → canonical)
SPECIES_ALIASES: dict[str, str] = {
    # Chum
    "chum": "chum",
    "chums": "chum",
    "chum salmon": "chum",
    # Sockeye
    "sockeye": "sockeye",
    "reds": "sockeye",
    "red": "sockeye",
    # Coho
    "coho": "coho",
    "silver": "coho",
    # Pink
    "pink": "pink",
    "humpies": "pink",
    "humpy": "pink",
    # King
    "king": "king",
    "chinook": "king",
    "spring": "king",
    # Other
    "halibut": "halibut",
    "cod": "cod",
    "rockfish": "rockfish",
    "herring": "herring",
    "bait": "bait",
}

# Depth zone mapping for vocabulary
DEPTH_ZONES = {
    "surface": (0, 5),
    "upper": (5, 20),
    "mid": (20, 40),
    "lower": (40, 55),
    "floor": (55, 60),
}


# ══════════════════════════════════════════════════════════════════════
#  Catch Report Parser
# ══════════════════════════════════════════════════════════════════════

def parse_catch_report(text: str) -> Optional[dict]:
    """Parse a natural-language catch report from the Captain.

    Handles formats like:
    - "chum at 35 fm, 15 fish"
    - "15 chum at 35 fm"
    - "picked up 8 sockeye at 25 fm"
    - "coho boil at 20 fm, saw 30+ fish"
    - "35 fm chum, about a dozen"

    Returns dict with species, depth_fm, count, or None.
    """
    text_lower = text.lower().strip()

    # Extract count (look for number near fish/fm/at)
    count = None
    count_patterns = [
        r"(\d+)\s*[+]?\s*(?:fish|chum|sockeye|coho|pink|salmon|king|halibut|bait)",
        r"(?:about|around|maybe|saw|counted)\s*(\d+)",
        r"(?:a\s+)?dozen(?:\s+or\s+so)?",  # "a dozen" → 12
        r"(?:couple|few)\s*dozen",  # "couple dozen" → 24
    ]
    for pat in count_patterns:
        m = re.search(pat, text_lower)
        if m:
            if "dozen" in pat and "dozen" in m.group():
                # Handle "a dozen" → 12, "couple dozen" → 24
                prefix = text_lower[:m.start()].strip()
                if "couple" in prefix or "few" in prefix:
                    count = 24
                else:
                    count = 12
            else:
                count = int(m.group(1))
            break

    # If count not found, try simpler patterns
    if count is None:
        m = re.search(r"(\d+)\s*[+]?\s*(?:at|in|on)", text_lower)
        if m:
            count = int(m.group(1))

    # Extract depth (look for number near fm/fathom)
    depth_fm = None
    depth_patterns = [
        r"(?:at|in|on|about|around)\s*(\d+)\s*(?:fm|fathom|fathoms)",
        r"(\d+)\s*(?:fm|fathom|fathoms)",
    ]
    for pat in depth_patterns:
        m = re.search(pat, text_lower)
        if m:
            depth_fm = int(m.group(1))
            break

    # Extract species
    species = None
    # Check species aliases in order of specificity
    for alias, canonical in sorted(SPECIES_ALIASES.items(), key=lambda x: -len(x[0])):
        if alias in text_lower:
            species = canonical
            break

    if species is None:
        # Generic "fish" — use as-is
        if "fish" in text_lower or "catch" in text_lower:
            species = "fish"
        else:
            return None

    return {
        "species": species,
        "depth_fm": depth_fm,
        "count": count,
        "raw_text": text,
        "parsed_at_utc": datetime.now(timezone.utc).isoformat(),
    }


# ══════════════════════════════════════════════════════════════════════
#  Capture Finder (time proximity)
# ══════════════════════════════════════════════════════════════════════

def find_nearest_capture(
    ts_str: str,
    max_lookback_minutes: int = 60,
) -> Optional[Path]:
    """Find the capture closest to a given timestamp.

    Steps:
    1. Query Ship Log Search timeline to find recent echogram captures
    2. Sort by absolute time difference
    3. Return the capture JSON path for annotation

    Falls back to local filesystem scan if Ship Log Search unavailable.
    """
    try:
        # Try Ship Log Search first — it has the authoritative timeline
        params = f"?from={_ts_minus(ts_str, max_lookback_minutes)}&k=20"
        req = urllib.request.Request(
            SHIP_LOG_SEARCH_URL + params,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp = urllib.request.urlopen(req, timeout=SHIP_LOG_TIMEOUT_S)
        data = json.loads(resp.read())

        # Filter for echogram captures only
        candidates = []
        for entry in data.get("results", []):
            meta = entry.get("metadata", {})
            if not meta.get("capture_id"):
                continue  # not an echogram capture
            ct = meta.get("timestamp", "")
            if ct:
                diff = abs(_ts_diff_seconds(ct, ts_str))
                candidates.append((diff, meta))

        if candidates:
            candidates.sort(key=lambda x: x[0])
            best = candidates[0]
            log.info(
                "Nearest capture: %s (%.0fs away)",
                best[1]["capture_id"],
                best[0],
            )
            # Find the local JSON file
            capture_id = best[1]["capture_id"]
            day_folder = best[1].get("day_folder", "")
            if day_folder:
                js_path = CAPTURES_DIR / day_folder / f"{capture_id}.json"
                if js_path.exists():
                    return js_path

    except Exception as e:
        log.warning("Ship Log Search query failed: %s", e)

    # Fallback: scan local captures
    log.info("Falling back to local filesystem scan...")
    best_path = None
    best_diff = float("inf")
    target_ts = _parse_ts(ts_str)

    for day_dir in sorted(CAPTURES_DIR.iterdir()):
        if not day_dir.is_dir():
            continue
        for js_file in sorted(day_dir.glob("*.json")):
            try:
                meta = json.loads(js_file.read_text(encoding="utf-8"))
                ct = meta.get("ts_utc", "")
                if not ct:
                    continue
                diff = abs((target_ts - _parse_ts(ct)).total_seconds())
                if diff < best_diff:
                    best_diff = diff
                    best_path = js_file
            except (json.JSONDecodeError, KeyError):
                continue

    if best_path and best_diff < max_lookback_minutes * 60:
        log.info("Found capture: %s (%.0fs away)", best_path.name, best_diff)
        return best_path

    log.warning("No nearby capture found within %d min", max_lookback_minutes)
    return None


def _parse_ts(s: str) -> datetime:
    """Parse an ISO timestamp string, handling various formats."""
    s = s.strip()
    # Handle trailing Z and timezone offsets
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return datetime.now(timezone.utc)


def _ts_diff_seconds(a: str, b: str) -> float:
    return (_parse_ts(a) - _parse_ts(b)).total_seconds()


def _ts_minus(ts: str, minutes: int) -> str:
    dt = _parse_ts(ts) - timedelta(minutes=minutes)
    return dt.isoformat()


# ══════════════════════════════════════════════════════════════════════
#  Capture Annotation
# ══════════════════════════════════════════════════════════════════════

def annotate_capture(
    json_path: Path,
    catch_report: dict,
) -> bool:
    """Annotate a capture JSON with a catch report label.

    Labels are stored in analysis.vocabulary as an array of:
    {
      "species": "chum",
      "depth_fm": 35,
      "count": 15,
      "raw_text": "chum at 35 fm, 15 fish",
      "confidence": null,   # set by analyzer when vocabulary is built
      "linked_at_utc": "...",
    }

    schema_version is incremented to 3 when the first catch report attaches.
    Multiple reports can attach to the same capture (different species/depths).
    """
    try:
        meta = json.loads(json_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as e:
        log.error("Cannot read %s: %s", json_path.name, e)
        return False

    analysis = meta.setdefault("analysis", {})
    if analysis.get("vocabulary") is None:
        analysis["vocabulary"] = []
    vocab = analysis["vocabulary"]

    # Build the label
    label = {
        "species": catch_report["species"],
        "depth_fm": catch_report["depth_fm"],
        "count": catch_report["count"],
        "raw_text": catch_report["raw_text"],
        "confidence": None,  # populated by future analyzer run
        "linked_at_utc": catch_report["parsed_at_utc"],
    }

    # Check for duplicates (same species + same depth)
    for existing in vocab:
        if (
            existing.get("species") == label["species"]
            and existing.get("depth_fm") == label["depth_fm"]
        ):
            # Merge: average count, keep earliest link time
            old_count = existing.get("count") or 0
            new_count = label["count"] or 0
            if old_count and new_count:
                existing["count"] = (old_count + new_count) // 2
            elif new_count:
                existing["count"] = new_count
            existing["raw_text"] = label["raw_text"]
            log.info(
                "Merged duplicate label for %s at %d fm",
                label["species"],
                label["depth_fm"],
            )
            break
    else:
        vocab.append(label)
        # Increment schema_version if not already at 3+
        current_sv = analysis.get("schema_version", 0)
        if current_sv < 3:
            analysis["schema_version"] = 3
            log.info(
                "Schema version bumped to 3 (first catch label on %s)",
                meta.get("capture_id", "?"),
            )

    # Update caption to reflect catch report
    current_caption = analysis.get("caption", "")
    label_line = (
        f"Catch report: {label['count']} {label['species']}"
        f"{' at ' + str(label['depth_fm']) + ' fm' if label['depth_fm'] else ''}."
    )
    if current_caption and label_line not in current_caption:
        analysis["caption"] = current_caption.rstrip(".") + f" {label_line}"

    try:
        json_path.write_text(
            json.dumps(meta, indent=2, default=str),
            encoding="utf-8",
        )
        log.info("Annotated %s with %s", json_path.name, label_line)
        return True
    except Exception as e:
        log.error("Write failed: %s", e)
        return False


# ══════════════════════════════════════════════════════════════════════
#  Ship Log Update
# ══════════════════════════════════════════════════════════════════════

def post_catch_to_ship_log(catch_report: dict, meta: dict) -> None:
    """POST a catch report to Ship Log Search as a standalone entry.

    Also links it to the nearest capture via metadata.
    """
    try:
        capture_id = meta.get("capture_id", "unknown")
        pos = meta.get("position", {})
        ts = meta.get("ts_utc", datetime.now(timezone.utc).isoformat())

        payload = {
            "text": (
                f"Catch report: {catch_report['count']} {catch_report['species']}"
                f"{' at ' + str(catch_report['depth_fm']) + ' fm' if catch_report['depth_fm'] else ''}."
            ),
            "category": "catch",
            "timestamp": ts,
            "lat": pos.get("lat_dd"),
            "lon": pos.get("lon_dd"),
            "location_name": f"{pos.get('lat_ddmm', '?')}N/{pos.get('lon_ddmm', '?')}W",
            "id": f"catch_{capture_id}_{catch_report['species']}_{int(datetime.now().timestamp())}",
            "metadata": {
                "species": catch_report["species"],
                "depth_fm": catch_report["depth_fm"],
                "count": catch_report["count"],
                "linked_capture_id": capture_id,
                "linked_at_utc": catch_report["parsed_at_utc"],
            },
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            SHIP_LOG_URL,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=SHIP_LOG_TIMEOUT_S)
        log.info("Catch report posted to Ship Log Search: %s", payload["id"])

    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        log.warning("Ship Log catch post failed (non-blocking): %s", e)


# ══════════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════════

def cli() -> None:
    """CLI entry point for manual catch report linking."""
    args = sys.argv[1:]

    if not args or "-h" in args or "--help" in args:
        print("Usage:")
        print("  python catch_link.py link <species> <depth_fm> <count>")
        print("                             [--ts <ISO-timestamp>]")
        print("                             [--text \"raw catch report\"]")
        print("  python catch_link.py parse \"catch report text\"")
        print()
        print("Examples:")
        print('  python catch_link.py link chum 35 15')
        print('  python catch_link.py link sockeye 25 8 --ts "2026-07-17T20:40:00Z"')
        print('  python catch_link.py parse "chum at 35 fm, 15 fish"')
        return

    if args[0] == "parse":
        text = " ".join(args[1:])
        if not text:
            text = input("Catch report text: ")
        result = parse_catch_report(text)
        if result:
            print(json.dumps(result, indent=2))
        else:
            print("Could not parse as catch report.")
        return

    if args[0] == "link":
        species = args[1] if len(args) > 1 else None
        depth_fm = int(args[2]) if len(args) > 2 else None
        count = int(args[3]) if len(args) > 3 else None
        raw_text = None
        ts = datetime.now(timezone.utc).isoformat()

        i = 4
        while i < len(args):
            if args[i] == "--ts" and i + 1 < len(args):
                ts = args[i + 1]
                i += 2
            elif args[i] == "--text" and i + 1 < len(args):
                raw_text = args[i + 1]
                i += 2
            else:
                i += 1

        if not all([species, count is not None]):
            print("Need: species, count. Depth optional.")
            return

        report = {
            "species": species.lower(),
            "depth_fm": depth_fm,
            "count": count,
            "raw_text": raw_text or f"{species} at {depth_fm} fm, {count} fish",
            "parsed_at_utc": datetime.now(timezone.utc).isoformat(),
        }

        print(f"Linking: {json.dumps(report, indent=2)}")
        print(f"Timestamp: {ts}")

        json_path = find_nearest_capture(ts)
        if not json_path:
            print("No nearby capture found.")
            return

        annotate_capture(json_path, report)

        meta = json.loads(json_path.read_text(encoding="utf-8"))
        post_catch_to_ship_log(report, meta)

        log.info("Catch linked to %s", json_path.name)


if __name__ == "__main__":
    cli()
