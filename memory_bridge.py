#!/usr/bin/env python3
"""memory_bridge.py — Wires the hermit memory system into the analyzer pipeline.

Called from analyzer.py Phase 12 after each capture analysis completes.
Reads the three memory layers (tide_pool → stipes → holdfast) and
integrates them into the live capture pipeline.

Usage:
  python memory_bridge.py process <json_path>   # Called after capture analysis
  python memory_bridge.py tick                  # Called from run_forever loop
  python memory_bridge.py migrate               # Manual holdfast migration
  python memory_bridge.py status                # Full memory system status
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("memory_bridge")
HERE = Path(__file__).parent.resolve()


def get_tide_pool():
    """Lazy import tide_pool to avoid circular imports."""
    from tide_pool import TidePool
    return TidePool()


def get_stipes():
    """Lazy import stipes."""
    from stipes import StipesDB
    return StipesDB()


def get_holdfast():
    """Lazy import holdfast."""
    from holdfast import Holdfast
    return Holdfast()


# ── Integration points ──────────────────────────────────────────────

def process_capture(json_path: Path) -> dict[str, Any]:
    """Called after analyzer.py completes a capture analysis.

    Steps:
    1. Read the analysis JSON
    2. Add capture summary to tide pool
    3. Reinforce notable captures (boats nearby, haze present, high blob count)
    4. Maybe flush tide pool -> stipes
    5. Log memory status
    """
    try:
        data = json.loads(json_path.read_text("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return {"status": "error", "error": str(e)}

    analysis = data.get("analysis", {})
    heuristic = analysis.get("heuristic", {})
    lf = heuristic.get("lf", {})
    hf = heuristic.get("hf", {})

    # Build summary for tide pool
    summary = {
        "capture_id": data.get("capture_id", ""),
        "ts_local": data.get("ts_local", ""),
        "blob_count": lf.get("blob_count", 0),
        "boats": lf.get("boat_proximity", {}).get("vertical_line_count", 0),
        "feed_present": hf.get("haze", {}).get("feed_present", False),
        "feed_intensity": hf.get("haze", {}).get("feed_intensity", "none"),
        "bottom_depth": (lf.get("bottom") or {}).get("bottom_depth_fm"),
        "mid_zone_mean": lf.get("zone_profiles", {}).get("mid", {}).get("mean_intensity", 0),
        "thermocline_count": lf.get("thermocline_count", 0),
    }

    tp = get_tide_pool()
    tp.add_capture_analysis(summary)

    # Auto-reinforce for notable patterns
    reinforced = []
    if summary["boats"] >= 5:
        tp.reinforce_capture()
        reinforced.append("boats")
    if summary["feed_present"]:
        tp.reinforce_capture()
        reinforced.append("feed")
    if summary["blob_count"] > 100:
        tp.reinforce_capture()
        reinforced.append("high_density")

    # Also reinforce feed_haze state separately
    if summary["feed_present"]:
        tp.update_feed_haze(active=True, confidence=0.7)
        tp.reinforce_feed_haze()

    # If boats present, also reinforce boat proximity
    if summary["boats"] > 0:
        tp.update_boat_proximity(count_within_1km=min(summary["boats"] // 5, 10))
        tp.reinforce_boat_proximity()

    # Try flush
    result = tp.maybe_flush()

    if result:
        log.info(
            "Memory flush: %d graduated, %d dropped",
            result.get("graduated_count", 0),
            result.get("dropped_count", 0),
        )

    # Check stipes graduation queue
    stipes = get_stipes()
    stipes_stats = stipes.stats()

    return {
        "status": "ok",
        "capture_id": summary["capture_id"],
        "reinforced": reinforced,
        "flushed": result is not None,
        "graduated": result.get("graduated_count", 0) if result else 0,
        "stipes_total": sum(stipes_stats.values()) if stipes_stats else 0,
    }


def tick() -> dict[str, Any]:
    """Called from analyzer.py's run_forever loop periodically.

    Checks tide pool for auto-flush, migrates holdfast queue.
    """
    report = {"tide_ok": False, "stipes_ok": False, "holdfast_ok": False}

    # Tide pool flush check
    try:
        tp = get_tide_pool()
        result = tp.maybe_flush()
        report["tide_ok"] = True
        if result:
            log.info(
                "Tick flush: %d graduated, %d dropped",
                result.get("graduated_count", 0),
                result.get("dropped_count", 0),
            )
    except Exception as e:
        log.debug("Tide pool tick error: %s", e)

    # Stipes prune
    try:
        stipes = get_stipes()
        pruned = stipes.prune(threshold=0.001)
        report["stipes_ok"] = True
        if pruned > 0:
            log.info("Stipes pruned %d decayed entries", pruned)
    except Exception as e:
        log.debug("Stipes tick error: %s", e)

    # Holdfast migration
    try:
        from holdfast import Holdfast
        hf = Holdfast()
        migrated = hf.migrate()
        report["holdfast_ok"] = True
        if migrated > 0:
            log.info("Holdfast migrated %d new permanent entries", migrated)
    except Exception as e:
        log.debug("Holdfast tick error: %s", e)

    return report


def migrate_holdfast() -> dict[str, Any]:
    """Manually drain the holdfast graduation queue."""
    from holdfast import Holdfast
    hf = Holdfast()
    count = hf.migrate()
    log.info("Manual migration: %d entries -> holdfast", count)
    return {"migrated": count, "total": len(hf)}


def status() -> dict[str, Any]:
    """Full memory system diagnostic."""
    try:
        tp = get_tide_pool()
        tp_status = tp.status()
    except Exception as e:
        tp_status = {"error": str(e)}

    try:
        stipes = get_stipes()
        sti = stipes.stats()
    except Exception as e:
        sti = {"error": str(e)}

    try:
        from holdfast import Holdfast
        hf = Holdfast()
        hf_stats = hf.stats()
        queue_len = len(hf.read_queue())
    except Exception as e:
        hf_stats = {"error": str(e)}
        queue_len = 0

    return {
        "tide_pool": tp_status,
        "stipes": sti,
        "holdfast": hf_stats,
        "graduation_queue": queue_len,
    }


# ══════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════

def cli() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print("Usage: python memory_bridge.py <command> [args]")
        print()
        print("Commands:")
        print("  process <json_path>  Called after capture analysis")
        print("  tick                 Called from run_forever loop")
        print("  migrate              Manual holdfast migration")
        print("  status               Full memory system status")
        return

    cmd = sys.argv[1]

    if cmd == "process" and len(sys.argv) >= 3:
        result = process_capture(Path(sys.argv[2]))
        print(json.dumps(result, indent=2))

    elif cmd == "tick":
        result = tick()
        print(json.dumps(result, indent=2))

    elif cmd == "migrate":
        result = migrate_holdfast()
        print(json.dumps(result, indent=2))

    elif cmd == "status":
        result = status()
        print(json.dumps(result, indent=2, default=str))

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    cli()
