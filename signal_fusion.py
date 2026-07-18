#!/usr/bin/env python3
"""signal_fusion.py — Bayesian fusion engine for tzpro-agent.

Combines all data streams:
  LF band, HF band, NMEA position, boat proximity, catch reports, temporal context.

Pure Python — dataclasses + math only. No external deps.
2 ms inference target for a single update step.

Design:
  Naive Bayes with log-probability fusion. Each signal source contributes an
  independent likelihood update in log space. The joint belief is the sum of
  log-likelihoods plus the log-prior.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# =======================================================================
#  Constants
# =======================================================================

# Depth zones (matches analyzer.py)
DEPTH_ZONES = ["surface", "upper", "mid", "lower", "floor"]

# Species we track (target + known bycatch in Southeast Alaska waters)
SPECIES = [
    "chum_salmon",    # primary target
    "pink_salmon",
    "coho_salmon",
    "chinook_salmon",
    "sablefish",
    "pacific_cod",
    "halibut",
    "rockfish",
    "lingcod",
    "pollock",
]

# Density bins (echo blobs m², discretized)
DENSITY_BINS = ["none", "trace", "light", "moderate", "heavy", "dense_school"]

# Competition levels (derived from boat proximity)
COMPETITION_LEVELS = ["absent", "distant", "nearby", "crowded"]

# Feed states
FEED_STATES = [False, True]

# ── Likelihood model parameters ─────────────────────────────────────

# LF band: long-range, low-frequency. Good for depth structure, large schools.
# Each (zone, density) pair has an expected LF intensity profile.
# Values are log P(LF signal | zone, density) — pre-computed lookup.
# Indexed as [zone_idx][density_idx]
LF_LIKELIHOOD = [
    # surface
    [0.02, 0.15, 0.25, 0.20, 0.15, 0.05],  # none → dense_school
    # upper
    [0.02, 0.10, 0.25, 0.35, 0.20, 0.08],
    # mid (target zone for chum)
    [0.02, 0.08, 0.20, 0.35, 0.38, 0.20],
    # lower
    [0.02, 0.12, 0.28, 0.30, 0.18, 0.08],
    # floor
    [0.02, 0.25, 0.25, 0.15, 0.08, 0.02],
]

# HF band: high-resolution, short-range. Good for species discrimination.
# P(HF signature | species) — pre-computed lookup per species.
HF_SPECIES_LIKELIHOOD = {
    "chum_salmon":    0.30,   # distinct school shape at 200 kHz
    "pink_salmon":    0.15,
    "coho_salmon":    0.12,
    "chinook_salmon": 0.05,
    "sablefish":      0.03,
    "pacific_cod":    0.03,
    "halibut":        0.02,
    "rockfish":       0.08,
    "lingcod":        0.02,
    "pollock":        0.10,
}

# Depth preference by species (likelihood of species given depth zone)
# P(depth_zone | species)
SPECIES_DEPTH_PREFERENCE = {
    "chum_salmon":    {"surface": 0.05, "upper": 0.30, "mid": 0.45, "lower": 0.15, "floor": 0.05},
    "pink_salmon":    {"surface": 0.15, "upper": 0.50, "mid": 0.25, "lower": 0.07, "floor": 0.03},
    "coho_salmon":    {"surface": 0.20, "upper": 0.45, "mid": 0.25, "lower": 0.07, "floor": 0.03},
    "chinook_salmon": {"surface": 0.10, "upper": 0.25, "mid": 0.30, "lower": 0.25, "floor": 0.10},
    "sablefish":      {"surface": 0.01, "upper": 0.05, "mid": 0.15, "lower": 0.35, "floor": 0.44},
    "pacific_cod":    {"surface": 0.02, "upper": 0.10, "mid": 0.25, "lower": 0.38, "floor": 0.25},
    "halibut":        {"surface": 0.01, "upper": 0.05, "mid": 0.15, "lower": 0.30, "floor": 0.49},
    "rockfish":       {"surface": 0.02, "upper": 0.10, "mid": 0.25, "lower": 0.33, "floor": 0.30},
    "lingcod":        {"surface": 0.01, "upper": 0.05, "mid": 0.15, "lower": 0.40, "floor": 0.39},
    "pollock":        {"surface": 0.05, "upper": 0.25, "mid": 0.40, "lower": 0.20, "floor": 0.10},
}

# Temporal influence on feed probability by hour of day
# Peak feeding: dawn (4-5 AM) and late afternoon (4-6 PM) in summer Alaska
FEED_BY_HOUR = [
    0.20,  # 00:00
    0.15,  # 01:00
    0.12,  # 02:00
    0.10,  # 03:00
    0.25,  # 04:00  dawn peak start
    0.35,  # 05:00  dawn peak
    0.30,  # 06:00
    0.25,  # 07:00
    0.22,  # 08:00
    0.25,  # 09:00
    0.28,  # 10:00
    0.30,  # 11:00
    0.30,  # 12:00
    0.28,  # 13:00
    0.30,  # 14:00
    0.35,  # 15:00
    0.40,  # 16:00  afternoon peak start
    0.45,  # 17:00  afternoon peak
    0.40,  # 18:00
    0.30,  # 19:00
    0.25,  # 20:00
    0.22,  # 21:00
    0.20,  # 22:00
    0.22,  # 23:00
]

# Tide influence (proxy: hour-of-tide-cycle mod 6, normalized)
# Alaska tides are semi-diurnal (~6 h per stage). Slack water = better feed.
TIDE_FEED_FACTOR = [1.0, 1.15, 1.10, 1.05, 1.0, 1.20]  # index = hour % 6

LOCAL_TZ = timezone(timedelta(hours=-8))


# =======================================================================
#  Log-probability helpers
# =======================================================================

def _clamp_log(logp: float, floor: float = -20.0) -> float:
    """Clamp log-prob to avoid -inf."""
    return max(logp, floor)


def _logsumexp(logps: list[float]) -> float:
    """Numerically stable log(sum(exp(x)))."""
    if not logps:
        return float("-inf")
    m = max(logps)
    if m == float("-inf"):
        return float("-inf")
    return m + math.log(sum(math.exp(x - m) for x in logps))


def _normalize_log(logps: dict[str, float]) -> dict[str, float]:
    """Normalize a dict of log-probabilities so sum(exp(v)) = 1."""
    keys = list(logps.keys())
    vals = [logps[k] for k in keys]
    total = _logsumexp(vals)
    if total == float("-inf"):
        n = len(keys)
        return {k: math.log(1.0 / n) for k in keys}
    return {k: v - total for k, v in zip(keys, vals)}


def _entropy_from_log(logps: dict[str, float]) -> float:
    """Shannon entropy from normalized log-probabilities (in nats)."""
    H = 0.0
    for logp in logps.values():
        p = math.exp(logp)
        if p > 0:
            H -= p * logp  # p * log(p) where log is natural log
    return H


# =======================================================================
#  FusionState
# =======================================================================

@dataclass
class FusionState:
    """Bayesian belief distribution over the joint state space.

    Each field holds normalized log-probabilities (sum(exp(v)) = 1).
    """

    species: dict[str, float] = field(default_factory=dict)
    depth_zone: dict[str, float] = field(default_factory=dict)
    density: dict[str, float] = field(default_factory=dict)
    competition: dict[str, float] = field(default_factory=dict)
    feed: float = 0.0  # log-odds of active feeding

    # Metadata
    timestamp: str = ""
    update_count: int = 0
    last_sources: list[str] = field(default_factory=list)  # last 10 source tags

    def probabilities(self) -> dict:
        """Return all beliefs as [0,1] probabilities."""
        return {
            "species": {k: round(math.exp(v), 6) for k, v in self.species.items()},
            "depth_zone": {k: round(math.exp(v), 6) for k, v in self.depth_zone.items()},
            "density": {k: round(math.exp(v), 6) for k, v in self.density.items()},
            "competition": {k: round(math.exp(v), 6) for k, v in self.competition.items()},
            "feed": round(1.0 / (1.0 + math.exp(-self.feed)), 6),  # sigmoid
        }

    def entropy(self) -> float:
        """Total Shannon entropy of the joint belief (nats)."""
        # Independence assumption: H(joint) ≈ sum H(marginals)
        return (
            _entropy_from_log(self.species)
            + _entropy_from_log(self.depth_zone)
            + _entropy_from_log(self.density)
            + _entropy_from_log(self.competition)
            # Feed entropy: binary
            + (-math.exp(self.feed) * self.feed if self.feed > -20 else 0.0)
        )

    def top_beliefs(self) -> dict:
        """Return MAP estimates for each dimension."""
        probs = self.probabilities()
        return {
            "species": max(probs["species"], key=probs["species"].get),
            "species_conf": probs["species"][max(probs["species"], key=probs["species"].get)],
            "depth_zone": max(probs["depth_zone"], key=probs["depth_zone"].get),
            "depth_zone_conf": probs["depth_zone"][max(probs["depth_zone"], key=probs["depth_zone"].get)],
            "density": max(probs["density"], key=probs["density"].get),
            "density_conf": probs["density"][max(probs["density"], key=probs["density"].get)],
            "competition": max(probs["competition"], key=probs["competition"].get),
            "competition_conf": probs["competition"][max(probs["competition"], key=probs["competition"].get)],
            "feed_active": probs["feed"] > 0.5,
            "feed_conf": probs["feed"],
        }


# =======================================================================
#  FusionEngine
# =======================================================================

@dataclass
class FusionEngine:
    """Naive Bayes fusion engine combining all data streams.

    Usage:
        engine = FusionEngine()
        engine.ingest_capture(lf_profile, hf_profile, position, boats)
        engine.ingest_catch_report("chum_salmon", "mid", 120)
        state = engine.belief_state()
        print(state.entropy())
    """

    state: FusionState = field(default_factory=FusionState)
    _signal_decay: float = 0.95  # exponential decay factor per update (0–1)
    _timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        """Initialize uniform priors."""
        self._init_uniform_priors()
        self.state.timestamp = datetime.now(LOCAL_TZ).isoformat()

    def _init_uniform_priors(self) -> None:
        n_species = len(SPECIES)
        n_zones = len(DEPTH_ZONES)
        n_density = len(DENSITY_BINS)
        n_comp = len(COMPETITION_LEVELS)

        self.state.species = {s: math.log(1.0 / n_species) for s in SPECIES}
        self.state.depth_zone = {z: math.log(1.0 / n_zones) for z in DEPTH_ZONES}
        self.state.density = {d: math.log(1.0 / n_density) for d in DENSITY_BINS}
        self.state.competition = {c: math.log(1.0 / n_comp) for c in COMPETITION_LEVELS}
        self.state.feed = 0.0  # log-odds 0 → 50 %

    # ── Core update primitive ──────────────────────────────────────

    def _apply_likelihood(
        self,
        target: str,
        likelihoods: dict[str, float],
        weight: float = 1.0,
    ) -> None:
        """Apply a weighted likelihood update to a belief dimension.

        Args:
            target: 'species', 'depth_zone', 'density', or 'competition'.
            likelihoods: P(signal | state=k) for each k.
            weight: 0–1 weighting factor for this signal's influence.
        """
        belief = getattr(self.state, target)
        # Default low likelihood for unmentioned states
        # so they drop after normalization
        n_keys = len(belief)
        default_lh = 0.005 / n_keys  # very small per-key default
        for k in belief:
            if k in likelihoods:
                belief[k] += weight * math.log(max(likelihoods[k], 1e-10))
            else:
                belief[k] += weight * math.log(default_lh)
        setattr(self.state, target, _normalize_log(belief))

    # ── Signal ingestion ──────────────────────────────────────────

    def ingest_signal(self, source: str, data: dict) -> float:
        """Ingest a generic signal from a named source.

        ``data`` is a dict with one or more of:
          - species_hint: dict[str, float]  → likelihoods per species
          - zone_hint: dict[str, float]     → likelihoods per depth zone
          - density_hint: dict[str, float]  → likelihoods per density bin
          - competition_hint: dict[str, float] → likelihoods per comp level
          - feed_hint: float                → feed log-odds shift
          - weight: float                   → 0–1 weight (default 1.0)

        Returns the updated total entropy.
        """
        t0 = time.perf_counter_ns()
        weight = float(data.get("weight", 1.0))
        weight = max(0.0, min(1.0, weight))

        if "species_hint" in data:
            self._apply_likelihood("species", data["species_hint"], weight)
        if "zone_hint" in data:
            self._apply_likelihood("depth_zone", data["zone_hint"], weight)
        if "density_hint" in data:
            self._apply_likelihood("density", data["density_hint"], weight)
        if "competition_hint" in data:
            self._apply_likelihood("competition", data["competition_hint"], weight)
        if "feed_hint" in data:
            self.state.feed += weight * float(data["feed_hint"])

        self._decay_beliefs()
        self._tick_temporal()
        self.state.update_count += 1
        self._record_source(source)

        elapsed_us = (time.perf_counter_ns() - t0) / 1000.0
        return elapsed_us  # diagnostics

    def ingest_capture(
        self,
        lf: dict,
        hf: dict,
        position: Optional[dict] = None,
        boats: Optional[list[dict]] = None,
    ) -> float:
        """Ingest a dual-band fishfinder capture frame.

        Args:
            lf: LF band zone profile dict. Expected keys:
                - zones: dict[zone_name, dict] with mean_intensity, peak_intensity,
                  pixel_count_above_threshold.
            hf: HF band zone profile dict (same structure as lf).
            position: Optional dict with 'lat', 'lon'.
            boats: Optional list of boat dicts with 'distance_nm'.
        """
        t0 = time.perf_counter_ns()

        # ── LF band → density × zone update ─────────────────────
        lf_zones = lf.get("zones", {})
        for zone_name, stats in lf_zones.items():
            if zone_name not in DEPTH_ZONES:
                continue
            zone_idx = DEPTH_ZONES.index(zone_name)

            # Normalize intensity to density bin match
            mean_intensity = float(stats.get("mean_intensity", 0))
            peak_intensity = float(stats.get("peak_intensity", 0))
            signal_pct = 0.0
            total_px = float(stats.get("total_pixels", 1))
            if total_px > 0:
                signal_pct = float(stats.get("pixel_count_above_threshold", 0)) / total_px

            # Composite score 0–1
            score = (mean_intensity / 255.0 * 0.3
                     + peak_intensity / 255.0 * 0.3
                     + signal_pct * 0.4)

            # Map score → density likelihood via LF likelihood table
            density_log_lh = {}
            for di, density_bin in enumerate(DENSITY_BINS):
                base = LF_LIKELIHOOD[zone_idx][di]
                closeness = 1.0 - abs(score - base) * 3.0
                density_log_lh[density_bin] = max(closeness, 0.01)

            self._apply_likelihood("density", density_log_lh, weight=0.4)

            # Zone belief: higher intensity → more signal from this zone
            zone_log_lh = {z: 0.05 for z in DEPTH_ZONES}
            zone_log_lh[zone_name] = 0.4 + score * 0.6
            self._apply_likelihood("depth_zone", zone_log_lh, weight=0.3)

        # ── HF band → species update ───────────────────────────
        hf_zones = hf.get("zones", {})
        hf_total_score = 0.0
        hf_zone_count = 0
        for zone_name, stats in hf_zones.items():
            mean_intensity = float(stats.get("mean_intensity", 0))
            peak_intensity = float(stats.get("peak_intensity", 0))
            signal_pct = 0.0
            total_px = float(stats.get("total_pixels", 1))
            if total_px > 0:
                signal_pct = float(stats.get("pixel_count_above_threshold", 0)) / total_px

            hf_total_score += (mean_intensity / 255.0 * 0.3
                               + peak_intensity / 255.0 * 0.3
                               + signal_pct * 0.4)
            hf_zone_count += 1

        hf_avg_score = hf_total_score / max(hf_zone_count, 1)

        if hf_avg_score > 0.05:
            species_log_lh = {}
            for sp, base_lh in HF_SPECIES_LIKELIHOOD.items():
                species_log_lh[sp] = base_lh * (0.5 + hf_avg_score * 0.5)
            self._apply_likelihood("species", species_log_lh, weight=0.4)

        # ── Boat proximity → competition ───────────────────────
        if boats is not None:
            n_boats = len(boats)
            min_dist = min((b.get("distance_nm", 999.0) for b in boats), default=999.0)

            comp_log_lh = {}
            if n_boats == 0 or min_dist > 10.0:
                comp_log_lh = {"absent": 0.90, "distant": 0.10, "nearby": 0.01, "crowded": 0.005}
            elif min_dist > 3.0:
                comp_log_lh = {"absent": 0.10, "distant": 0.70, "nearby": 0.15, "crowded": 0.05}
            elif min_dist > 1.0:
                comp_log_lh = {"absent": 0.02, "distant": 0.15, "nearby": 0.65, "crowded": 0.18}
            else:
                comp_log_lh = {"absent": 0.005, "distant": 0.05, "nearby": 0.20, "crowded": 0.745}

            # More boats → more competition
            if n_boats >= 5:
                comp_log_lh["crowded"] += 0.15
                comp_log_lh["nearby"] += 0.05

            self._apply_likelihood("competition", comp_log_lh, weight=0.5)

        # ── Position → species prior (regional) ────────────────
        # Southeast Alaska summer = salmon dominant. Placeholder for future
        # lat/lon-driven regional priors (GIS shapefiles of known runs).
        if position:
            lat = position.get("lat", 0)
            # Very rough: north of 55° N → more chum/coho, south → more pink
            region_log_lh = {}
            if lat > 55.0:
                region_log_lh = {
                    "chum_salmon": 0.30, "pink_salmon": 0.15, "coho_salmon": 0.25,
                    "chinook_salmon": 0.10, "sablefish": 0.05, "pacific_cod": 0.03,
                    "halibut": 0.02, "rockfish": 0.05, "lingcod": 0.02, "pollock": 0.03,
                }
            else:
                region_log_lh = {
                    "chum_salmon": 0.20, "pink_salmon": 0.30, "coho_salmon": 0.15,
                    "chinook_salmon": 0.10, "sablefish": 0.05, "pacific_cod": 0.04,
                    "halibut": 0.03, "rockfish": 0.08, "lingcod": 0.02, "pollock": 0.03,
                }
            self._apply_likelihood("species", region_log_lh, weight=0.15)

        self._decay_beliefs()
        self._tick_temporal()
        self.state.update_count += 1
        self._record_source("capture")

        elapsed_us = (time.perf_counter_ns() - t0) / 1000.0
        return elapsed_us

    def ingest_catch_report(
        self,
        species: str,
        depth: str,
        count: int,
    ) -> float:
        """Ingest a catch report (human or sensor-confirmed).

        High-confidence update: a confirmed catch is strong evidence.

        Args:
            species: Species name (must be in SPECIES list).
            depth: Depth zone name (must be in DEPTH_ZONES).
            count: Number of fish caught.
        """
        t0 = time.perf_counter_ns()

        # Weight scales with count (diminishing returns)
        weight = min(1.0, math.log(count + 1) / math.log(20))
        confidence = min(1.0, count / 50.0)

        # Species: strong spike on confirmed catch
        if species in SPECIES:
            sp_log_lh = {s: 0.01 for s in SPECIES}
            sp_log_lh[species] = 0.90
            self._apply_likelihood("species", sp_log_lh, weight=weight * 0.8)

        # Depth zone: confirmed catch at known depth
        if depth in DEPTH_ZONES:
            zone_log_lh = {z: 0.02 for z in DEPTH_ZONES}
            zone_log_lh[depth] = 0.90
            self._apply_likelihood("depth_zone", zone_log_lh, weight=weight * 0.6)

        # Density: catch implies presence
        if count >= 50:
            dens_log_lh = {"none": 0.001, "trace": 0.02, "light": 0.05,
                           "moderate": 0.15, "heavy": 0.40, "dense_school": 0.379}
        elif count >= 20:
            dens_log_lh = {"none": 0.002, "trace": 0.03, "light": 0.10,
                           "moderate": 0.30, "heavy": 0.40, "dense_school": 0.168}
        elif count >= 5:
            dens_log_lh = {"none": 0.005, "trace": 0.05, "light": 0.30,
                           "moderate": 0.40, "heavy": 0.20, "dense_school": 0.045}
        else:
            dens_log_lh = {"none": 0.02, "trace": 0.15, "light": 0.45,
                           "moderate": 0.30, "heavy": 0.07, "dense_school": 0.01}
        self._apply_likelihood("density", dens_log_lh, weight=weight * 0.4)

        # Feed: catch confirms active feeding
        self.state.feed += weight * confidence * 2.0

        self._decay_beliefs()
        self._tick_temporal()
        self.state.update_count += 1
        self._record_source(f"catch:{species}")

        elapsed_us = (time.perf_counter_ns() - t0) / 1000.0
        return elapsed_us

    # ── Temporal context ──────────────────────────────────────────

    def _tick_temporal(self) -> None:
        """Update feed belief based on time-of-day and tide cycle."""
        now = datetime.now(LOCAL_TZ)
        hour = now.hour
        tide_idx = hour % 6  # rough tide stage

        # Base feed rate from diurnal cycle
        base_feed = FEED_BY_HOUR[hour] * TIDE_FEED_FACTOR[tide_idx]

        # Convert to log-odds shift centered at 0.5
        # log(p/(1-p)) for base_feed
        base_feed_clamped = max(0.01, min(0.99, base_feed))
        target_log_odds = math.log(base_feed_clamped / (1.0 - base_feed_clamped))

        # Nudge current feed log-odds toward time-of-day target (5% per tick)
        self.state.feed += 0.05 * (target_log_odds - self.state.feed)

        # Moon phase placeholder — future: actual moon phase calc
        # Full/new moon → stronger tides → better feed > slack

        self.state.timestamp = now.isoformat()

    # ── Belief decay ──────────────────────────────────────────────

    def _decay_beliefs(self) -> None:
        """Apply exponential decay toward uniform prior.

        Without decay, beliefs get stuck. Decay at rate (1 - signal_decay).
        """
        rate = self._signal_decay
        complement = 1.0 - rate

        n_species = len(SPECIES)
        n_zones = len(DEPTH_ZONES)
        n_density = len(DENSITY_BINS)
        n_comp = len(COMPETITION_LEVELS)

        uniform_species = math.log(1.0 / n_species)
        uniform_zone = math.log(1.0 / n_zones)
        uniform_density = math.log(1.0 / n_density)
        uniform_comp = math.log(1.0 / n_comp)

        for k in self.state.species:
            self.state.species[k] = rate * self.state.species[k] + complement * uniform_species
        for k in self.state.depth_zone:
            self.state.depth_zone[k] = rate * self.state.depth_zone[k] + complement * uniform_zone
        for k in self.state.density:
            self.state.density[k] = rate * self.state.density[k] + complement * uniform_density
        for k in self.state.competition:
            self.state.competition[k] = rate * self.state.competition[k] + complement * uniform_comp

        self.state.feed *= rate

        # Re-normalize after decay
        self.state.species = _normalize_log(self.state.species)
        self.state.depth_zone = _normalize_log(self.state.depth_zone)
        self.state.density = _normalize_log(self.state.density)
        self.state.competition = _normalize_log(self.state.competition)

    # ── Source tracking ───────────────────────────────────────────

    def _record_source(self, tag: str) -> None:
        self.state.last_sources.append(tag)
        if len(self.state.last_sources) > 10:
            self.state.last_sources = self.state.last_sources[-10:]

    # ── Public query methods ──────────────────────────────────────

    def belief_state(self) -> dict:
        """Return current belief state as a serializable dict."""
        return {
            "probabilities": self.state.probabilities(),
            "top_beliefs": self.state.top_beliefs(),
            "entropy": round(self.state.entropy(), 6),
            "entropy_breakdown": {
                "species": round(_entropy_from_log(self.state.species), 6),
                "depth_zone": round(_entropy_from_log(self.state.depth_zone), 6),
                "density": round(_entropy_from_log(self.state.density), 6),
                "competition": round(_entropy_from_log(self.state.competition), 6),
                "feed": round(
                    -math.exp(self.state.feed) * self.state.feed
                    if self.state.feed > -20
                    else 0.0,
                    6,
                ),
            },
            "update_count": self.state.update_count,
            "timestamp": self.state.timestamp,
            "last_sources": self.state.last_sources,
        }

    def entropy(self) -> float:
        """Return total Shannon entropy of the current joint belief (nats)."""
        return self.state.entropy()

    def reset(self) -> None:
        """Reset to uniform priors."""
        self._init_uniform_priors()
        self.state.update_count = 0
        self.state.last_sources.clear()
        self.state.timestamp = datetime.now(LOCAL_TZ).isoformat()

    # ── Serialization ─────────────────────────────────────────────

    def save(self, path: Optional[Path] = None) -> Path:
        """Serialize current state to .fusion_state.json."""
        if path is None:
            path = Path(__file__).parent / ".fusion_state.json"

        payload = {
            "species": self.state.species,
            "depth_zone": self.state.depth_zone,
            "density": self.state.density,
            "competition": self.state.competition,
            "feed": self.state.feed,
            "timestamp": self.state.timestamp,
            "update_count": self.state.update_count,
            "last_sources": self.state.last_sources,
            "belief_snapshot": self.belief_state(),
        }

        with open(path, "w") as f:
            json.dump(payload, f, indent=2)

        return path

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "FusionEngine":
        """Restore engine state from .fusion_state.json."""
        if path is None:
            path = Path(__file__).parent / ".fusion_state.json"

        engine = cls()

        if not path.exists():
            return engine

        try:
            with open(path, "r") as f:
                data = json.load(f)

            engine.state.species = data.get("species", engine.state.species)
            engine.state.depth_zone = data.get("depth_zone", engine.state.depth_zone)
            engine.state.density = data.get("density", engine.state.density)
            engine.state.competition = data.get("competition", engine.state.competition)
            engine.state.feed = data.get("feed", engine.state.feed)
            engine.state.timestamp = data.get("timestamp", engine.state.timestamp)
            engine.state.update_count = data.get("update_count", 0)
            engine.state.last_sources = data.get("last_sources", [])

        except (json.JSONDecodeError, KeyError, TypeError):
            # Corrupt state file → start fresh
            pass

        return engine


# =======================================================================
#  Benchmarks
# =======================================================================

def benchmark() -> dict:
    """Run a quick benchmark of the fusion engine.

    Returns dict with timing stats in microseconds.
    """
    engine = FusionEngine()

    # Synthetic LF/HF profiles (matching analyzer.py output format)
    lf = {
        "zones": {
            "mid": {"mean_intensity": 45.0, "peak_intensity": 180.0,
                    "pixel_count_above_threshold": 3400, "total_pixels": 5000},
            "upper": {"mean_intensity": 20.0, "peak_intensity": 80.0,
                      "pixel_count_above_threshold": 800, "total_pixels": 5000},
            "lower": {"mean_intensity": 25.0, "peak_intensity": 110.0,
                      "pixel_count_above_threshold": 1400, "total_pixels": 5000},
            "surface": {"mean_intensity": 12.0, "peak_intensity": 40.0,
                        "pixel_count_above_threshold": 300, "total_pixels": 5000},
            "floor": {"mean_intensity": 30.0, "peak_intensity": 90.0,
                      "pixel_count_above_threshold": 900, "total_pixels": 5000},
        }
    }
    hf = {
        "zones": {
            "mid": {"mean_intensity": 50.0, "peak_intensity": 200.0,
                    "pixel_count_above_threshold": 3800, "total_pixels": 5000},
            "upper": {"mean_intensity": 18.0, "peak_intensity": 70.0,
                      "pixel_count_above_threshold": 600, "total_pixels": 5000},
            "lower": {"mean_intensity": 22.0, "peak_intensity": 95.0,
                      "pixel_count_above_threshold": 1100, "total_pixels": 5000},
            "surface": {"mean_intensity": 10.0, "peak_intensity": 35.0,
                        "pixel_count_above_threshold": 200, "total_pixels": 5000},
            "floor": {"mean_intensity": 28.0, "peak_intensity": 85.0,
                      "pixel_count_above_threshold": 750, "total_pixels": 5000},
        }
    }
    position = {"lat": 56.5, "lon": -134.2}
    boats = [{"id": "b1", "distance_nm": 2.5}, {"id": "b2", "distance_nm": 5.0}]

    # Warm-up
    engine.ingest_capture(lf, hf, position, boats)

    engine2 = FusionEngine()
    timings = []

    for _ in range(20):
        t_us = engine2.ingest_capture(lf, hf, position, boats)
        timings.append(t_us)

    avg_us = sum(timings) / len(timings)
    return {
        "avg_us": round(avg_us, 2),
        "min_us": round(min(timings), 2),
        "max_us": round(max(timings), 2),
        "p50_us": round(sorted(timings)[len(timings) // 2], 2),
        "passes_2ms": avg_us < 2000,  # 2000 uss = 2 ms
        "samples": len(timings),
    }


# =======================================================================
#  Main
# =======================================================================

if __name__ == "__main__":
    engine = FusionEngine()

    print("=== Initial Uniform Priors ===")
    print(json.dumps(engine.belief_state(), indent=2))

    # Simulate a capture ingestion
    lf = {
        "zones": {
            "mid": {"mean_intensity": 48.0, "peak_intensity": 190.0,
                    "pixel_count_above_threshold": 3600, "total_pixels": 5000},
            "upper": {"mean_intensity": 15.0, "peak_intensity": 60.0,
                      "pixel_count_above_threshold": 500, "total_pixels": 5000},
        }
    }
    hf = {
        "zones": {
            "mid": {"mean_intensity": 52.0, "peak_intensity": 210.0,
                    "pixel_count_above_threshold": 4000, "total_pixels": 5000},
        }
    }
    position = {"lat": 56.5, "lon": -134.2}
    boats = [{"id": "b1", "distance_nm": 2.0}]

    t_us = engine.ingest_capture(lf, hf, position, boats)
    print(f"\n=== After Capture ({t_us:.1f} us) ===")
    print(json.dumps(engine.belief_state(), indent=2))

    # Simulate a catch report
    t_us = engine.ingest_catch_report("chum_salmon", "mid", 35)
    print(f"\n=== After Catch Report ({t_us:.1f} us) ===")
    print(json.dumps(engine.belief_state(), indent=2))

    # Generic signal
    t_us = engine.ingest_signal("weather", {
        "feed_hint": 0.5,
        "weight": 0.3,
    })
    print(f"\n=== After Weather Signal ({t_us:.1f} us) ===")
    print(json.dumps(engine.belief_state(), indent=2))

    print(f"\n=== Top Beliefs ===")
    print(json.dumps(engine.state.top_beliefs(), indent=2))

    # Save & reload
    save_path = engine.save()
    print(f"\nSaved to {save_path}")

    loaded = FusionEngine.load(save_path)
    assert abs(loaded.entropy() - engine.entropy()) < 0.001, "Round-trip mismatch!"

    # Benchmark
    bench = benchmark()
    print(f"\n=== Benchmark ===")
    print(f"Avg: {bench['avg_us']:.1f} us  Min: {bench['min_us']:.1f} us  Max: {bench['max_us']:.1f} us")
    print(f"P50: {bench['p50_us']:.1f} us  Passes 2 ms: {bench['passes_2ms']}")

    print("\nOK All checks passed.")
