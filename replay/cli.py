"""replay/cli.py — command-line interface for replay v0.

Usage:
    python -m replay.cli <twin_root> <date> [--model]

Output:
    Compact human-readable report with agreement rate, disagreement examples,
    and verdict (PASS >= 0.8, DRIFT < 0.8).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import replay


def print_report(report: dict, verbose: bool = False) -> None:
    """Print a compact human-readable report.

    Args:
        report: The structured report from replay_day
        verbose: If True, print all frames; otherwise just top 5 disagreements
    """
    date = report["date"]
    total_frames = report["frames"]
    replayed = report["replayed"]
    agreement_rate = report["agreement_rate"]

    # Header
    print(f"\n{'='*60}")
    print(f"REPLAY REPORT — {date}")
    print(f"{'='*60}")

    # Summary stats
    print(f"Frames:     {total_frames}")
    print(f"Replayed:   {replayed}")
    print(f"Agreement:  {agreement_rate:.1%}")

    # Disagreements
    disagreements = [pf for pf in report["per_frame"] if pf.get("agree") is False]
    if disagreements:
        print(f"\nDisagreements ({len(disagreements)}):")
        print(f"{'-'*60}")

        # Show top 5 (or all if verbose)
        shown = disagreements if verbose else disagreements[:5]

        for i, diff in enumerate(shown, 1):
            frame_id = diff["frame_id"]
            print(f"\n[{i}] Frame: {frame_id}")

            for delta in diff.get("deltas", []):
                field = delta.get("field", "unknown")

                if field == "bottom_type":
                    print(f"    bottom_type: stored={delta['stored']} vs fresh={delta['fresh']}")
                elif field == "bottom_fm":
                    print(f"    bottom_fm: stored={delta['stored']} vs fresh={delta['fresh']} (delta={delta['delta'])")
                elif field == "search_terms":
                    stored = delta.get("stored", [])
                    fresh = delta.get("fresh", [])
                    jaccard = delta.get("jaccard", 0.0)
                    print(f"    search_terms: Jaccard={jaccard}")
                    print(f"      stored: {stored}")
                    print(f"      fresh:  {fresh}")
                else:
                    print(f"    {field}: {delta}")
    else:
        print("\n✓ No disagreements found")

    # Verdict
    verdict = "PASS" if agreement_rate >= 0.8 else "DRIFT"
    status_symbol = "✓" if verdict == "PASS" else "⚠"
    print(f"\n{status_symbol} Verdict: {verdict}")

    # Show skipped frames if any
    skipped = [pf for pf in report["per_frame"] if pf.get("agree") is None]
    if skipped:
        print(f"\nNote: {len(skipped)} frames skipped (no stored record or blob missing)")


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Replay perception analysis over stored twin data"
    )
    parser.add_argument(
        "twin_root",
        type=Path,
        help="Path to twin directory (contains meta.db)"
    )
    parser.add_argument(
        "date",
        help="Date to replay in YYYY-MM-DD format"
    )
    parser.add_argument(
        "--model",
        action="store_true",
        help="Use actual vision model (cascade ollama) instead of stub"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show all disagreements (not just top 5)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON report instead of human-readable"
    )

    args = parser.parse_args()

    try:
        # Choose analyzer
        if args.model:
            analyzer = replay._model_analyzer(args.twin_root)
        else:
            analyzer = None  # Use stub

        # Run replay
        report = replay.replay_day(args.twin_root, args.date, analyzer)

        # Output
        if args.json:
            # Sort keys for deterministic output
            print(json.dumps(report, sort_keys=True, indent=2))
        else:
            print_report(report, args.verbose)

        return 0 if report["agreement_rate"] >= 0.8 else 1

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
