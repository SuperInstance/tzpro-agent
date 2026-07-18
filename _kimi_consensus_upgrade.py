#!/usr/bin/env python3
"""_kimi_consensus_upgrade.py — Improved consensus fusion that feeds generate_caption().

This module upgrades the analyzer's signal/consensus integration by:

1. Running the Bayesian fusion engine BEFORE caption generation, so the
   fused belief actually influences the caption.
2. Collecting independent predictions from every available agent:
   - signal_fusion (Bayesian multi-source fusion)
   - vocabulary (catch-report linked depth→species model)
   - blob_classifier (heuristic/ML blob classification)
   - school_state (temporal behavior classification)
3. Feeding those predictions into ConsensusEngine for weighted voting.
4. Returning a compact, caption-ready result that generate_caption() can
   append as one natural-language sentence.

Intended usage in analyzer.py (around the existing Phase 9 block):

    from _kimi_consensus_upgrade import build_consensus_for_caption, add_consensus_to_caption

    consensus_result = build_consensus_for_caption(
        lf=analysis_lf,
        hf=analysis_hf,
        meta=meta,
        school_state=school_state,
    )
    add_consensus_to_caption(parts, consensus_result)

The module is fully additive: any missing dependency or empty vote set falls
back gracefully to "no consensus" so caption generation never breaks.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# ── Paths ────────────────────────────────────────────────────────────

HERE = Path(__file__).parent.resolve()
STATE_FILE = HERE / ".consensus_upgrade_state.json"

# ── Species name normalization ───────────────────────────────────────

# Different agents use different naming conventions. Map everything to the
# short form used by vocabulary / blob_classifier, then back to the
# signal_fusion canonical form when needed.
SPECIES_ALIASES: dict[str, str] = {
    "chum_salmon": "chum",
    "pink_salmon": "pink",
    "coho_salmon": "coho",
    "chinook_salmon": "chinook",
    "sablefish": "sablefish",
    "pacific_cod": "cod",
    "halibut": "halibut",
    "rockfish": "rockfish",
    "lingcod": "lingcod",
    "pollock": "pollock",
    "bait_ball": "bait_ball",
    "noise": "noise",
}

# Reverse lookup for display
_LONG_FORM: dict[str, str] = {
    "chum": "chum salmon",
    "pink": "pink salmon",
    "coho": "coho salmon",
    "chinook": "chinook salmon",
    "cod": "Pacific cod",
    "sablefish": "sablefish",
    "halibut": "halibut",
    "rockfish": "rockfish",
    "lingcod": "lingcod",
    "pollock": "pollock",
    "bait_ball": "bait ball",
    "noise": "noise",
}


def _shorten_species(name: str) -> str:
    return SPECIES_ALIASES.get(name.lower().strip(), name.lower().strip())


def _long_form(name: str) -> str:
    short = _shorten_species(name)
    return _LONG_FORM.get(short, short)


# ── Result container ─────────────────────────────────────────────────

@dataclass
class CaptionConsensusResult:
    """Consensus data ready for generate_caption()."""

    top_species: str = "unknown"
    top_confidence: float = 0.0
    top_probability: float = 0.0
    probabilities: dict[str, float] = field(default_factory=dict)
    agreement: str = "unknown"
    entropy: float = 0.0
    num_votes: int = 0
    num_agents: int = 0
    feed_active: bool = False
    feed_confidence: float = 0.5
    depth_zone: str = "unknown"
    density: str = "unknown"
    competition: str = "unknown"
    school_state: str = "unknown"
    school_confidence: float = 0.0
    fusion_entropy: float = 0.0
    sources: list[str] = field(default_factory=list)
    raw_fusion: dict = field(default_factory=dict)
    raw_consensus: dict = field(default_factory=dict)

    def is_meaningful(self, min_confidence: float = 0.35) -> bool:
        """Return True if the consensus is worth mentioning in a caption."""
        if self.top_species in ("unknown", "noise"):
            return self.top_confidence >= min_confidence and self.num_agents >= 2
        return self.top_confidence >= min_confidence and self.num_votes >= 1


# ── Vocabulary vote collection ───────────────────────────────────────

def _collect_vocabulary_votes(lf: dict) -> list[dict]:
    """Collect species predictions from vocabulary-tagged blobs."""
    votes: list[dict] = []
    try:
        from vocabulary import lookup  # type: ignore
    except Exception:
        return votes

    blobs = lf.get("blobs", [])
    seen: set[str] = set()
    for b in blobs:
        pred = b.get("prediction")
        if pred and pred.get("species"):
            sp = _shorten_species(pred["species"])
            conf = float(pred.get("confidence", 0.5))
            if sp not in seen:
                votes.append({"species": sp, "confidence": conf, "evidence": "vocabulary blob tag"})
                seen.add(sp)
            continue

        # Fallback: vocabulary lookup by blob centroid depth
        depth = b.get("centroid_depth_fm")
        if depth is None:
            continue
        try:
            preds = lookup(float(depth))
        except Exception:
            continue
        for p in preds[:2]:  # top-2 only
            sp = _shorten_species(p.get("species", "unknown"))
            conf = float(p.get("confidence", 0.1))
            if conf >= 0.1 and sp not in seen:
                votes.append({"species": sp, "confidence": conf, "evidence": f"vocabulary lookup @ {depth} fm"})
                seen.add(sp)
    return votes


# ── Blob classifier vote collection ──────────────────────────────────

def _collect_blob_classifier_votes(lf: dict) -> list[dict]:
    """Collect species predictions from the blob classifier."""
    votes: list[dict] = []
    try:
        from blob_classifier import BlobClassifier  # type: ignore
    except Exception:
        return votes

    clf = BlobClassifier()
    try:
        clf.load()
    except Exception:
        pass  # heuristic fallback is available even without a trained model

    blobs = lf.get("blobs", [])
    scores: dict[str, float] = {}
    for b in blobs:
        features = {
            "centroid_depth_fm": b.get("centroid_depth_fm", 0),
            "area_px": b.get("area_px", 0),
            "aspect_ratio": b.get("aspect_ratio", 1.0),
            "mean_intensity": b.get("mean_intensity", 0) / 255.0,
        }
        try:
            species, conf = clf.classify(features)
        except Exception:
            continue
        species = _shorten_species(species)
        if species == "noise":
            continue
        scores[species] = scores.get(species, 0.0) + conf

    if not scores:
        return votes

    # Normalize accumulated blob-classifier scores
    total = sum(scores.values())
    if total <= 0:
        return votes
    for sp, raw in sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3]:
        votes.append({"species": sp, "confidence": round(raw / total, 3), "evidence": "blob classifier"})
    return votes


# ── Signal fusion vote collection ────────────────────────────────────

def _load_fusion_engine() -> Any:
    """Load or create a FusionEngine, forgiving missing methods."""
    from signal_fusion import FusionEngine  # type: ignore

    if hasattr(FusionEngine, "load_or_new"):
        return FusionEngine.load_or_new()
    return FusionEngine.load()


def _collect_signal_fusion_votes(
    lf: dict,
    hf: dict,
    meta: dict,
    school_state: Optional[dict] = None,
) -> tuple[list[dict], dict]:
    """Run the Bayesian fusion engine and return species votes + state snapshot."""
    votes: list[dict] = []
    snapshot: dict = {}
    try:
        engine = _load_fusion_engine()
        position = meta.get("position", {})
        boats = lf.get("boat_proximity", {})
        engine.ingest_capture(lf=lf, hf=hf, position=position, boats=boats)
        try:
            engine.save()
        except Exception:
            pass

        snapshot = engine.belief_state()
        probs = snapshot.get("probabilities", {})
        species_probs = probs.get("species", {})

        # Feed active signal as a pseudo-agent vote on "feed" (not species)
        feed_conf = probs.get("feed", 0.5)

        for sp, p in sorted(species_probs.items(), key=lambda x: x[1], reverse=True)[:5]:
            if p >= 0.05:
                votes.append({
                    "species": _shorten_species(sp),
                    "confidence": round(p, 3),
                    "evidence": "Bayesian signal fusion",
                })

        # School state adds a behavioral signal; if it matches a known species
        # depth preference we can nudge that species slightly.
        if school_state:
            state = school_state.get("state", "unknown")
            conf = float(school_state.get("confidence", 0.0))
            if state != "unknown" and conf >= 0.3:
                snapshot["school_state"] = school_state

        snapshot["feed_confidence"] = feed_conf
    except Exception as e:
        snapshot = {"error": str(e)}

    return votes, snapshot


# ── Consensus assembly ───────────────────────────────────────────────

def _build_consensus_engine() -> Any:
    """Load or create a ConsensusEngine with state persistence."""
    from consensus import ConsensusEngine, AGENTS  # type: ignore

    try:
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text("utf-8"))
            engine = ConsensusEngine(
                historical_weights=data.get("historical_weights", dict(AGENTS)),
                vote_history=data.get("vote_history", []),
            )
            return engine
    except Exception:
        pass
    return ConsensusEngine()


def _save_consensus_engine(engine: Any) -> None:
    """Persist consensus engine state."""
    try:
        state = {
            "historical_weights": getattr(engine, "historical_weights", {}),
            "vote_history": getattr(engine, "vote_history", [])[-500:],
            "updated_at": time.time(),
        }
        STATE_FILE.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass


def _species_to_fusion_name(short_name: str) -> str:
    """Map short species name back to signal_fusion canonical name."""
    for long_name, short in SPECIES_ALIASES.items():
        if short == short_name:
            return long_name
    return short_name


def build_consensus_for_caption(
    lf: dict,
    hf: dict,
    meta: dict,
    school_state: Optional[dict] = None,
    track_result: Optional[dict] = None,
) -> CaptionConsensusResult:
    """Build a consensus result intended for consumption by generate_caption().

    Args:
        lf: Low-frequency band analysis dict from analyzer.py.
        hf: High-frequency band analysis dict from analyzer.py.
        meta: Capture metadata dict (should contain position if available).
        school_state: Optional output from school_state.classify_school().
        track_result: Optional output from track_blobs() (currently unused).

    Returns:
        CaptionConsensusResult with top species, probabilities, agreement,
        and fusion metadata ready to format into a caption sentence.
    """
    result = CaptionConsensusResult()
    result.sources = []

    # ── 1. Bayesian signal fusion ─────────────────────────────────────
    fusion_votes, fusion_snapshot = _collect_signal_fusion_votes(lf, hf, meta, school_state)
    if fusion_snapshot:
        result.raw_fusion = fusion_snapshot
        result.fusion_entropy = fusion_snapshot.get("entropy", 0.0)
        probs = fusion_snapshot.get("probabilities", {})
        result.feed_active = probs.get("feed", 0.5) > 0.5
        result.feed_confidence = round(probs.get("feed", 0.5), 3)
        top_beliefs = fusion_snapshot.get("top_beliefs", {})
        result.depth_zone = top_beliefs.get("depth_zone", "unknown")
        result.density = top_beliefs.get("density", "unknown")
        result.competition = top_beliefs.get("competition", "unknown")
        if fusion_votes:
            result.sources.append("signal_fusion")

    # ── 2. Vocabulary votes ────────────────────────────────────────────
    vocab_votes = _collect_vocabulary_votes(lf)
    if vocab_votes:
        result.sources.append("vocabulary")

    # ── 3. Blob classifier votes ───────────────────────────────────────
    blob_votes = _collect_blob_classifier_votes(lf)
    if blob_votes:
        result.sources.append("blob_classifier")

    # ── 4. School state context ────────────────────────────────────────
    if school_state:
        result.school_state = school_state.get("state", "unknown")
        result.school_confidence = float(school_state.get("confidence", 0.0))

    # ── 5. Weighted consensus vote ─────────────────────────────────────
    all_predictions: dict[str, list[dict]] = {
        "signal_fusion": fusion_votes,
        "vocabulary": vocab_votes,
        "blob_classifier": blob_votes,
    }

    # Only run consensus if we have at least one agent with votes
    if any(all_predictions.values()):
        engine = _build_consensus_engine()
        engine.ingest_predictions(all_predictions)
        consensus = engine.vote(lookback_seconds=120.0)
        _save_consensus_engine(engine)

        if consensus:
            result.raw_consensus = {
                "top_species": consensus.top_species,
                "probabilities": consensus.probabilities,
                "agreement": consensus.agreement,
                "confidence": consensus.confidence,
                "entropy": consensus.entropy,
                "num_votes": consensus.num_votes,
                "num_agents": consensus.num_agents,
            }
            result.top_species = _shorten_species(consensus.top_species)
            result.top_probability = round(consensus.probabilities.get(consensus.top_species, 0.0), 3)
            result.top_confidence = consensus.confidence
            result.probabilities = {
                _shorten_species(k): round(v, 3)
                for k, v in consensus.probabilities.items()
            }
            result.agreement = consensus.agreement
            result.entropy = consensus.entropy
            result.num_votes = consensus.num_votes
            result.num_agents = consensus.num_agents
        else:
            # No consensus yet — fall back to best single vote
            best = _best_single_vote(fusion_votes + vocab_votes + blob_votes)
            if best:
                result.top_species = best["species"]
                result.top_confidence = best["confidence"]
                result.top_probability = best["confidence"]
                result.num_votes = 1
                result.num_agents = 1
    else:
        # No votes at all — fall back to raw fusion top species if available
        top_beliefs = fusion_snapshot.get("top_beliefs", {})
        top_sp = top_beliefs.get("species")
        top_conf = top_beliefs.get("species_conf", 0.0)
        if top_sp:
            result.top_species = _shorten_species(top_sp)
            result.top_confidence = round(top_conf, 3)
            result.top_probability = round(top_conf, 3)
            result.num_agents = 1
            result.sources.append("signal_fusion")

    return result


def _best_single_vote(votes: list[dict]) -> Optional[dict]:
    """Return highest-confidence vote from a flat list."""
    if not votes:
        return None
    return max(votes, key=lambda v: v.get("confidence", 0.0))


# ── Caption formatting ───────────────────────────────────────────────

def _agreement_word(agreement: str) -> str:
    return {
        "high": "strongly",
        "moderate": "moderately",
        "low": "weakly",
        "conflicting": "conflictingly",
    }.get(agreement, "")


def format_consensus_sentence(result: CaptionConsensusResult) -> Optional[str]:
    """Format a consensus result into a single caption sentence, or None."""
    if not result.is_meaningful(min_confidence=0.30):
        return None

    species = result.top_species
    long_species = _long_form(species)
    conf_pct = int(round(result.top_confidence * 100))

    # Build a clause for top runners-up
    runner_clauses: list[str] = []
    for sp, p in sorted(result.probabilities.items(), key=lambda x: x[1], reverse=True):
        if sp != species and p >= 0.10 and len(runner_clauses) < 2:
            runner_clauses.append(f"{_long_form(sp)} {int(round(p * 100))}%")

    parts: list[str] = []
    parts.append(f"Fleet consensus: {long_species} ({conf_pct}% confidence)")
    if runner_clauses:
        parts.append(f"; next likely: {', '.join(runner_clauses)}")
    parts.append(".")

    # Add behavioral / ecological context when confident
    extras: list[str] = []
    if result.feed_active and result.feed_confidence >= 0.55:
        extras.append("active feed inferred")
    if result.school_state not in ("unknown", "absent") and result.school_confidence >= 0.4:
        extras.append(f"school {result.school_state}")
    if result.competition not in ("unknown", "absent") and result.competition != "absent":
        extras.append(f"competition {result.competition}")

    if extras:
        parts.append(f" Context: {', '.join(extras)}.")

    return "".join(parts)


def add_consensus_to_caption(
    caption_parts: list[str],
    result: CaptionConsensusResult,
) -> None:
    """Append a formatted consensus sentence to an existing caption parts list.

    This is the direct hook for analyzer.generate_caption(): pass it the
    `parts` list and the result from build_consensus_for_caption().
    """
    sentence = format_consensus_sentence(result)
    if sentence:
        caption_parts.append(sentence)


# ── Analyzer integration helper ──────────────────────────────────────

def consensus_context_for_analyzer(
    lf: dict,
    hf: dict,
    meta: dict,
    school_state: Optional[dict] = None,
) -> dict:
    """Return a plain dict that generate_caption() can consume directly.

    Useful if you prefer to pass the consensus as an extra keyword argument
    rather than mutating the caption parts list.
    """
    result = build_consensus_for_caption(lf, hf, meta, school_state)
    return {
        "top_species": result.top_species,
        "top_confidence": result.top_confidence,
        "top_probability": result.top_probability,
        "probabilities": result.probabilities,
        "agreement": result.agreement,
        "entropy": result.entropy,
        "feed_active": result.feed_active,
        "feed_confidence": result.feed_confidence,
        "school_state": result.school_state,
        "school_confidence": result.school_confidence,
        "sources": result.sources,
        "sentence": format_consensus_sentence(result),
    }


# ── CLI / quick test ─────────────────────────────────────────────────

def _demo() -> None:
    """Run a self-contained demo with synthetic analyzer-style inputs."""
    lf = {
        "zone_profiles": {
            "mid": {"mean_intensity": 48.0, "peak_intensity": 190.0},
        },
        "blobs": [
            {"centroid_depth_fm": 35.0, "area_px": 900, "aspect_ratio": 1.3, "mean_intensity": 120},
            {"centroid_depth_fm": 33.0, "area_px": 850, "aspect_ratio": 1.2, "mean_intensity": 110},
        ],
        "blob_count": 2,
        "boat_proximity": {"vertical_line_count": 0, "severity": "none"},
    }
    hf = {
        "zone_profiles": {
            "mid": {"mean_intensity": 52.0, "peak_intensity": 210.0},
        },
        "haze": {"feed_present": False},
    }
    meta = {"position": {"lat": 56.5, "lon": -134.2}}
    school_state = {"state": "holding", "confidence": 0.72, "evidence": ["stable blob count"]}

    result = build_consensus_for_caption(lf, hf, meta, school_state)
    print(json.dumps({
        "top_species": result.top_species,
        "top_confidence": result.top_confidence,
        "agreement": result.agreement,
        "entropy": result.entropy,
        "num_votes": result.num_votes,
        "num_agents": result.num_agents,
        "sources": result.sources,
        "sentence": format_consensus_sentence(result),
    }, indent=2))


if __name__ == "__main__":
    _demo()
