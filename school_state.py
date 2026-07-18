"""school_state.py -- Classify school behavior from recent captures.

Takes list of dicts with blob_count, mean_depth_fm.
Returns {state: "holding"/"building"/"dispersing"/"migrating"/"absent",
         confidence: 0-1, evidence: list}.

Logic:
  holding    -- blobs within +-20%
  building   -- >=+20% over 3 frames
  dispersing -- <=-20% over 3 frames
  migrating  -- mean depth shift >5 fm
  absent     -- blobs <3
"""

from __future__ import annotations


def classify_school(
    captures: list[dict] | None = None,
    n_frames: int = 10,
) -> dict:
    """Classify school state from a list of capture snapshots or from disk.

    Each capture dict should have:
      - blob_count: int
      - mean_depth_fm: float | None

    Returns:
        state: "holding" | "building" | "dispersing" | "migrating" | "absent"
        confidence: 0.0 - 1.0
        evidence: list of human-readable strings explaining classification
    """
    if not captures:
        return {
            "state": "absent",
            "confidence": 1.0,
            "evidence": ["No capture data available -- assuming absent."],
        }

    blob_counts = [c.get("blob_count", 0) for c in captures]
    depths = [c.get("mean_depth_fm") for c in captures
              if c.get("mean_depth_fm") is not None]

    evidence: list[str] = []

    # Absent check
    if all(bc < 3 for bc in blob_counts):
        return {
            "state": "absent",
            "confidence": 0.9,
            "evidence": [f"All {len(blob_counts)} frames have < 3 blobs."],
        }

    # Need at least 3 frames for trend
    if len(blob_counts) < 3:
        avg_bc = sum(blob_counts) / len(blob_counts)
        evidence.append(f"Only {len(blob_counts)} frames available -- limited trend.")
        return {
            "state": "holding",
            "confidence": 0.4,
            "evidence": evidence,
        }

    recent_bc = blob_counts[-3:]
    early_bc = blob_counts[:3]

    avg_recent = sum(recent_bc) / len(recent_bc)
    avg_early = sum(early_bc) / len(early_bc)

    ratio = avg_recent / max(avg_early, 1)

    # Building
    if ratio >= 1.20:
        change_pct = (ratio - 1) * 100
        upward = _trend_direction(recent_bc) > 0
        conf = min(1.0, 0.5 + abs(ratio - 1) * 3)
        if not upward:
            conf *= 0.6
        evidence.append(
            f"Blob count grew from ~{avg_early:.0f} to ~{avg_recent:.0f} "
            f"(+{change_pct:.0f}%){' (upward trend)' if upward else ''}."
        )
        return {"state": "building", "confidence": round(conf, 2), "evidence": evidence}

    # Dispersing
    if ratio <= 0.80:
        change_pct = (1 - ratio) * 100
        downward = _trend_direction(recent_bc) < 0
        conf = min(1.0, 0.5 + abs(1 - ratio) * 3)
        if not downward:
            conf *= 0.6
        evidence.append(
            f"Blob count fell from ~{avg_early:.0f} to ~{avg_recent:.0f} "
            f"(-{change_pct:.0f}%){' (downward trend)' if downward else ''}."
        )
        return {"state": "dispersing", "confidence": round(conf, 2), "evidence": evidence}

    # Migrating
    if depths and len(depths) >= 2:
        depth_first = depths[0]
        depth_last = depths[-1]
        depth_shift = abs(depth_last - depth_first)
        if depth_shift > 5.0:
            direction = "deeper" if depth_last > depth_first else "shallower"
            conf = min(1.0, 0.4 + depth_shift / 5.0 * 0.6)
            evidence.append(
                f"Mean depth shifted from {depth_first:.1f} fm to "
                f"{depth_last:.1f} fm ({direction}, {depth_shift:.1f} fm)."
            )
            return {"state": "migrating", "confidence": round(conf, 2), "evidence": evidence}

    # Holding (default)
    holding_deviation = max(blob_counts) / max(min(blob_counts), 1)
    conf = max(0.3, min(1.0, 1.5 - holding_deviation * 0.5))
    evidence.append(
        f"Blob count stable around ~{avg_recent:.0f} "
        f"(range {min(blob_counts)}-{max(blob_counts)}, ratio {holding_deviation:.1f}x)."
    )
    return {"state": "holding", "confidence": round(conf, 2), "evidence": evidence}


def _trend_direction(values: list[float]) -> int:
    """Return +1 if upward trend, -1 if downward, 0 if flat."""
    if len(values) < 2:
        return 0
    up = sum(1 for i in range(1, len(values)) if values[i] > values[i-1])
    down = sum(1 for i in range(1, len(values)) if values[i] < values[i-1])
    if up > down:
        return 1
    if down > up:
        return -1
    return 0
