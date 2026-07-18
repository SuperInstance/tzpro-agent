#!/usr/bin/env python3
"""consensus.py — Multi-agent voting for the tzpro-agent ecosystem.

Each agent (signal_fusion, school_state, vocabulary, blob_classifier) makes
independent predictions about the underwater state. This module aggregates
them into a weighted consensus — the "wisdom of the fleet."

ARCHITECTURE:
  Agent 1 (Bayesian)   → {chum: 0.82, sockeye: 0.10, unknown: 0.08}
  Agent 2 (School)     → {chum: 0.65, unknown: 0.35}
  Agent 3 (Vocabulary) → {chum: 0.95}
  Agent 4 (Blob shape) → {chum: 0.45, pollock: 0.30, cod: 0.25}
                          ↓
                  ConsensusEngine.vote()
                          ↓
                  {chum: 0.72, sockeye: 0.05, pollock: 0.08}
                  confidence=0.72, entropy=0.91, agreement=high
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).parent.resolve()
STATE_FILE = HERE / ".consensus_state.json"

# ── Agent definitions ──────────────────────────────────────────────

AGENTS: dict[str, float] = {
    "signal_fusion": 0.85,    # Bayesian fusion — most principled
    "vocabulary": 0.70,       # Catch-linked — strong signal when data exists
    "school_state": 0.60,     # Temporal trend analysis
    "blob_classifier": 0.50,  # ML-based — good but limited training data
}


@dataclass
class Vote:
    """A single agent's prediction about the current state."""
    agent: str
    species: str
    confidence: float
    evidence: str = ""
    weight: float = 1.0

    @property
    def weighted_confidence(self) -> float:
        return self.confidence * self.weight


@dataclass
class ConsensusResult:
    """Aggregated consensus from all voting agents."""
    top_species: str
    probabilities: dict[str, float]
    agreement: str           # high | moderate | low | conflicting
    confidence: float        # 0-1, overall certainty
    entropy: float           # Shannon entropy of the distribution
    num_votes: int
    num_agents: int
    updated_at: float


@dataclass
class ConsensusEngine:
    """Weighted voting aggregation across all agent predictions.

    Each agent provides a (species, confidence) vote. Votes are weighted
    by the agent's historical reliability. Weighted probabilities are
    normalized to sum to 1.0. Agreement is classified by entropy.
    """

    historical_weights: dict[str, float] = field(default_factory=lambda: dict(AGENTS))
    vote_history: list[dict] = field(default_factory=list)
    max_history: int = 1000

    @staticmethod
    def _entropy(probs: dict[str, float]) -> float:
        """Shannon entropy of a probability distribution."""
        h = 0.0
        for p in probs.values():
            if p > 0:
                h -= p * math.log2(p)
        return h

    @staticmethod
    def _normalize(probs: dict[str, float]) -> dict[str, float]:
        """Scale probabilities to sum to 1.0."""
        total = sum(probs.values())
        if total <= 0:
            return {"unknown": 1.0}
        return {k: v / total for k, v in probs.items()}

    def _classify_agreement(self, entropy: float) -> str:
        if entropy < 0.5:
            return "high"
        elif entropy < 1.2:
            return "moderate"
        elif entropy < 1.8:
            return "low"
        else:
            return "conflicting"

    def ingest_vote(self, vote: Vote) -> None:
        """Record a single agent's vote."""
        weight = self.historical_weights.get(vote.agent, 0.5)
        vote.weight = weight
        self.vote_history.append({
            "agent": vote.agent,
            "species": vote.species,
            "confidence": vote.confidence,
            "weight": weight,
            "evidence": vote.evidence,
            "timestamp": time.time(),
        })
        # Trim history
        if len(self.vote_history) > self.max_history:
            self.vote_history = self.vote_history[-self.max_history:]

    def ingest_predictions(self, predictions: dict[str, list[dict]]) -> None:
        """Batch-ingest predictions from multiple agents.

        Args:
            predictions: {agent_name: [{species: str, confidence: float, evidence: str}]}
        """
        for agent, preds in predictions.items():
            for pred in preds:
                self.ingest_vote(Vote(
                    agent=agent,
                    species=pred.get("species", "unknown"),
                    confidence=pred.get("confidence", 0.1),
                    evidence=pred.get("evidence", ""),
                ))

    def vote(self, lookback_seconds: float = 120.0) -> Optional[ConsensusResult]:
        """Aggregate all votes within the lookback window into a consensus.

        Returns ConsensusResult or None if no recent votes.
        """
        cutoff = time.time() - lookback_seconds
        recent = [v for v in self.vote_history if v["timestamp"] >= cutoff]

        if not recent:
            return None

        # Aggregate weighted probabilities
        raw_probs: dict[str, float] = {}
        for v in recent:
            species = v["species"]
            weighted_conf = v["confidence"] * v["weight"]
            raw_probs[species] = raw_probs.get(species, 0.0) + weighted_conf

        # Normalize
        probs = self._normalize(raw_probs)

        # Top species
        top = max(probs, key=probs.get)

        # Metrics
        entropy = self._entropy(probs)
        agreement = self._classify_agreement(entropy)
        confidence = 1.0 - (entropy / max(math.log2(max(len(probs), 2)), 0.1))

        # Count unique agents that voted
        agents = set(v["agent"] for v in recent)

        return ConsensusResult(
            top_species=top,
            probabilities=probs,
            agreement=agreement,
            confidence=round(max(0.0, min(1.0, confidence)), 3),
            entropy=round(entropy, 3),
            num_votes=len(recent),
            num_agents=len(agents),
            updated_at=time.time(),
        )

    def update_weight(self, agent: str, accuracy_delta: float) -> None:
        """Adjust an agent's weight based on recent accuracy.

        positive delta = agent was correct → increase weight
        negative delta = agent was wrong → decrease weight
        """
        old = self.historical_weights.get(agent, 0.5)
        new = max(0.1, min(1.0, old + accuracy_delta))
        self.historical_weights[agent] = round(new, 2)

    def save(self) -> None:
        """Persist state to disk."""
        state = {
            "historical_weights": self.historical_weights,
            "vote_history": self.vote_history[-500:],  # save last 500
            "updated_at": time.time(),
        }
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps(state, indent=2, default=str))
        except OSError as e:
            print(f"consensus: save failed: {e}")

    @classmethod
    def load(cls) -> ConsensusEngine:
        """Load from disk or return fresh engine."""
        try:
            data = json.loads(STATE_FILE.read_text("utf-8"))
            engine = cls(
                historical_weights=data.get("historical_weights", dict(AGENTS)),
                vote_history=data.get("vote_history", []),
            )
            return engine
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            return cls()

    def summary(self) -> dict:
        """Human-readable state summary."""
        recent = self.vote()
        return {
            "agents": self.historical_weights,
            "recent_consensus": {
                "top_prediction": recent.top_species if recent else None,
                "confidence": recent.confidence if recent else None,
                "entropy": recent.entropy if recent else None,
                "agreement": recent.agreement if recent else None,
                "num_votes": recent.num_votes if recent else None,
            } if recent else "no recent votes",
            "total_votes_in_history": len(self.vote_history),
        }


# ══════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════

def cli() -> None:
    import sys

    engine = ConsensusEngine.load()

    if len(sys.argv) >= 3 and sys.argv[1] == "vote":
        agent = sys.argv[2]
        species = sys.argv[3] if len(sys.argv) >= 4 else "unknown"
        conf = float(sys.argv[4]) if len(sys.argv) >= 5 else 0.5
        engine.ingest_vote(Vote(agent=agent, species=species, confidence=conf))
        engine.save()
        result = engine.vote()
        if result:
            print(f"Added vote: {agent} → {species} ({conf})")
            print(f"Consensus: {result.top_species} (P={result.confidence}, {result.agreement} agreement)")
        return

    if len(sys.argv) >= 2 and sys.argv[1] == "status":
        s = engine.summary()
        print("CONSENSUS STATE")
        print("-" * 40)
        for agent, weight in s["agents"].items():
            print(f"  {agent:20s} weight={weight}")
        if isinstance(s["recent_consensus"], dict):
            rc = s["recent_consensus"]
            print(f"\n  Recent consensus:")
            print(f"    Top:      {rc['top_prediction']}")
            print(f"    Conf:     {rc['confidence']}")
            print(f"    Entropy:  {rc['entropy']}")
            print(f"    Agreement: {rc['agreement']}")
            print(f"    Votes:    {rc['num_votes']}")
        else:
            print(f"  No recent votes")
        print(f"\n  Total in history: {s['total_votes_in_history']}")
        return

    print("Usage:")
    print("  python consensus.py status                 — show consensus state")
    print("  python consensus.py vote <agent> <species> <conf>  — add a vote")
    print("  python consensus.py vote chum 0.82         — quick vote")


if __name__ == "__main__":
    cli()
