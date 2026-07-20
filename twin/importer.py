"""
twin/importer.py

Walks captures/v3/** to import frames into the data twin.

Idempotent re-runs: same sha256 returns existing frame_id.
Maps existing analysis JSON into echogram_records where present.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


class Importer:
    """Import frames from captures/v3/ directory into the twin."""

    def __init__(self, twin) -> None:
        """
        Initialize the importer.

        Args:
            twin: A Twin instance.
        """
        self._twin = twin

    def import_captures_v3(
        self,
        captures_dir: Path,
        print_summary: bool = True
    ) -> dict[str, int]:
        """
        Walk captures/v3/** and import all PNG + JSON sidecar pairs.

        Args:
            captures_dir: Path to captures/v3/ directory.
            print_summary: If True, print a summary report.

        Returns:
            Dictionary with import statistics.
        """
        if not self._twin.conn:
            raise RuntimeError("Twin not open. Call open() first.")

        stats = {
            "total_found": 0,
            "imported": 0,
            "skipped_duplicate": 0,
            "skipped_no_sidecar": 0,
            "records_added": 0,
            "errors": 0
        }

        captures_path = Path(captures_dir)
        if not captures_path.exists():
            if print_summary:
                print(f"Captures directory does not exist: {captures_path}")
            return stats

        # Walk recursively
        for png_path in captures_path.rglob("*.png"):
            stats["total_found"] += 1

            # Look for corresponding JSON sidecar
            json_path = png_path.with_suffix(".json")

            if not json_path.exists():
                stats["skipped_no_sidecar"] += 1
                continue

            # Load sidecar
            try:
                sidecar = json.loads(json_path.read_text())
            except Exception as e:
                if print_summary:
                    print(f"Error reading sidecar {json_path}: {e}")
                stats["errors"] += 1
                continue

            # Import the frame
            try:
                result = self._twin.add_frame(
                    png_path=png_path,
                    sidecar=sidecar,
                    cadence=sidecar.get("cadence", "30s")
                )

                if result.is_new:
                    stats["imported"] += 1
                else:
                    stats["skipped_duplicate"] += 1

                # Look for analysis JSON
                analysis_path = png_path.with_suffix(".analysis.json")
                if analysis_path.exists():
                    self._import_analysis(result.frame_id, analysis_path, stats)

            except Exception as e:
                if print_summary:
                    print(f"Error importing {png_path}: {e}")
                stats["errors"] += 1

        if print_summary:
            self._print_summary(stats)

        return stats

    def _import_analysis(self, frame_id: str, analysis_path: Path, stats: dict) -> None:
        """
        Import analysis JSON as an echogram_record.

        Args:
            frame_id: The frame_id to attach the record to.
            analysis_path: Path to the .analysis.json file.
            stats: Statistics dict to update.
        """
        try:
            analysis = json.loads(analysis_path.read_text())

            # Convert to record format
            record = {
                "ts_utc": analysis.get("ts_utc"),
                "depth_top_m": analysis.get("depth_top_m"),
                "depth_bot_m": analysis.get("depth_bot_m"),
                "vocab_terms": analysis.get("vocab_terms"),
                "model": analysis.get("model"),
                "confidence": analysis.get("confidence"),
                "raw": analysis  # Store full analysis in record_json
            }

            self._twin.add_record(frame_id, record)
            stats["records_added"] += 1

        except Exception:
            pass  # Skip failed analysis imports

    def _print_summary(self, stats: dict) -> None:
        """Print a summary of the import."""
        print("\n=== Data Twin Import Summary ===")
        print(f"Total PNG files found:    {stats['total_found']}")
        print(f"New frames imported:      {stats['imported']}")
        print(f"Skipped (duplicate):      {stats['skipped_duplicate']}")
        print(f"Skipped (no sidecar):     {stats['skipped_no_sidecar']}")
        print(f"Records added:            {stats['records_added']}")
        print(f"Errors:                   {stats['errors']}")
        print("================================\n")


def import_main(captures_dir: str, memory_dir: str) -> None:
    """
    CLI entry point for import.

    Args:
        captures_dir: Path to captures/v3/ directory.
        memory_dir: Path to memory/ directory.
    """
    from .twin import Twin

    twin = Twin(Path(memory_dir))

    with twin:
        importer = Importer(twin)
        stats = importer.import_captures_v3(Path(captures_dir))


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python -m twin.importer <captures_dir> <memory_dir>")
        sys.exit(1)

    import_main(sys.argv[1], sys.argv[2])
