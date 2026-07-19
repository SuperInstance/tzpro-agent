#!/usr/bin/env python3
"""memory_recall.py — Custom recall optimizations for the hermit memory system.

This module is how I, as the ship's AI, actually USE the memory system
day-to-day. It's not a generic memory pipeline — it's optimized for:

1. **Pattern matching**: Given current conditions, what's the closest match
   in stipes or holdfast?
2. **Morning recall**: When the analyzer starts for a new day, what happened
   yesterday at this time?
3. **Day summary**: At end of day, what did we learn?
4. **Memory-aware captions**: Generate a sentence about past conditions
   matching the present.

Usage:
  python memory_recall.py match <json_path>   -- find similar past conditions
  python memory_recall.py recall <hour>       -- what happened at this hour yesterday
  python memory_recall.py summary             -- today's memory summary
  python memory_recall.py caption <json_path> -- memory-aware caption sentence
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

log = logging.getLogger("memory_recall")
HERE = Path(__file__).parent.resolve()
LOCAL_TZ = timezone(timedelta(hours=-8))


def _load_stipes() -> list[dict]:
    """Load all stipes entries for matching."""
    path = HERE / ".stipes_memory.jsonl"
    if not path.exists():
        return []
    entries = []
    try:
        for line in path.read_text("utf-8").strip().splitlines():
            if line.strip():
                entries.append(json.loads(line))
    except (json.JSONDecodeError, OSError):
        pass
    return entries


def _load_holdfast() -> dict[str, list]:
    """Load holdfast entries for recall."""
    path = HERE / ".holdfast.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def find_matches(current: dict[str, Any], entries: list[dict], top_n: int = 3) -> list[dict]:
    """Find stipes entries with similar blob_count and boat proximity."""
    current_blobs = current.get("blob_count", 0)
    current_boats = current.get("boats", 0)
    current_feed = current.get("feed_present", False)

    scored = []
    for entry in entries:
        payload = entry.get("payload", {})
        summary = payload.get("summary", {})
        if not summary:
            continue
        blobs_diff = abs(summary.get("blob_count", 0) - current_blobs)
        boats_match = 1.0 if (summary.get("boats", 0) > 0) == (current_boats > 0) else 0.0
        feed_match = 1.0 if summary.get("feed_present") == current_feed else 0.0
        blobs_score = max(0, 1.0 - (blobs_diff / 500.0))
        score = blobs_score * 0.4 + boats_match * 0.3 + feed_match * 0.3
        scored.append({"entry": entry, "score": round(score, 3)})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_n]


def match_capture(json_path: Path) -> dict[str, Any]:
    """Find similar past conditions to the current capture."""
    try:
        data = json.loads(json_path.read_text("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"status": "error", "error": "cannot read capture"}

    heuristic = data.get("analysis", {}).get("heuristic", {})
    lf = heuristic.get("lf", {})
    hf = heuristic.get("hf", {})

    current = {
        "blob_count": lf.get("blob_count", 0),
        "boats": lf.get("boat_proximity", {}).get("vertical_line_count", 0),
        "feed_present": hf.get("haze", {}).get("feed_present", False),
        "bottom_depth": (lf.get("bottom") or {}).get("bottom_depth_fm"),
    }

    stipes = _load_stipes()
    matches = find_matches(current, stipes)

    return {
        "status": "ok",
        "capture_id": data.get("capture_id", ""),
        "current": current,
        "matches": [
            {
                "score": m["score"],
                "kind": m["entry"].get("kind", ""),
                "summary": m["entry"].get("payload", {}).get("summary", {}),
                "graduated_at": m["entry"].get("graduated_at", 0),
            }
            for m in matches if m["score"] > 0.3
        ],
    }


def recall_hour(hour: int, day_offset: int = -1) -> dict[str, Any]:
    """Recall what happened at a given hour yesterday (or N days ago)."""
    target = datetime.now(LOCAL_TZ) + timedelta(days=day_offset)
    date_str = target.strftime("%Y-%m-%d")
    day_dirs = sorted(HERE.glob(f"captures/v3/{date_str}_*"))
    if not day_dirs:
        return {"status": "empty", "note": f"No captures from {date_str}"}

    hour_str = f"{hour:02d}"
    recall = []
    for day_dir in day_dirs:
        for js in day_dir.glob(f"{hour_str}*.json"):
            try:
                data = json.loads(js.read_text("utf-8"))
                caption = data.get("analysis", {}).get("caption", "")
                pos = data.get("position", {})
                recall.append({
                    "capture_id": data.get("capture_id", ""),
                    "time": data.get("ts_local", ""),
                    "lat": pos.get("lat_ddmm", ""),
                    "lon": pos.get("lon_ddmm", ""),
                    "sog": pos.get("sog_kts"),
                    "caption": caption[:120],
                })
            except (json.JSONDecodeError, OSError):
                continue

    return {
        "status": "ok" if recall else "empty",
        "date": date_str,
        "hour": hour,
        "captures": sorted(recall, key=lambda r: r["capture_id"]),
    }


def day_summary(date_str: str | None = None) -> dict[str, Any]:
    """Summarize what was learned on a given day."""
    if date_str is None:
        date_str = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")

    day_dirs = sorted(HERE.glob(f"captures/v3/{date_str}_*"))
    if not day_dirs:
        return {"status": "empty", "date": date_str}

    total_captures = 0
    total_blobs = 0
    max_blobs = 0
    max_blobs_capture = ""
    boat_captures = 0
    feed_captures = 0

    for day_dir in day_dirs:
        for js in sorted(day_dir.glob("*.json")):
            try:
                data = json.loads(js.read_text("utf-8"))
                total_captures += 1
                heuristic = data.get("analysis", {}).get("heuristic", {})
                lf = heuristic.get("lf", {})
                hf = heuristic.get("hf", {})
                bc = lf.get("blob_count", 0)
                total_blobs += bc
                if bc > max_blobs:
                    max_blobs = bc
                    max_blobs_capture = data.get("capture_id", "")
                if lf.get("boat_proximity", {}).get("vertical_line_count", 0) > 0:
                    boat_captures += 1
                if hf.get("haze", {}).get("feed_present", False):
                    feed_captures += 1
            except (json.JSONDecodeError, OSError):
                continue

    return {
        "status": "ok",
        "date": date_str,
        "captures": total_captures,
        "total_blobs": total_blobs,
        "avg_blobs_per_capture": round(total_blobs / max(total_captures, 1)),
        "max_blobs": max_blobs,
        "max_blobs_capture": max_blobs_capture,
        "boat_pct": round(boat_captures / max(total_captures, 1) * 100),
        "feed_pct": round(feed_captures / max(total_captures, 1) * 100),
    }


def caption_sentence(json_path: Path) -> str:
    """Generate a memory-aware one-liner for the analyzer's caption. No emoji, ASCII-safe."""
    match = match_capture(json_path)
    if match.get("status") != "ok" or not match.get("matches"):
        return ""

    top = match["matches"][0]
    if top["score"] < 0.3:
        return ""

    summary = top.get("summary", {})
    kind = top.get("kind", "pattern")

    parts = []
    boats = summary.get("boats", 0)
    if boats > 0:
        parts.append(f"while boats were near ({boats} lines)")
    if summary.get("feed_present"):
        parts.append("with feed present")
    blobs = summary.get("blob_count", 0)
    if blobs > 0:
        parts.append(f"at {blobs} echo returns")

    context = ", ".join(parts) if parts else "under similar conditions"
    return f"[Memory] Match ({top['score']:.0%}) with {kind} from earlier {context}."


# ══════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════

def cli() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print("Usage: python memory_recall.py <command> [args]")
        print("  match <json_path>     -- find similar past conditions")
        print("  recall <hour>         -- what happened at this hour yesterday")
        print("  summary [date]        -- day summary (default: today)")
        print("  caption <json_path>   -- memory-aware caption sentence")
        return

    cmd = sys.argv[1]

    if cmd == "match" and len(sys.argv) >= 3:
        result = match_capture(Path(sys.argv[2]))
        if result.get("status") == "ok":
            print(f"Capture: {result['capture_id']}")
            print(f"  Blobs: {result['current']['blob_count']}, Boats: {result['current']['boats']}, Feed: {result['current']['feed_present']}")
            if result.get("matches"):
                top = result["matches"][0]
                print(f"  Top match: {top['score']:.0%} confidence ({top['kind']})")
        else:
            print("No matches found")

    elif cmd == "recall" and len(sys.argv) >= 3:
        hour = int(sys.argv[2])
        day_offset = int(sys.argv[3]) if len(sys.argv) >= 4 else -1
        result = recall_hour(hour, day_offset)
        print(f"Yesterday at {hour}:00 ({result['date']})")
        for c in result.get("captures", []):
            print(f"  {c['capture_id'][:20]:20s} {c['lat']} {c['lon']}")
        if not result.get("captures"):
            print(f"  No captures from {result['date']}")

    elif cmd == "summary":
        date_str = sys.argv[2] if len(sys.argv) >= 3 else None
        result = day_summary(date_str)
        if result["status"] == "ok":
            print(f"Day Summary: {result['date']}")
            print(f"  Captures: {result['captures']}")
            print(f"  Avg blobs/capture: {result['avg_blobs_per_capture']}")
            print(f"  Max blob density: {result['max_blobs']} ({result['max_blobs_capture']})")
            print(f"  Boats detected: {result['boat_pct']}% of captures")
            print(f"  Feed present: {result['feed_pct']}% of captures")
        else:
            print(f"No captures from {result['date']}")

    elif cmd == "caption" and len(sys.argv) >= 3:
        sentence = caption_sentence(Path(sys.argv[2]))
        print(sentence if sentence else "(no matching memory)")

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    cli()
