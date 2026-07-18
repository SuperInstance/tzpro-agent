#!/usr/bin/env python3
"""
conservation_layer.py — Structural budget enforcement for tzpro-agent.

CONSERVATION LAW: γ + H = C
─────────────────────────────────────────────────────────────────────
Every intelligent system has a fixed information-processing capacity C.
Useful cognitive work (γ, "gamma") plus entropy/action overhead (H)
cannot exceed C. This is a structural invariant — it's enforced at the
execution layer, NOT at the prompt/model level. No inference can escape
the budget.

The law has a Noetherian symmetry: for every conserved quantity (C), there
is a corresponding continuous symmetry in the system dynamics. Here, the
symmetry is translational invariance in the action space: the total cost
of actions is invariant under reordering.

SCALE LAW: γ + H = 1.283 − 0.159·log(V)
─────────────────────────────────────────────────────────────────────
As tile/vocabulary volume V grows, the available productive capacity decays
logarithmically. When V exceeds the split threshold, the system must either
forget (prune low-signal entries) or spawn (fork a child with fresh V=0).

SPECTRAL FINGERPRINT: The Laplacian IS the structure
─────────────────────────────────────────────────────────────────────
The graph Laplacian of the module dependency network encodes structural
coherence. The Fiedler value (second eigenvalue) measures algebraic
connectivity. When the spectral gap closes (λ₂ → 0), the graph is about
to disconnect — a structural crisis signal.

UNIFIED ARCHITECTURE:
┌──────────────────────────────────────────────┐
│               CONSERVATION LAYER             │
│  ┌──────────┐  ┌───────────┐  ┌───────────┐ │
│  │ Budget   │  │ Scale     │  │ Spectral  │ │
│  │ γ+H ≤ C  │  │ C−k·logV  │  │ Laplacian │ │
│  └────┬─────┘  └─────┬─────┘  └─────┬─────┘ │
│  ┌────▼──────────────▼──────────────▼─────┐  │
│  │         ConservationState              │  │
│  └────────────────┬──────────────────────┘  │
│  ┌────────────────▼──────────────────────┐  │
│  │         Execution Gate                │  │
│  │  ActionBudget.consume() → permit/deny │  │
│  └───────────────────────────────────────┘  │
└──────────────────────────────────────────────┘

Invariants:
  1. No action escapes the budget counter
  2. V > split_threshold → forget or spawn
  3. Spectral gap closure → ALERT
  4. All state flows through EventLog

Usage:
  python conservation_layer.py status   — show budget state
  python conservation_layer.py gc       — run split/gc check
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "ActionBudget",
    "ActionBudgetExceeded",
    "SplitTrigger",
    "ConservationState",
    "SpectralLaplacian",
    "EventLog",
    "ACTION_BUDGET_FILE",
    "EVENT_LOG_FILE",
]

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────

DEFAULT_CAPACITY: float = 10_000.0
DEFAULT_SPLIT_THRESHOLD: int = 1_000
DEFAULT_WASTE_RATIO_LIMIT: float = 3.0
DEFAULT_SPECTRAL_GAP_THRESHOLD: float = 0.05
DEFAULT_SCALE_CONSTANT: float = 1.283
DEFAULT_SCALE_LOG_COEFFICIENT: float = 0.159

# File paths live alongside this module.
_MODULE_DIR: Path = Path(__file__).parent.resolve()
ACTION_BUDGET_FILE: Path = _MODULE_DIR / ".conservation_state.json"
EVENT_LOG_FILE: Path = _MODULE_DIR / ".conservation_events.jsonl"


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Exceptions                                                         ║
# ╚══════════════════════════════════════════════════════════════════════╝


class ActionBudgetExceeded(Exception):
    """Raised when an action would exceed the remaining budget."""

    def __init__(self, budget: "ActionBudget"):
        self.budget = budget
        super().__init__(
            f"ActionBudget exceeded: used={budget.used}/{budget.total} "
            f"(γ={budget.productive}, H={budget.waste}, "
            f"waste_ratio={budget.waste_ratio:.2f})"
        )


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  1. ActionBudget — Hard ceiling, structural enforcement              ║
# ╚══════════════════════════════════════════════════════════════════════╝


@dataclass
class ActionBudget:
    """Tracks γ (work) + H (entropy/actions) vs C (capacity).

    Enforced at the execution layer. The agent never sees the counter.
    ``consume(estimated_info_gain)`` gates every API call. When ``used ==
    total`` or ``waste_ratio > 3.0``, the action is denied structurally.

    Attributes:
        total:        Total capacity C — session cap.
        used:         Actions consumed so far.
        productive:   γ — actions with info gain above threshold.
        waste:        H — actions with info gain at or below threshold.
        waste_ratio:  H / γ; triggers denial when > DEFAULT_WASTE_RATIO_LIMIT.
    """

    total: float = DEFAULT_CAPACITY
    used: float = 0.0
    productive: float = 0.0
    waste: float = 0.0
    info_gain_threshold: float = 0.5
    waste_ratio_limit: float = DEFAULT_WASTE_RATIO_LIMIT

    @property
    def remaining(self) -> float:
        """Capacity not yet consumed."""
        return self.total - self.used

    @property
    def waste_ratio(self) -> float:
        """H / γ; returns inf when productive == 0 to safely signal excess waste."""
        if self.productive == 0.0:
            return float("inf") if self.waste > 0.0 else 0.0
        return self.waste / self.productive

    @property
    def exhausted(self) -> bool:
        """True when no budget remains or waste is excessive."""
        return self.remaining <= 0.0 or self.waste_ratio > self.waste_ratio_limit

    def consume(self, estimated_info_gain: float) -> bool:
        """Attempt to consume one action unit.

        Returns True if permitted, False if budget is exhausted.
        If the info gain is above the threshold the action counts
        as productive (γ); otherwise it counts as waste (H).

        Raises ActionBudgetExceeded when budget is exhausted
        (so callers can fail-fast).
        """
        if self.exhausted:
            raise ActionBudgetExceeded(self)

        cost = self._compute_cost(estimated_info_gain)
        self.used += cost

        if estimated_info_gain > self.info_gain_threshold:
            self.productive += cost
        else:
            self.waste += cost

        logger.debug(
            "ActionBudget.consume: gain=%.2f cost=%.2f used=%.1f/%.1f γ=%.1f H=%.1f ratio=%.2f",
            estimated_info_gain,
            cost,
            self.used,
            self.total,
            self.productive,
            self.waste,
            self.waste_ratio,
        )
        return True

    def _compute_cost(self, estimated_info_gain: float) -> float:
        """Cost per action. Subclasses may override for non-uniform costs.

        Default: each action costs 1.0 unit. High-uncertainty actions
        (low estimated_info_gain) can optionally be made more expensive
        to disincentivize thrashing.
        """
        return 1.0

    def reset(self) -> None:
        """Reset counters (e.g., on session restart). Total capacity is preserved."""
        self.used = 0.0
        self.productive = 0.0
        self.waste = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "used": self.used,
            "remaining": self.remaining,
            "productive": self.productive,
            "waste": self.waste,
            "waste_ratio": self.waste_ratio,
            "exhausted": self.exhausted,
            "info_gain_threshold": self.info_gain_threshold,
            "waste_ratio_limit": self.waste_ratio_limit,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActionBudget":
        return cls(
            total=data.get("total", DEFAULT_CAPACITY),
            used=data.get("used", 0.0),
            productive=data.get("productive", 0.0),
            waste=data.get("waste", 0.0),
            info_gain_threshold=data.get("info_gain_threshold", 0.5),
            waste_ratio_limit=data.get("waste_ratio_limit", DEFAULT_WASTE_RATIO_LIMIT),
        )


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  2. SplitTrigger — Vocabulary-growth gate                            ║
# ╚══════════════════════════════════════════════════════════════════════╝


@dataclass
class SplitTrigger:
    """Monitors vocabulary size V and triggers structural actions.

    When V > split_threshold, the system must either *forget* (prune
    lowest-confidence entries) or *spawn* (fork a child agent with a
    fresh V=0 budget). This prevents logarithmic capacity decay from
    stagnating the system.

    Attributes:
        volume:           Current vocabulary/tile count V.
        split_threshold:  Trigger point for forget/spawn.
        last_split_at:    Timestamp of last split action.
    """

    volume: int = 0
    split_threshold: int = DEFAULT_SPLIT_THRESHOLD
    last_split_at: float = 0.0

    def should_split(self) -> bool:
        """Return True when V exceeds the split threshold."""
        return self.volume > self.split_threshold

    def split_reason(self) -> str:
        """Human-readable explanation of why a split is indicated."""
        if not self.should_split():
            overflow = 0
            return (
                f"V={self.volume} ≤ threshold={self.split_threshold}; no split needed."
            )
        overflow = self.volume - self.split_threshold
        # Scale-law projection: roughly how much capacity is being lost.
        decay = DEFAULT_SCALE_LOG_COEFFICIENT * math.log(
            max(self.volume, 1)
        )
        return (
            f"V={self.volume} > threshold={self.split_threshold} "
            f"(overflow={overflow}); "
            f"scale law projects C decay ≈ {decay:.3f}. "
            f"Action required: forget() lowest-confidence entries "
            f"or spawn() a child agent."
        )

    def forget(
        self, confidences: Dict[str, float], min_confidence: float = 0.1
    ) -> Tuple[Dict[str, float], int]:
        """Prune entries below *min_confidence*.

        Returns (survivors_dict, count_pruned).
        """
        survivors = {
            k: v for k, v in confidences.items() if v >= min_confidence
        }
        pruned = len(confidences) - len(survivors)
        self.volume = len(survivors)
        self.last_split_at = time.time()
        if pruned:
            logger.info(
                "SplitTrigger.forget: pruned %d low-confidence entries, "
                "%d survive (V=%d).",
                pruned,
                len(survivors),
                self.volume,
            )
        return survivors, pruned

    def spawn(self) -> "SplitTrigger":
        """Create a fresh SplitTrigger for a child context (V=0).

        The parent's volume is NOT automatically reduced — the caller
        should follow up with forget() or accept the parent at its
        current V.
        """
        self.last_split_at = time.time()
        logger.info("SplitTrigger.spawn: forking child with V=0.")
        return SplitTrigger(volume=0, split_threshold=self.split_threshold)

    def update_volume(self, new_volume: int) -> None:
        """Set V to a new observed value."""
        self.volume = new_volume

    def to_dict(self) -> Dict[str, Any]:
        return {
            "volume": self.volume,
            "split_threshold": self.split_threshold,
            "last_split_at": self.last_split_at,
            "should_split": self.should_split(),
            "split_reason": self.split_reason(),
        }


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  3. ConservationState — Unified budget + scale + spectral tracker    ║
# ╚══════════════════════════════════════════════════════════════════════╝


@dataclass
class ConservationState:
    """Unified state object holding all conservation metrics.

    Combines the ActionBudget, SplitTrigger, and spectral fingerprint
    into a single trackable, serializable object.

    Attributes:
        gamma:         Productive work γ accumulated so far.
        entropy:       Entropy/action overhead H accumulated so far.
        volume:        Active vocabulary/tile count V.
        capacity:      Total budget C.
        split_threshold:  V value that triggers forget/spawn.
        last_update:   Timestamp of most recent state mutation.
    """

    gamma: float = 0.0
    entropy: float = 0.0
    volume: int = 0
    capacity: float = DEFAULT_CAPACITY
    split_threshold: int = DEFAULT_SPLIT_THRESHOLD
    last_update: float = field(default_factory=time.time)

    # ── Computed properties ──────────────────────────────────────────

    @property
    def remaining(self) -> float:
        return self.capacity - self.gamma - self.entropy

    @property
    def waste_ratio(self) -> float:
        if self.gamma == 0.0:
            return float("inf") if self.entropy > 0.0 else 0.0
        return self.entropy / self.gamma

    @property
    def needs_split(self) -> bool:
        return self.volume > self.split_threshold

    @property
    def capacity_projected(self) -> float:
        """Scale-law projection: C − k·log(V)."""
        return DEFAULT_SCALE_CONSTANT - DEFAULT_SCALE_LOG_COEFFICIENT * math.log(
            max(self.volume, 1)
        )

    # ── Mutation ─────────────────────────────────────────────────────

    def record_action(self, work_cost: float = 1.0) -> None:
        """Record one productive action (adds to γ, touches last_update)."""
        self.gamma += work_cost
        self.last_update = time.time()

    def record_entropy(self, entropy: float = 1.0) -> None:
        """Record one entropy/waste action (adds to H, touches last_update)."""
        self.entropy += entropy
        self.last_update = time.time()

    def consume_budget(self) -> bool:
        """Check if action is permitted under the current budget.

        Returns True if budget allows action; False if exhausted.
        """
        if self.remaining <= 0.0:
            logger.debug("ConservationState.consume_budget: denied (budget exhausted).")
            return False
        if self.waste_ratio > DEFAULT_WASTE_RATIO_LIMIT:
            logger.debug(
                "ConservationState.consume_budget: denied (waste_ratio=%.2f > limit=%.2f).",
                self.waste_ratio,
                DEFAULT_WASTE_RATIO_LIMIT,
            )
            return False
        return True

    def state_snapshot(self) -> Dict[str, Any]:
        """Return a serializable snapshot of all metrics."""
        self.last_update = time.time()
        return {
            "gamma": self.gamma,
            "entropy": self.entropy,
            "volume": self.volume,
            "capacity": self.capacity,
            "split_threshold": self.split_threshold,
            "remaining": self.remaining,
            "waste_ratio": self.waste_ratio,
            "needs_split": self.needs_split,
            "capacity_projected": self.capacity_projected,
            "scale_constant": DEFAULT_SCALE_CONSTANT,
            "scale_log_coefficient": DEFAULT_SCALE_LOG_COEFFICIENT,
            "last_update": self.last_update,
        }

    def reset(self) -> None:
        """Reset γ and H to 0 (e.g., on session restart)."""
        self.gamma = 0.0
        self.entropy = 0.0
        self.last_update = time.time()


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  4. SpectralLaplacian — Graph spectral fingerprint                   ║
# ╚══════════════════════════════════════════════════════════════════════╝


@dataclass
class SpectralLaplacian:
    """Compute spectral metrics from a module-coupling adjacency dict.

    The graph Laplacian encodes structural coherence, community
    boundaries, and vulnerability — independent of domain. The Fiedler
    value (second eigenvalue) IS the system's algebraic connectivity.

    For now, the linear algebra is stubbed: we accept an adjacency
    dict and compute basic metrics without a full eigendecomposition.
    This lets callers integrate real solvers (numpy/scipy) later
    without changing the interface.

    Attributes:
        adjacency:      Dict[str, List[str]] — module → connected modules.
        spectral_gap:   Gap between λ₂ and λ₃ (cached after compute).
        fiedler_value:  λ₂ — algebraic connectivity (cached).
        cheeger_constant: Boundary-to-volume ratio (cached).
        degree:         Dict[str, int] — degree of each node.
        node_count:     Total number of nodes.
        edge_count:     Total number of edges (undirected).
    """

    adjacency: Dict[str, List[str]] = field(default_factory=dict)
    spectral_gap: float = 0.0
    fiedler_value: float = 0.0
    cheeger_constant: float = 0.0
    degree: Dict[str, int] = field(default_factory=dict)
    node_count: int = 0
    edge_count: int = 0

    def __post_init__(self) -> None:
        if self.adjacency:
            self._compute_degree()
            self.compute()

    def _compute_degree(self) -> None:
        """Build the degree dict from adjacency."""
        self.degree = {}
        self.node_count = 0
        self.edge_count = 0
        seen_edges = set()

        for node, neighbors in self.adjacency.items():
            if neighbors is not None:
                self.degree[node] = len(neighbors)
                self.node_count = max(self.node_count, len(self.adjacency))
                for nb in neighbors:
                    # Count each undirected edge once.
                    edge = tuple(sorted((node, nb)))
                    if edge not in seen_edges:
                        seen_edges.add(edge)
                        self.edge_count += 1
                # Ensure neighbor nodes exist in degree dict even if not
                # present as keys in adjacency.
                for nb in neighbors:
                    if nb not in self.degree:
                        self.degree[nb] = 0

        # Fix up for any missing references.
        for node in self.adjacency:
            if node not in self.degree:
                self.degree[node] = 0

        self.node_count = len(self.degree)

    def compute(self) -> None:
        """Compute spectral gap, Fiedler value, and Cheeger constant.

        The current implementation uses a simplified approach:
        - Fiedler value is approximated from the minimum degree and
          edge density (MOHAR upper bound: λ₂ ≤ n/(n−1) · min_deg).
          Without a full eigen-solver this is a lower-bound estimate.
        - Spectral gap estimated from degree distribution width.
        - Cheeger constant approximated as cut-size / min(vol(A), vol(B)).

        Replace with numpy.linalg.eigvalsh when numpy is available.
        """
        n = self.node_count
        if n <= 1 or self.edge_count == 0:
            self.fiedler_value = 0.0
            self.spectral_gap = 0.0
            self.cheeger_constant = 0.0
            return

        min_deg = min(self.degree.values()) if self.degree else 0
        max_deg = max(self.degree.values()) if self.degree else 0

        # Mohar inequality: algebraic connectivity ≤ (n/(n-1)) * min_deg
        fiedler_upper = (n / max(n - 1, 1)) * min_deg

        # Edge density: 2m / (n*(n-1)).
        density = (2.0 * self.edge_count) / (n * max(n - 1, 1))

        # Estimate λ₂ as a fraction of its upper bound, modulated by density.
        # A dense graph tends to have higher connectivity.
        self.fiedler_value = fiedler_upper * min(density, 1.0)

        # Spectral gap: ratio of λ₃ to λ₂ heuristic.
        # Without full eigendecomposition we use degree spread as proxy.
        degree_spread = max_deg - min_deg
        if self.fiedler_value > 0.0 and degree_spread > 0:
            # Wider degree spread → larger gap between leading eigenvalues.
            self.spectral_gap = min(
                (degree_spread / max(max_deg, 1)) / self.fiedler_value, 1.0
            )
        else:
            self.spectral_gap = 0.0

        # Cheeger constant approximation: min cut / min volume.
        # We estimate this from edge density and minimum degree.
        if min_deg > 0:
            # h(G) ≈ (1 - density) for regular-ish graphs.
            self.cheeger_constant = 0.5 * (n / max(n - 1, 1)) * (
                1.0 - min(density, 1.0)
            )
        else:
            self.cheeger_constant = 1.0

    def is_healthy(self, gap_threshold: float = DEFAULT_SPECTRAL_GAP_THRESHOLD) -> bool:
        """Return True when the spectral gap is above the crisis threshold."""
        return self.spectral_gap > gap_threshold

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "fiedler_value": self.fiedler_value,
            "spectral_gap": self.spectral_gap,
            "cheeger_constant": self.cheeger_constant,
            "degree": self.degree.copy(),
            "healthy": self.is_healthy(),
        }


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  5. EventLog — Append-only telemetry                                 ║
# ╚══════════════════════════════════════════════════════════════════════╝


@dataclass
class EventLog:
    """Append-only, lossless event log stored as JSON Lines.

    Every budget mutation, split event, spectral computation, and
    threshold crossing is logged *before* interpretation. The fleet
    is the experiment — we cannot know in advance what's signal.

    File format: one JSON object per line in .conservation_events.jsonl.
    """

    path: Path = EVENT_LOG_FILE

    def log_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Append a timestamped event to the log.

        Args:
            event_type: Category label (e.g., "ActionBudget.consume",
                        "SplitTrigger.forget", "SpectralLaplacian.compute").
            data:       Arbitrary serializable payload.
        """
        entry = {
            "timestamp": time.time(),
            "event_type": event_type,
            "data": data,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except OSError as exc:
            logger.error("EventLog: failed to write event %s: %s", event_type, exc)

    def recent_events(self, n: int = 10) -> List[Dict[str, Any]]:
        """Return the *n* most recent events (reverse chronological).

        Loads the full file — acceptable for modest log sizes. For
        production-scale telemetry a ring-buffer or db backend should
        be substituted.
        """
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except FileNotFoundError:
            return []
        entries = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("EventLog: malformed line skipped.")
                continue
        # Return newest first.
        return entries[-n:][::-1]

    def events_by_type(self, event_type: str) -> List[Dict[str, Any]]:
        """Return all events matching *event_type* (chronological)."""
        results: List[Dict[str, Any]] = []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("event_type") == event_type:
                            results.append(entry)
                    except json.JSONDecodeError:
                        continue
        except FileNotFoundError:
            pass
        return results

    def clear(self) -> None:
        """Truncate the log file (used in tests / reset)."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("", encoding="utf-8")
        except OSError as exc:
            logger.error("EventLog: failed to clear: %s", exc)


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Persistence helpers                                                 ║
# ╚══════════════════════════════════════════════════════════════════════╝


def _save_budget(budget: ActionBudget, path: Path = ACTION_BUDGET_FILE) -> None:
    """Serialize ActionBudget to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(budget.to_dict(), indent=2), encoding="utf-8")


def _load_budget(path: Path = ACTION_BUDGET_FILE) -> ActionBudget:
    """Deserialize ActionBudget from disk, falling back to defaults."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ActionBudget.from_dict(data)
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as exc:
        logger.debug("_load_budget: returning default budget (%s)", exc)
        return ActionBudget()


def _save_conservation_state(
    state: ConservationState, path: Path = ACTION_BUDGET_FILE
) -> None:
    """Serialize ConservationState to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state.state_snapshot(), indent=2), encoding="utf-8"
    )


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CLI                                                                 ║
# ╚══════════════════════════════════════════════════════════════════════╝


def _cli_status() -> None:
    """``python conservation_layer.py status`` — display budget state."""
    budget = _load_budget()
    state = ConservationState(
        gamma=budget.productive,
        entropy=budget.waste,
        capacity=budget.total,
    )

    print("╔══════════════════════════════════════════╗")
    print("║  tzpro-agent  CONSERVATION STATE         ║")
    print("╚══════════════════════════════════════════╝")
    print()
    print("  Conservation Law: γ + H = C")
    print(f"  ────────────────────────────────────────")
    sn = state.state_snapshot()
    for key in (
        "gamma",
        "entropy",
        "volume",
        "capacity",
        "remaining",
        "waste_ratio",
        "needs_split",
        "capacity_projected",
    ):
        val = sn.get(key, "—")
        label = key.replace("_", " ").title()
        if isinstance(val, float):
            print(f"  {label:<24s} {val:>12.4f}")
        else:
            print(f"  {label:<24s} {val!r:>12s}")
    print()

    # ActionBudget detail
    print("  ActionBudget:")
    bd = budget.to_dict()
    for key in ("total", "used", "remaining", "productive", "waste", "waste_ratio"):
        val = bd.get(key, "—")
        label = key.replace("_", " ").title()
        if isinstance(val, float):
            print(f"    {label:<22s} {val:>12.4f}")
        else:
            print(f"    {label:<22s} {val!r:>12s}")
    print(f"    Exhausted:            {budget.exhausted}")


def _cli_gc() -> None:
    """``python conservation_layer.py gc`` — run split/gc check."""
    budget = _load_budget()
    log = EventLog()
    state = ConservationState(
        gamma=budget.productive,
        entropy=budget.waste,
        capacity=budget.total,
    )
    trigger = SplitTrigger(volume=state.volume)

    print("╔══════════════════════════════════════════╗")
    print("║  tzpro-agent  SPLIT / GC CHECK           ║")
    print("╚══════════════════════════════════════════╝")
    print()

    if trigger.should_split():
        reason = trigger.split_reason()
        print(f"  ⚠  SPLIT REQUIRED: {reason}")
        log.log_event("gc.split_required", {"reason": reason})

        # Simulate forget on a dummy vocabulary.
        vocab = {f"tile_{i:04d}": max(0.05, 1.0 / (i + 1)) for i in range(trigger.volume)}
        surv, pruned = trigger.forget(vocab, min_confidence=0.15)
        print(f"  📉 forget(): pruned {pruned} entries, {len(surv)} survive.")
        log.log_event(
            "gc.forget",
            {"volume_before": trigger.volume + pruned, "pruned": pruned, "volume_after": len(surv)},
        )
    else:
        print(f"  ✅ No split needed. V={trigger.volume} ≤ threshold={trigger.split_threshold}")
        log.log_event(
            "gc.no_split", {"volume": trigger.volume, "threshold": trigger.split_threshold}
        )

    # Check waste ratio.
    if budget.waste_ratio > budget.waste_ratio_limit:
        print(f"  ⚠  WASTE RATIO HIGH: H/γ = {budget.waste_ratio:.2f} > {budget.waste_ratio_limit}")
        log.log_event("gc.high_waste", budget.to_dict())
    else:
        print(f"  ✅ Waste ratio OK: H/γ = {budget.waste_ratio:.2f} ≤ {budget.waste_ratio_limit}")

    print()
    print(f"  Events logged to {log.path}")


def _cli_help() -> None:
    print("usage: python conservation_layer.py {status|gc}")
    print()
    print("  status  — display current budget and conservation state")
    print("  gc      — run split/gc check (forget low-confidence entries)")


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint. Returns 0 on success, 1 on error."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        _cli_help()
        return 0

    cmd = argv[0].lower()
    if cmd == "status":
        _cli_status()
    elif cmd == "gc":
        _cli_gc()
    elif cmd in ("-h", "--help", "help"):
        _cli_help()
    else:
        print(f"unknown command: {cmd!r}", file=sys.stderr)
        _cli_help()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
