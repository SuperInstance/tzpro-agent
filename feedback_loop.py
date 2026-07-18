#!/usr/bin/env python3
"""
feedback_loop.py — ZeroClaw intelligence closure.

The system observes -> describes -> Captain acts -> effects are observed.
This module tracks action-consequence pairs and learns from them, closing
the loop so the agent improves its recommendations over time.

Data flow:
    capture -> analyzer.py (observe/describe)
           -> feedback_loop.suggest(analysis) -> recommendation
           -> Captain acts (or not)
           -> feedback_loop.record_action()
           -> later: feedback_loop.record_outcome()
           -> feedback_loop.learn() (correlate, reinforce)

All records are appended to .feedback_log.jsonl for auditability.

No ML libraries. Pure dict tracking + weighted scoring.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("tzpro.feedback_loop")

# ── Config ───────────────────────────────────────────────────────────
WORKSPACE = Path(__file__).parent.resolve()
LOG_PATH = WORKSPACE / ".feedback_log.jsonl"

# Category weights for scoring: which signals matter most for each
# recommendation type. Updated by learn() over time.
DEFAULT_CATEGORY_WEIGHTS = {
    "boat_avoid": 1.0,    # "Boats approaching, recommend X turn"
    "stay_course": 1.0,   # "Recommend staying on course"
    "feed_haze": 1.0,     # "Feed haze increasing/decreasing"
    "chum_spot": 1.0,     # "Recommend chumming at this spot"
    "gear_check": 1.0,    # "Recommend checking gear depth"
    "bottom_watch": 1.0,  # "Bottom rising/falling"
    "drift_adjust": 1.0,  # "Recommend adjusting drift"
}

# Outcome polarity map — used to score outcomes numerically
OUTCOME_SCORES = {
    "catch increased":      1.0,
    "catch steady":         0.5,
    "catch decreased":     -0.5,
    "blobs decreased":     -0.3,  # fewer fish seen
    "blobs increased":      0.5,  # more fish seen
    "blobs steady":         0.0,
    "boats cleared":        0.5,
    "boats worsened":      -0.5,
    "haze decreased":       0.3,
    "haze increased":      -0.3,
    "haze steady":          0.0,
    "no change":            0.0,
    "no data":              0.0,
}


# ══════════════════════════════════════════════════════════════════════
#  Data Classes
# ══════════════════════════════════════════════════════════════════════

@dataclass
class ActionRecord:
    """One action-consequence pair in the feedback loop."""
    timestamp: str
    capture_id: str
    recommendation: str          # what the agent suggested
    recommendation_category: str  # "boat_avoid", "stay_course", etc.
    action_taken: str            # what the Captain actually did
    action_followed: bool        # did the Captain follow the rec?
    outcome: Optional[str] = None
    outcome_score: float = 0.0
    learned: bool = False        # has learn() processed this?
    notes: dict = field(default_factory=dict)


# ══════════════════════════════════════════════════════════════════════
#  FeedbackLoop
# ══════════════════════════════════════════════════════════════════════

class FeedbackLoop:
    """Closed-loop learning for tzpro-agent.

    Observes analysis -> makes suggestions -> tracks whether the Captain
    followed them and what happened -> reinforces or penalizes future
    suggestions of that type.
    """

    def __init__(self, log_path: Path | None = None):
        self.log_path = log_path or LOG_PATH
        self._category_weights = dict(DEFAULT_CATEGORY_WEIGHTS)

        # Signal-to-decision mapping: for each category, track which
        # signal patterns led to good outcomes so suggest() can boost
        # matching patterns.
        # { category: { pattern_key: total_score } }
        self._signal_memory: dict[str, dict[str, float]] = defaultdict(
            lambda: defaultdict(float)
        )

        # Past suggestions indexed by capture_id
        self._pending: dict[str, ActionRecord] = {}

        # Load existing log for continuity
        self._load_history()

    # ── I/O ─────────────────────────────────────────────────────────

    def _load_history(self) -> None:
        """Replay historical records to rebuild signal memory."""
        if not self.log_path.exists():
            return

        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        cat = rec.get("recommendation_category", "")
                        outcome = rec.get("outcome_score", 0.0)
                        if outcome != 0.0 and rec.get("action_followed"):
                            # Replay: update signal memory from history
                            notes = rec.get("notes", {})
                            sig = notes.get("signal_key", "")
                            if sig and cat:
                                self._signal_memory[cat][sig] += outcome
                        # Rebuild category weights from history
                        if cat and outcome != 0.0:
                            self._category_weights.setdefault(cat, 1.0)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            log.warning("Could not load feedback history: %s", e)

    def _append_log(self, record: ActionRecord) -> None:
        """Append one record as a JSON line."""
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(record), default=str) + "\n")

    # ── Signal Extraction ───────────────────────────────────────────

    @staticmethod
    def _extract_signals(analysis: dict) -> dict:
        """Extract normalized decision-relevant features from analysis.

        Returns a dict of named signals that suggest() and learn() use.
        """
        lf = analysis.get("lf", {})
        hf = analysis.get("hf", {})

        # Bottom
        bottom = lf.get("bottom") or hf.get("bottom") or {}
        bottom_depth = bottom.get("bottom_depth_fm")
        bottom_conf = bottom.get("confidence", "none")

        # Blobs
        blobs_lf = lf.get("blobs", [])
        blob_count = lf.get("blob_count", 0)

        # Boats
        boats = lf.get("boat_proximity", {})
        boat_lines = boats.get("vertical_line_count", 0)
        boat_sev = boats.get("severity", "none")

        # Thermoclines
        thermo_count = lf.get("thermocline_count", 0)

        # Haze (HF only)
        haze = hf.get("haze", {})
        haze_level = haze.get("level", "none")
        haze_change = haze.get("change", "stable")

        # Zone profiles
        zones = lf.get("zone_profiles", {})
        mid_zone = zones.get("mid", {})
        mid_intensity = mid_zone.get("mean_intensity", 0)

        signals = {
            "bottom_depth_fm": bottom_depth,
            "bottom_conf": bottom_conf,
            "blob_count": blob_count,
            "boat_lines": boat_lines,
            "boat_severity": boat_sev,
            "thermocline_count": thermo_count,
            "haze_level": haze_level,
            "haze_change": haze_change,
            "mid_zone_intensity": mid_intensity,
            "has_mid_blobs": any(
                b.get("centroid_depth_fm", 0) >= 20
                for b in blobs_lf
            ) if blobs_lf else False,
            "has_surface_blobs": any(
                b.get("centroid_depth_fm", 0) < 5
                for b in blobs_lf
            ) if blobs_lf else False,
        }

        return signals

    @staticmethod
    def _signal_key(signals: dict, category: str) -> str:
        """Produce a stable key that groups similar signal patterns.

        Different categories care about different signals. This key
        collapses continuous values into buckets for pattern matching.
        """
        # Bucket helpers
        def b_depth(d):
            if d is None: return "d_none"
            if d < 10: return "d_0_10"
            if d < 25: return "d_10_25"
            if d < 40: return "d_25_40"
            return "d_40_plus"

        def b_blobs(n):
            if n == 0: return "blobs_0"
            if n < 3: return "blobs_1_2"
            if n < 6: return "blobs_3_5"
            return "blobs_6_plus"

        def b_boats(n):
            if n == 0: return "boats_0"
            if n < 3: return "boats_1_2"
            return "boats_3_plus"

        def b_haze(h):
            return f"haze_{h}"

        parts = []

        if category in ("boat_avoid",):
            parts.append(b_boats(signals.get("boat_lines", 0)))
            parts.append(b_depth(signals.get("bottom_depth_fm")))

        elif category in ("stay_course",):
            parts.append(b_blobs(signals.get("blob_count", 0)))
            parts.append(b_haze(signals.get("haze_level", "none")))
            parts.append(b_boats(signals.get("boat_lines", 0)))

        elif category in ("feed_haze",):
            parts.append(b_haze(signals.get("haze_level", "none")))
            parts.append(str(signals.get("haze_change", "stable")))

        elif category in ("chum_spot",):
            parts.append(b_blobs(signals.get("blob_count", 0)))
            parts.append(b_depth(signals.get("bottom_depth_fm")))
            parts.append("mid" if signals.get("has_mid_blobs") else "nomid")

        elif category in ("gear_check", "bottom_watch"):
            parts.append(b_depth(signals.get("bottom_depth_fm")))

        elif category in ("drift_adjust",):
            parts.append(b_boats(signals.get("boat_lines", 0)))
            parts.append(b_depth(signals.get("bottom_depth_fm")))

        else:
            # Generic pattern
            parts.append(b_blobs(signals.get("blob_count", 0)))
            parts.append(b_boats(signals.get("boat_lines", 0)))
            parts.append(b_haze(signals.get("haze_level", "none")))

        return ":".join(parts)

    # ── Recommendation Engine ────────────────────────────────────────

    def suggest(self, analysis: dict) -> str:
        """Generate a recommendation from capture analysis.

        inspect capture analysis -> identify notable signals ->
        check reinforcement memory for similar past patterns ->
        produce weighted natural-language recommendation.

        Returns a recommendation string like:
          "Boats approaching from east, recommend port turn"
          "Feed haze increasing, recommend staying on course"
        """
        signals = self._extract_signals(analysis)

        # ── Generate candidate recommendations ──────────────────
        candidates: list[tuple[str, str, float]] = []
        # Each: (category, message, score)

        # Rule A: Boat proximity
        boat_lines = signals["boat_lines"]
        boat_sev = signals["boat_severity"]
        if boat_lines > 0:
            if boat_sev in ("high", "critical"):
                candidates.append((
                    "boat_avoid",
                    f"Multiple boats detected ({boat_lines} lines, {boat_sev}), recommend checking surroundings and considering evasive turn",
                    0.85,
                ))
            else:
                candidates.append((
                    "boat_avoid",
                    f"Boats approaching ({boat_lines} detected), recommend monitoring proximity",
                    0.60,
                ))

        # Rule B: Haze / plankton bloom
        haze_level = signals["haze_level"]
        haze_change = signals["haze_change"]
        if haze_level in ("heavy", "moderate"):
            if haze_change == "increasing":
                candidates.append((
                    "feed_haze",
                    "Feed haze increasing, recommend staying on course — fish may be feeding",
                    0.75,
                ))
            else:
                candidates.append((
                    "feed_haze",
                    f"Heavy feed haze present ({haze_level}), recommend staying in this area",
                    0.65,
                ))
        elif haze_level == "light":
            if haze_change == "decreasing":
                candidates.append((
                    "feed_haze",
                    "Feed haze decreasing, fish may be moving — consider relocating",
                    0.50,
                ))

        # Rule C: Blob detection -> chum or stay
        blob_count = signals["blob_count"]
        has_mid = signals["has_mid_blobs"]
        if has_mid and blob_count >= 2:
            candidates.append((
                "chum_spot",
                f"Schools detected in mid-zone ({blob_count} blobs), recommend chumming at this spot",
                0.80,
            ))
        elif blob_count > 0:
            candidates.append((
                "chum_spot",
                f"Some echo returns visible ({blob_count} blobs), may be worth a test drop",
                0.50,
            ))

        # Rule D: Bottom depth
        bottom_depth = signals["bottom_depth_fm"]
        if bottom_depth is not None:
            if bottom_depth < 20:
                candidates.append((
                    "bottom_watch",
                    f"Bottom rising — {bottom_depth:.0f} fm, recommend checking gear clearance",
                    0.70,
                ))
            elif bottom_depth > 50:
                candidates.append((
                    "bottom_watch",
                    f"Deep bottom at {bottom_depth:.0f} fm — may be offshore basin, fish may be scattered",
                    0.40,
                ))

        # Rule E: No signals -> stay course
        if not candidates:
            candidates.append((
                "stay_course",
                "No significant signals detected, recommend staying on present course",
                0.30,
            ))

        # ── Apply reinforcement weights ──────────────────────────
        for i, (cat, msg, base_score) in enumerate(candidates):
            cat_weight = self._category_weights.get(cat, 1.0)
            sig_key = self._signal_key(signals, cat)
            signal_bonus = self._signal_memory.get(cat, {}).get(sig_key, 0.0)

            # Clamp signal bonus to [-0.5, +0.5] to avoid wild swings
            signal_bonus = max(-0.5, min(0.5, signal_bonus))

            # Final score: base * category_weight + signal_bonus
            final_score = base_score * cat_weight + signal_bonus
            candidates[i] = (cat, msg, final_score)

        # ── Pick best ────────────────────────────────────────────
        candidates.sort(key=lambda x: x[2], reverse=True)
        best_cat, best_msg, best_score = candidates[0]

        log.debug(
            "Suggest: %d candidates -> '%s' (%.2f, category=%s)",
            len(candidates), best_msg[:60], best_score, best_cat,
        )
        return best_msg

    # ── Action / Outcome Recording ───────────────────────────────────

    def record_action(
        self,
        capture_id: str,
        recommendation: str,
        action_taken: str,
        signals: dict | None = None,
    ) -> ActionRecord:
        """Record what the Captain actually did in response to a suggestion.

        Args:
            capture_id: Capture identifier (matches analyzer's capture_id).
            recommendation: The suggestion string from suggest().
            action_taken: What the Captain actually did (natural language).
            signals: Optional signal dict from _extract_signals for context.

        Returns the stored ActionRecord.
        """
        cat = self._classify_recommendation(recommendation)
        action_followed = self._did_follow(recommendation, action_taken, cat)

        record = ActionRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            capture_id=capture_id,
            recommendation=recommendation,
            recommendation_category=cat,
            action_taken=action_taken,
            action_followed=action_followed,
            notes={"signal_key": self._signal_key(signals or {}, cat)},
        )

        self._pending[capture_id] = record
        self._append_log(record)
        log.info(
            "Record action: %s -> '%s' -> followed=%s",
            capture_id, action_taken[:50], action_followed,
        )
        return record

    def record_outcome(
        self,
        capture_id: str,
        outcome: str,
    ) -> Optional[ActionRecord]:
        """Record the observed outcome of an action.

        Args:
            capture_id: Must match a previously record_action()'d capture.
            outcome: Natural-language outcome like "catch increased",
                     "blobs decreased", "no change", "boats cleared", etc.

        Returns the updated ActionRecord, or None if no matching record_action.
        """
        record = self._pending.pop(capture_id, None)
        if record is None:
            log.warning(
                "Outcome for unknown capture_id %s — searching log", capture_id,
            )
            # Fallback: search the log file for it
            record = self._find_record(capture_id)

        if record is None:
            log.error("No ActionRecord found for capture_id=%s", capture_id)
            return None

        record.outcome = outcome
        record.outcome_score = OUTCOME_SCORES.get(outcome, 0.0)

        # Re-write with outcome
        self._append_log(record)
        log.info(
            "Record outcome: %s -> '%s' (score=%.2f)",
            capture_id, outcome, record.outcome_score,
        )
        return record

    # ── Learning ─────────────────────────────────────────────────────

    def learn(self) -> dict:
        """Retroactively correlate recommendations + actions + outcomes.

        Iterates all records in .feedback_log.jsonl and updates:
          - _category_weights: category-level score averaging
          - _signal_memory: signal-pattern -> outcome mapping

        Returns a summary dict with stats about what changed.
        """
        if not self.log_path.exists():
            return {"status": "no_log", "records": 0}

        # Reset and replay
        self._category_weights = dict(DEFAULT_CATEGORY_WEIGHTS)
        self._signal_memory = defaultdict(lambda: defaultdict(float))

        records = []
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            log.error("learn() read error: %s", e)
            return {"status": "error", "error": str(e)}

        # ── Category weight: mean outcome_score per category ─────
        cat_scores: dict[str, list[float]] = defaultdict(list)
        for r in records:
            if not r.get("action_followed"):
                continue
            score = r.get("outcome_score", 0.0)
            cat = r.get("recommendation_category", "")
            if cat and score != 0.0:
                cat_scores[cat].append(score)

        for cat, scores in cat_scores.items():
            mean = sum(scores) / len(scores) if scores else 1.0
            # Blend: 70% new mean, 30% old to prevent overcorrection
            old = self._category_weights.get(cat, 1.0)
            self._category_weights[cat] = round(old * 0.3 + mean * 0.7, 3)

        # ── Signal memory: signal_key -> mean outcome ─────────────
        sig_records: dict[str, dict[str, list[float]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for r in records:
            if not r.get("action_followed"):
                continue
            score = r.get("outcome_score", 0.0)
            cat = r.get("recommendation_category", "")
            sig_key = r.get("notes", {}).get("signal_key", "")
            if cat and sig_key and score != 0.0:
                sig_records[cat][sig_key].append(score)

        for cat, keys in sig_records.items():
            for sig_key, scores in keys.items():
                mean_score = sum(scores) / len(scores) if scores else 0.0
                self._signal_memory[cat][sig_key] = round(mean_score, 3)

        # ── Stats ────────────────────────────────────────────────
        followed = [r for r in records if r.get("action_followed")]
        with_outcomes = [r for r in followed if r.get("outcome")]
        positive = [r for r in with_outcomes if r.get("outcome_score", 0) > 0]

        summary = {
            "status": "ok",
            "records_total": len(records),
            "records_followed": len(followed),
            "records_with_outcomes": len(with_outcomes),
            "positive_outcomes": len(positive),
            "category_weights": dict(self._category_weights),
            "signal_patterns_learned": sum(
                len(v) for v in self._signal_memory.values()
            ),
        }

        # Mark all records as learned
        log.info(
            "learn(): %d records, %d categories updated, %d signal patterns",
            len(records),
            len(cat_scores),
            summary["signal_patterns_learned"],
        )
        return summary

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _classify_recommendation(recommendation: str) -> str:
        """Classify a recommendation string into a category."""
        r = recommendation.lower()
        if "boat" in r and ("avoid" in r or "turn" in r or "approach" in r):
            return "boat_avoid"
        if "stay" in r and "course" in r:
            return "stay_course"
        if "feed" in r or "haze" in r:
            return "feed_haze"
        if "chum" in r:
            return "chum_spot"
        if "gear" in r:
            return "gear_check"
        if "bottom" in r:
            return "bottom_watch"
        if "drift" in r:
            return "drift_adjust"
        return "stay_course"  # default

    @staticmethod
    def _did_follow(
        recommendation: str, action_taken: str, category: str
    ) -> bool:
        """Heuristic: did the Captain follow the recommendation?"""
        rec_l = recommendation.lower()
        act_l = action_taken.lower()

        if category == "boat_avoid":
            return any(w in act_l for w in ("turn", "move", "avoid", "alter", "evasive"))
        if category == "stay_course":
            return any(w in act_l for w in ("stay", "continue", "maintain", "hold", "keep"))
        if category == "feed_haze":
            return any(w in act_l for w in ("stay", "continue", "hold", "remain", "keep"))
        if category == "chum_spot":
            return any(w in act_l for w in ("chum", "drop", "bait", "fish", "test"))
        if category == "gear_check":
            return any(w in act_l for w in ("check", "gear", "haul", "pull"))
        if category == "bottom_watch":
            return any(w in act_l for w in ("check", "watch", "monitor", "gear", "depth"))
        if category == "drift_adjust":
            return any(w in act_l for w in ("adjust", "drift", "move", "reposition"))

        # Generic: if the action is not a rejection, assume followed
        rejection = any(
            w in act_l for w in ("ignore", "disregard", "override", "no", "not")
        )
        return not rejection

    def _find_record(self, capture_id: str) -> Optional[ActionRecord]:
        """Search the log file for an existing ActionRecord by capture_id."""
        if not self.log_path.exists():
            return None
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if data.get("capture_id") == capture_id:
                            return ActionRecord(
                                timestamp=data.get("timestamp", ""),
                                capture_id=data.get("capture_id", ""),
                                recommendation=data.get("recommendation", ""),
                                recommendation_category=data.get(
                                    "recommendation_category", ""
                                ),
                                action_taken=data.get("action_taken", ""),
                                action_followed=data.get("action_followed", False),
                                outcome=data.get("outcome"),
                                outcome_score=data.get("outcome_score", 0.0),
                                learned=data.get("learned", False),
                                notes=data.get("notes", {}),
                            )
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass
        return None

    # ── Inspection ───────────────────────────────────────────────────

    def stats(self) -> dict:
        """Return current state summary."""
        return {
            "log_path": str(self.log_path),
            "log_exists": self.log_path.exists(),
            "category_weights": dict(self._category_weights),
            "signal_patterns": sum(
                len(v) for v in self._signal_memory.values()
            ),
            "pending_records": len(self._pending),
        }


# ══════════════════════════════════════════════════════════════════════
#  CLI: quick test
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    loop = FeedbackLoop()

    # Simulate an analysis dict (like what analyzer.py produces)
    sample_analysis = {
        "lf": {
            "bottom": {"bottom_depth_fm": 35, "confidence": "high"},
            "blobs": [
                {"centroid_depth_fm": 28, "prediction": {"species": "salmon"}},
                {"centroid_depth_fm": 32, "prediction": {"species": "salmon"}},
                {"centroid_depth_fm": 30, "prediction": {}},
                {"centroid_depth_fm": 3, "prediction": {}},
            ],
            "blob_count": 4,
            "thermocline_count": 1,
            "thermoclines": [{"center_depth_fm": 15}],
            "boat_proximity": {"vertical_line_count": 3, "severity": "high"},
            "zone_profiles": {"mid": {"mean_intensity": 42, "peak_intensity": 78}},
        },
        "hf": {
            "haze": {"level": "moderate", "change": "increasing"},
        },
    }

    print("=" * 60)
    print("FeedbackLoop Self-Test")
    print("=" * 60)

    # Step 1: Suggest
    rec = loop.suggest(sample_analysis)
    print(f"\n[SUGGEST] Recommendation: {rec}")

    # Step 2: Captain acts (with signals for better learning)
    cap_id = "capture_20260718T102100_001"
    signals = loop._extract_signals(sample_analysis)
    record = loop.record_action(
        capture_id=cap_id,
        recommendation=rec,
        action_taken="Turned to port 30 degrees to check surroundings, then resumed course",
        signals=signals,
    )
    print(f"\n[ACTION] Action recorded: followed={record.action_followed}")

    # Step 3: Outcome
    record = loop.record_outcome(
        capture_id=cap_id,
        outcome="boats cleared",
    )
    print(f"\n[OUTCOME] Outcome: '{record.outcome}' (score={record.outcome_score})")

    # Step 4: Learn
    summary = loop.learn()
    print(f"\n[LEARN] Learn summary:")
    print(f"   Records: {summary['records_total']}")
    print(f"   Followed: {summary['records_followed']}")
    print(f"   With outcomes: {summary['records_with_outcomes']}")
    print(f"   Positive: {summary['positive_outcomes']}")
    print(f"   Weights: {summary['category_weights']}")
    print(f"   Patterns learned: {summary['signal_patterns_learned']}")

    # Step 5: Stats
    print(f"\n[STATS] Current stats: {loop.stats()}")

    print(f"\n[OK] Self-test complete. Log at: {LOG_PATH}")
