#!/usr/bin/env python3
"""vocabulary.py — Aggregated echogram vocabulary with confidence scoring.

Phase 5 of the capture pipeline. Accumulates catch report labels across
all captures and computes confidence scores for species-at-depth patterns.

DESIGN:
- Vocabulary is aggregated from ALL captures (analysis.vocabulary arrays)
- For each (species, depth_zone) pair, tracks: count, how many reports,
  average intensity of matching blobs
- Confidence is Bayesian: how many reports for this species at this depth
  vs other species at the same depth — weighted by proximity in time
- The analyzer calls vocabulary.lookup(depth_fm) to get predicted species
  and confidence for each blob it detects

BAYESIAN CONFIDENCE MODEL:
    P(species | depth_zone) = reports(species, zone) / total_reports(zone)
    
    Adjusted with Laplace smoothing:
    P = (reports(species, zone) + alpha) / (total_reports(zone) + alpha * N_species)
    where alpha = 1 (add-one smoothing), N_species = number of known species

    Final confidence is clamped to [0.05, 0.95]:
    - Confidence < 0.1 → species is "unidentified"
    - Confidence 0.1-0.4 → "possible <species>"
    - Confidence 0.4-0.7 → "likely <species>"
    - Confidence > 0.7 → <species> (no qualifier)

USAGE:
    python vocabulary.py summarize              # Print aggregated vocabulary
    python vocabulary.py lookup 35              # What's at 35 fm?
    python vocabulary.py lookup 35 --zone mid   # With zone context
    python vocabulary.py rebuild                # Re-scan all captures and rebuild cache
"""

from __future__ import annotations

import json
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

CAPTURES_DIR = Path(__file__).parent.resolve() / "captures" / "v3"
VOCAB_CACHE = Path(__file__).parent.resolve() / ".vocabulary_cache.json"

# Depth zones (matching analyzer.py)
ZONES: dict[str, tuple[float, float]] = {
    "surface": (0, 5),
    "upper": (5, 20),
    "mid": (20, 40),
    "lower": (40, 55),
    "floor": (55, 60),
}

# Confidence thresholds
CONF_UNIDENTIFIED = 0.1
CONF_POSSIBLE = 0.4
CONF_LIKELY = 0.7

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("vocabulary")


# ══════════════════════════════════════════════════════════════════════
#  Depth Zone Utils
# ══════════════════════════════════════════════════════════════════════

def depth_to_zone(depth_fm: float) -> Optional[str]:
    """Map a depth in fm to a named zone."""
    for zone_name, (z_start, z_end) in ZONES.items():
        if z_start <= depth_fm < z_end:
            return zone_name
    return None


def zone_range(zone_name: str) -> tuple[float, float]:
    """Return the depth range for a named zone."""
    return ZONES.get(zone_name, (0, 60))


# ══════════════════════════════════════════════════════════════════════
#  Vocabulary Aggregation
# ══════════════════════════════════════════════════════════════════════

def aggregate_vocabulary(force_rebuild: bool = False) -> dict:
    """Aggregate catch report labels from all captures.

    Returns a dict:
    {
        "species_list": ["chum", "sockeye", ...],
        "species_map": {
            "chum": {
                "zones": {
                    "mid": {
                        "count": 15,
                        "reports": 1,
                        "avg_count": 15.0,
                        "depths": [35.0],
                    }
                },
                "total_reports": 1,
                "total_caught": 15,
            }
        },
        "zone_species": {
            "mid": {
                "total_reports": 1,
                "chum": {"reports": 1, "count": 15},
            }
        },
        "timestamp": "2026-07-17T22:50:00Z",
        "total_labels": 1,
    }
    """
    if not force_rebuild:
        cached = try_load_cache()
        if cached:
            return cached

    species_map: dict = defaultdict(lambda: {
        "zones": defaultdict(lambda: {"count": 0, "reports": 0, "depths": []}),
        "total_reports": 0,
        "total_caught": 0,
    })
    zone_species: dict = defaultdict(lambda: {"total_reports": 0})
    total_labels = 0
    captures_scanned = 0

    if not CAPTURES_DIR.exists():
        log.warning("Captures directory not found: %s", CAPTURES_DIR)
        return build_empty()

    for day_dir in sorted(CAPTURES_DIR.iterdir()):
        if not day_dir.is_dir():
            continue
        for js_file in day_dir.glob("*.json"):
            try:
                meta = json.loads(js_file.read_text(encoding="utf-8"))
                analysis = meta.get("analysis", {})
                vocab = analysis.get("vocabulary", [])
                if not vocab:
                    continue

                captures_scanned += 1
                for label in vocab:
                    species = label.get("species")
                    depth_fm = label.get("depth_fm")
                    count = label.get("count") or 0

                    if not species:
                        continue

                    zone_name = depth_to_zone(depth_fm) if depth_fm else "unknown"

                    species_map[species]["total_reports"] += 1
                    species_map[species]["total_caught"] += count
                    species_map[species]["zones"][zone_name]["count"] += count
                    species_map[species]["zones"][zone_name]["reports"] += 1
                    if depth_fm:
                        species_map[species]["zones"][zone_name]["depths"].append(
                            depth_fm
                        )

                    zone_species[zone_name]["total_reports"] += 1
                    if species not in zone_species[zone_name]:
                        zone_species[zone_name][species] = {"reports": 0, "count": 0}
                    zone_species[zone_name][species]["reports"] += 1
                    zone_species[zone_name][species]["count"] += count

                    total_labels += 1
            except (json.JSONDecodeError, KeyError, OSError):
                continue

    result = {
        "species_list": sorted(species_map.keys()),
        "species_map": dict(species_map),
        "zone_species": dict(zone_species),
        "timestamp": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        "total_labels": total_labels,
        "captures_scanned": captures_scanned,
    }

    # Cache it
    try:
        VOCAB_CACHE.write_text(
            json.dumps(result, indent=2, default=str), encoding="utf-8"
        )
    except OSError:
        pass

    return result


def try_load_cache() -> Optional[dict]:
    """Try to load cached vocabulary. Returns None if missing or stale."""
    if not VOCAB_CACHE.exists():
        return None
    try:
        return json.loads(VOCAB_CACHE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def build_empty() -> dict:
    return {
        "species_list": [],
        "species_map": {},
        "zone_species": {},
        "timestamp": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        "total_labels": 0,
        "captures_scanned": 0,
    }


# ══════════════════════════════════════════════════════════════════════
#  Confidence Scoring
# ══════════════════════════════════════════════════════════════════════

# Laplace smoothing constant
ALPHA = 1.0


def lookup(
    depth_fm: float,
    vocab: Optional[dict] = None,
    force_rebuild: bool = False,
) -> list[dict]:
    """Look up predicted species at a given depth.

    Returns a list of species predictions sorted by confidence descending.
    Each entry:
    {
        "species": "chum",
        "confidence": 0.73,
        "confidence_label": "likely chum",
        "zone": "mid",
        "reports": 3,
        "avg_count": 12.5,
    }
    """
    if vocab is None:
        vocab = aggregate_vocabulary(force_rebuild=force_rebuild)

    zone_name = depth_to_zone(depth_fm)
    if zone_name is None:
        return []

    zone_data = vocab.get("zone_species", {}).get(zone_name, {})
    total_reports = zone_data.get("total_reports", 0)
    known_species = zone_data.get("species_list", vocab.get("species_list", []))
    # Actual species in this zone
    zone_species_keys = [
        k for k in zone_data if k not in ("total_reports", "species_list")
    ]
    n_species = max(len(zone_species_keys), 1)

    results = []
    for species in zone_species_keys:
        species_data = zone_data.get(species, {})
        reports = species_data.get("reports", 0)

        # Laplace-smoothed probability
        p = (reports + ALPHA) / (total_reports + ALPHA * n_species)
        # Clamp
        confidence = max(0.05, min(0.95, p))

        # Map to label
        if confidence < CONF_UNIDENTIFIED:
            label = "unidentified"
        elif confidence < CONF_POSSIBLE:
            label = f"possible {species}"
        elif confidence < CONF_LIKELY:
            label = f"likely {species}"
        else:
            label = species

        species_map = vocab.get("species_map", {}).get(species, {})
        zone_details = species_map.get("zones", {}).get(zone_name, {})
        depths = zone_details.get("depths", [])
        avg_count = (
            sum(depths) / len(depths) if depths else 0
        )

        results.append({
            "species": species,
            "confidence": round(confidence, 3),
            "confidence_label": label,
            "zone": zone_name,
            "reports": reports,
            "total_reports_in_zone": total_reports,
            "avg_count": round(avg_count, 1) if avg_count else None,
            "depth_fm": depth_fm,
        })

    results.sort(key=lambda x: x["confidence"], reverse=True)
    return results


def annotate_blobs(
    blobs: list[dict],
    vocab: Optional[dict] = None,
    force_rebuild: bool = False,
) -> list[dict]:
    """Annotate a list of analyzer blobs with vocabulary predictions.

    Each blob dict gets an additional 'prediction' field with
    the best species match for its centroid depth.

    Blobs in zones with no vocabulary remain unlabeled (prediction=None).
    """
    if vocab is None:
        vocab = aggregate_vocabulary(force_rebuild=force_rebuild)

    if not vocab.get("total_labels", 0):
        return blobs  # No vocabulary yet — return unlabeled

    annotated = []
    for blob in blobs:
        depth = blob.get("centroid_depth_fm", 0)
        predictions = lookup(depth, vocab=vocab)

        if predictions:
            best = predictions[0]
            if best["confidence"] >= CONF_POSSIBLE:
                blob["prediction"] = {
                    "species": best["species"],
                    "confidence": best["confidence"],
                    "confidence_label": best["confidence_label"],
                }
            else:
                blob["prediction"] = None
        else:
            blob["prediction"] = None

        annotated.append(blob)

    return annotated


# ══════════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════════

def cli() -> None:
    """CLI entry point."""
    args = sys.argv[1:]

    if not args or "-h" in args or "--help" in args:
        print("Usage:")
        print("  python vocabulary.py summarize              # Show aggregated vocabulary")
        print("  python vocabulary.py lookup <depth_fm>      # Predict species at depth")
        print("  python vocabulary.py rebuild                # Force rescan all captures")
        print()
        print("Examples:")
        print("  python vocabulary.py lookup 35")
        print("  python vocabulary.py summarize")
        return

    if args[0] == "rebuild":
        log.info("Rebuilding vocabulary from all captures...")
        vocab = aggregate_vocabulary(force_rebuild=True)
        print(json.dumps(vocab, indent=2, default=str))
        return

    if args[0] == "summarize":
        vocab = aggregate_vocabulary()
        total = vocab.get("total_labels", 0)
        scanned = vocab.get("captures_scanned", 0)
        species = vocab.get("species_list", [])

        print(f" Vocabulary Summary")
        print(f"   Total labels:    {total}")
        print(f"   Captures scanned: {scanned}")
        print(f"   Species known:   {', '.join(species) if species else 'none'}")
        print()

        if not species:
            print("   No catch reports yet. Annotate some with catch_link.py")
            return

        zone_species = vocab.get("zone_species", {})
        for zone_name in ("surface", "upper", "mid", "lower", "floor"):
            zs = zone_species.get(zone_name, {})
            total_z = zs.get("total_reports", 0)
            if total_z == 0:
                continue
            z_range = zone_range(zone_name)
            print(f"   {zone_name} ({z_range[0]}-{z_range[1]} fm):")
            for species in sorted(zs.keys()):
                if species == "total_reports":
                    continue
                sd = zs[species]
                p = (sd["reports"] + ALPHA) / (total_z + ALPHA * max(len(species), 1))
                print(
                    f"     {species}: {sd['reports']} report(s), "
                    f"{sd['count']} total fish, "
                    f"confidence {p:.2f}"
                )
        return

    if args[0] == "lookup" and len(args) >= 2:
        try:
            depth = float(args[1])
        except ValueError:
            print(f"Invalid depth: {args[1]}")
            return

        results = lookup(depth, force_rebuild=False)
        if not results:
            print(f"No vocabulary data for {depth} fm (zone: {depth_to_zone(depth)})")
            return

        print(f" Predictions at {depth} fm:")
        for r in results:
            label = r["confidence_label"]
            print(
                f"   {label} (P={r['confidence']:.2f}, "
                f"{r['reports']} report(s))"
            )
        return

    print(f"Unknown command: {args[0]}")


if __name__ == "__main__":
    cli()
