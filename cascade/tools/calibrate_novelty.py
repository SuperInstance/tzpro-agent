"""cascade/tools/calibrate_novelty.py — replay candidate retention rules
against EXISTING minute notes, no inference needed (docs/research/
NOVELTY_CALIBRATION.md §5).

Usage: python -m cascade.tools.calibrate_novelty [notes_dir]
Prints a retention table per threshold and the kept frames for the
recommended rule (0.85 OR-of-three).
"""
from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path

DEPTH_RE = re.compile(
    r"(approximately|at)\s+\d+\s*(fm|fathoms?|m\b|met[er]+s?)", re.IGNORECASE
)
DISTINCT_WORDS = {"distinct", "localized", "concentrated", "dense", "sharp", "hard", "sudden"}
FEATURE_SET = {"blob school", "bottom hardness change", "thermocline break",
               "surface noise", "dense schools"}


def retain(note: dict, thr: float) -> dict[str, bool]:
    """The OR-of-three rule. Returns the per-clause verdicts."""
    caption = (note.get("caption") or "").lower()
    features = [f.lower() for f in (note.get("features") or [])]
    score = (note.get("novelty") or 0.0) >= thr
    depth = bool(DEPTH_RE.search(note.get("caption") or ""))
    combo = (
        sum(1 for f in features if f in FEATURE_SET) >= 2
        and any(w in caption for w in DISTINCT_WORDS)
    )
    return {"score": score, "depth": depth, "combo": combo, "keep": score or depth or combo}


def main() -> None:
    notes_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        r"C:\Users\casey\.openclaw\workspace\tzpro-agent\cascade_out\minute_notes\novel"
    )
    notes = [json.loads(p.read_text()) for p in sorted(notes_dir.glob("*.json"))]
    if not notes:
        print(f"no notes found in {notes_dir}")
        return

    print(f"corpus: {len(notes)} notes from {notes_dir}\n")
    print(f"{'thr':>5} | {'score-only':>10} | {'OR-of-three':>11}")
    print("-" * 34)
    for thr in [0.65, 0.70, 0.75, 0.80, 0.85, 0.90]:
        score_kept = sum(1 for n in notes if (n.get("novelty") or 0) >= thr)
        rule_kept = sum(1 for n in notes if retain(n, thr)["keep"])
        print(f"{thr:>5.2f} | {score_kept:>4}/{len(notes):<5} | {rule_kept:>4}/{len(notes):<6}")

    print("\nkept by the recommended rule (thr=0.85, OR-of-three):")
    for n in notes:
        v = retain(n, 0.85)
        if v["keep"]:
            why = "+".join(k for k in ("score", "depth", "combo") if v[k])
            print(f"  [{why:>17}] {(n.get('caption') or '')[:90]}")


if __name__ == "__main__":
    main()
