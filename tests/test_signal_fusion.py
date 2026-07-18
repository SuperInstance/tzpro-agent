#!/usr/bin/env python3
"""tests/test_signal_fusion.py — Unit tests for the Bayesian fusion module.

Covers:
  - Uniform prior initialization
  - LF/HF capture ingestion
  - Catch report ingestion
  - Generic signal ingestion
  - Entropy convergence
  - Belief decay
  - Serialization round-trip
  - Benchmark target (2 ms)
  - Edge cases (empty zones, invalid species, missing optional args)
"""

from __future__ import annotations

import json
import math
import sys
import tempfile
from pathlib import Path

# Ensure the project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from signal_fusion import (
    FusionEngine,
    FusionState,
    DEPTH_ZONES,
    SPECIES,
    DENSITY_BINS,
    COMPETITION_LEVELS,
    _normalize_log,
    _entropy_from_log,
    benchmark,
)


# ── Synthetic test data ────────────────────────────────────────────

def make_lf_profile(scores: dict[str, float]) -> dict:
    """Build a synthetic LF zone profile.
    scores: zone_name → composite score 0–1
    """
    zones = {}
    for zone_name, score in scores.items():
        zones[zone_name] = {
            "mean_intensity": score * 200.0,
            "peak_intensity": score * 255.0,
            "pixel_count_above_threshold": int(score * 5000),
            "total_pixels": 5000,
        }
    return {"zones": zones}


def make_hf_profile(scores: dict[str, float]) -> dict:
    """Build a synthetic HF zone profile."""
    return make_lf_profile(scores)  # same structure


# ═══════════════════════════════════════════════════════════════════════
#  Tests
# ═══════════════════════════════════════════════════════════════════════

class TestFusionState:
    """FusionState dataclass tests."""

    def test_uniform_initialization(self):
        engine = FusionEngine()
        state = engine.state

        # All species equally probable
        probs = state.probabilities()
        n_species = len(SPECIES)
        for sp, p in probs["species"].items():
            assert abs(p - 1.0 / n_species) < 0.001, f"{sp} = {p}"

        # All depth zones equally probable
        n_zones = len(DEPTH_ZONES)
        for z, p in probs["depth_zone"].items():
            assert abs(p - 1.0 / n_zones) < 0.001, f"{z} = {p}"

        # Feed starts at 0.5 (log-odds 0)
        assert abs(probs["feed"] - 0.5) < 0.02, f"feed = {probs['feed']}"

    def test_entropy_starts_high(self):
        engine = FusionEngine()
        H = engine.entropy()
        # Uniform over 10 species + 5 zones + 6 density + 4 comp + binary feed
        # H_max ≈ ln(10) + ln(5) + ln(6) + ln(4) + ln(2) ≈ 2.30+1.61+1.79+1.39+0.69 = 7.78
        assert H > 7.0, f"Expected high initial entropy, got {H:.4f}"

    def test_probabilities_sum_to_one(self):
        engine = FusionEngine()
        probs = engine.state.probabilities()
        assert abs(sum(probs["species"].values()) - 1.0) < 0.001
        assert abs(sum(probs["depth_zone"].values()) - 1.0) < 0.001
        assert abs(sum(probs["density"].values()) - 1.0) < 0.001
        assert abs(sum(probs["competition"].values()) - 1.0) < 0.001

    def test_top_beliefs(self):
        engine = FusionEngine()
        top = engine.state.top_beliefs()
        assert "species" in top
        assert "species_conf" in top
        assert "depth_zone" in top
        assert "feed_active" in top
        assert isinstance(top["species_conf"], float)


class TestSignalIngestion:
    """Signal ingestion tests."""

    def test_ingest_signal_species_hint(self):
        engine = FusionEngine()
        engine.ingest_signal("test", {
            "species_hint": {"chum_salmon": 0.80, "pink_salmon": 0.10, "coho_salmon": 0.05},
            "weight": 1.0,
        })
        probs = engine.state.probabilities()
        assert probs["species"]["chum_salmon"] > probs["species"]["pink_salmon"], (
            f"chum={probs['species']['chum_salmon']:.4f} pink={probs['species']['pink_salmon']:.4f}"
        )
        assert probs["species"]["chum_salmon"] > 0.15, (
            f"chum={probs['species']['chum_salmon']:.4f} should be > 0.15"
        )

    def test_ingest_signal_zone_hint(self):
        engine = FusionEngine()
        engine.ingest_signal("test", {
            "zone_hint": {"mid": 0.85, "upper": 0.10},
        })
        probs = engine.state.probabilities()
        assert probs["depth_zone"]["mid"] > probs["depth_zone"]["surface"], (
            f"mid={probs['depth_zone']['mid']:.4f} surface={probs['depth_zone']['surface']:.4f}"
        )

    def test_ingest_signal_feed_hint(self):
        engine = FusionEngine()
        engine.ingest_signal("test", {"feed_hint": 3.0})  # strong feed signal
        probs = engine.state.probabilities()
        assert probs["feed"] > 0.8, f"Expected high feed prob, got {probs['feed']}"

    def test_ingest_signal_zero_weight_noop(self):
        engine = FusionEngine()
        initial = engine.entropy()
        engine.ingest_signal("test", {
            "species_hint": {"chum_salmon": 1.0},
            "weight": 0.0,
        })
        # Should be nearly unchanged (decay + temporal still run, so small drift is OK)
        assert abs(engine.entropy() - initial) < 0.05


class TestCaptureIngestion:
    """LF/HF capture ingestion tests."""

    def test_capture_converges_chum_mid(self):
        engine = FusionEngine()

        lf = make_lf_profile({"mid": 0.7, "upper": 0.2})
        hf = make_hf_profile({"mid": 0.75})

        for _ in range(10):
            engine.ingest_capture(lf, hf)

        probs = engine.state.probabilities()
        # Mid zone should dominate
        assert probs["depth_zone"]["mid"] > 0.3
        # Density should shift away from "none"
        assert probs["density"]["none"] < 0.1

    def test_capture_with_boats(self):
        engine = FusionEngine()
        lf = make_lf_profile({"mid": 0.5})
        hf = make_hf_profile({"mid": 0.5})
        boats = [{"id": "b1", "distance_nm": 0.5}, {"id": "b2", "distance_nm": 0.8}]

        engine.ingest_capture(lf, hf, boats=boats)
        probs = engine.state.probabilities()
        assert probs["competition"]["crowded"] > probs["competition"]["absent"], (
            f"crowded={probs['competition']['crowded']:.4f} absent={probs['competition']['absent']:.4f}"
        )

    def test_capture_no_boats(self):
        engine = FusionEngine()
        lf = make_lf_profile({"mid": 0.5})
        hf = make_hf_profile({"mid": 0.5})

        engine.ingest_capture(lf, hf, boats=[])
        probs = engine.state.probabilities()
        assert probs["competition"]["absent"] > probs["competition"]["crowded"], (
            f"absent={probs['competition']['absent']:.4f} crowded={probs['competition']['crowded']:.4f}"
        )

    def test_capture_with_position(self):
        engine = FusionEngine()
        lf = make_lf_profile({"mid": 0.5})
        hf = make_hf_profile({"mid": 0.5})
        position = {"lat": 57.0, "lon": -135.0}

        engine.ingest_capture(lf, hf, position=position)
        probs = engine.state.probabilities()
        # Chum should be favored north of 55°
        assert probs["species"]["chum_salmon"] > probs["species"]["chinook_salmon"]

    def test_capture_empty_zones_no_crash(self):
        engine = FusionEngine()
        lf = {"zones": {}}
        hf = {"zones": {}}
        engine.ingest_capture(lf, hf)
        # Should not crash; entropy should remain high
        assert engine.entropy() > 7.0

    def test_capture_unknown_zone_ignored(self):
        engine = FusionEngine()
        lf = {"zones": {"bogus_zone": {"mean_intensity": 100, "peak_intensity": 200,
                                        "pixel_count_above_threshold": 1000, "total_pixels": 5000}}}
        hf = {"zones": {}}
        engine.ingest_capture(lf, hf)
        # Should handle gracefully — unknown key is skipped
        assert engine.entropy() > 0


class TestCatchReportIngestion:
    """Catch report ingestion tests."""

    def test_catch_report_confirms_species(self):
        engine = FusionEngine()
        engine.ingest_catch_report("chum_salmon", "mid", 30)
        probs = engine.state.probabilities()
        assert probs["species"]["chum_salmon"] > 0.15
        assert probs["depth_zone"]["mid"] > 0.15

    def test_catch_report_strength_scales_with_count(self):
        engine_small = FusionEngine()
        engine_big = FusionEngine()

        engine_small.ingest_catch_report("chum_salmon", "mid", 1)
        engine_big.ingest_catch_report("chum_salmon", "mid", 100)

        small_p = engine_small.state.probabilities()["species"]["chum_salmon"]
        big_p = engine_big.state.probabilities()["species"]["chum_salmon"]
        assert big_p > small_p, f"big={big_p:.4f} <= small={small_p:.4f}"

    def test_catch_report_invalid_species_no_crash(self):
        engine = FusionEngine()
        engine.ingest_catch_report("unicorn_fish", "mid", 10)
        # Should not crash — unknown species is silently ignored
        assert engine.entropy() > 0

    def test_catch_report_invalid_zone_no_crash(self):
        engine = FusionEngine()
        engine.ingest_catch_report("chum_salmon", "stratosphere", 10)
        assert engine.entropy() > 0

    def test_catch_report_sets_feed(self):
        engine = FusionEngine()
        initial_feed = engine.state.probabilities()["feed"]
        engine.ingest_catch_report("chum_salmon", "mid", 50)
        after_feed = engine.state.probabilities()["feed"]
        assert after_feed > initial_feed


class TestEntropy:
    """Entropy behavior tests."""

    def test_entropy_decreases_with_evidence(self):
        engine = FusionEngine()
        initial_H = engine.entropy()

        # Apply many capture ingestions
        lf = make_lf_profile({"mid": 0.7})
        hf = make_hf_profile({"mid": 0.75})
        for _ in range(20):
            engine.ingest_capture(lf, hf)

        after_H = engine.entropy()
        assert after_H < initial_H, f"Entropy should decrease: {initial_H:.4f} → {after_H:.4f}"

    def test_entropy_components_are_positive(self):
        engine = FusionEngine()
        state = engine.belief_state()
        ebd = state["entropy_breakdown"]
        for k, v in ebd.items():
            assert v >= 0, f"{k} entropy is negative: {v}"


class TestDecay:
    """Belief decay tests."""

    def test_decay_toward_uniform(self):
        engine = FusionEngine()
        engine._signal_decay = 0.8  # aggressive decay for test

        # Build strong beliefs
        engine.ingest_catch_report("chum_salmon", "mid", 100)
        peak_chum = engine.state.probabilities()["species"]["chum_salmon"]
        assert peak_chum > 0.3, f"Expected strong chum belief, got {peak_chum}"

        # Apply many captures (each tick applies decay)
        lf = make_lf_profile({"surface": 0.1})
        hf = make_hf_profile({"surface": 0.1})
        for _ in range(30):
            engine.ingest_capture(lf, hf)

        decayed_chum = engine.state.probabilities()["species"]["chum_salmon"]
        # Should have drifted back toward uniform (1/10 = 0.1)
        assert decayed_chum < peak_chum, f"Decay should reduce belief: {peak_chum:.4f} → {decayed_chum:.4f}"


class TestSerialization:
    """Save/load round-trip tests."""

    def test_save_load_roundtrip(self):
        engine = FusionEngine()

        # Build some state
        lf = make_lf_profile({"mid": 0.8, "upper": 0.3})
        hf = make_hf_profile({"mid": 0.8})
        engine.ingest_capture(lf, hf)
        engine.ingest_catch_report("coho_salmon", "upper", 15)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            engine.save(tmp_path)

            loaded = FusionEngine.load(tmp_path)

            # Entropy should match
            assert abs(loaded.entropy() - engine.entropy()) < 0.001

            # Species probs should match
            orig_probs = engine.state.probabilities()
            loaded_probs = loaded.state.probabilities()
            for sp in SPECIES:
                assert abs(orig_probs["species"][sp] - loaded_probs["species"][sp]) < 0.001

            # Update count should match
            assert loaded.state.update_count == engine.state.update_count

            # Timestamp should match
            assert loaded.state.timestamp == engine.state.timestamp

        finally:
            tmp_path.unlink(missing_ok=True)

    def test_load_missing_file_returns_fresh(self):
        engine = FusionEngine.load(Path("/nonexistent/path.json"))
        assert engine is not None
        assert engine.state.update_count == 0

    def test_load_corrupt_file_returns_fresh(self):
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as tmp:
            tmp.write("this is not json {{{")
            tmp_path = Path(tmp.name)

        try:
            engine = FusionEngine.load(tmp_path)
            assert engine is not None
            assert engine.state.update_count == 0
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_save_default_path(self):
        engine = FusionEngine()
        # Save to default location in project root
        default_path = PROJECT_ROOT / ".fusion_state.json"

        # Clean up any previous file
        default_path.unlink(missing_ok=True)

        try:
            path = engine.save()
            assert default_path.exists()
            assert path == default_path

            # Verify content is valid JSON
            with open(path) as f:
                data = json.load(f)
            assert "species" in data
            assert "belief_snapshot" in data
        finally:
            default_path.unlink(missing_ok=True)


class TestReset:
    """Reset behavior tests."""

    def test_reset_restores_uniform(self):
        engine = FusionEngine()
        engine.ingest_catch_report("chum_salmon", "mid", 200)

        assert engine.state.update_count > 0
        engine.reset()

        assert engine.state.update_count == 0
        probs = engine.state.probabilities()
        n_species = len(SPECIES)
        for sp, p in probs["species"].items():
            assert abs(p - 1.0 / n_species) < 0.001


class TestBenchmark:
    """Benchmark target tests."""

    def test_benchmark_passes_2ms(self):
        result = benchmark()
        assert result["passes_2ms"], (
            f"Benchmark avg {result['avg_us']:.1f} µs exceeds 2000 µs target"
        )

    def test_ingest_signal_sub_ms(self):
        import time
        engine = FusionEngine()
        times = []
        for _ in range(50):
            t_us = engine.ingest_signal("perf_test", {
                "species_hint": {"chum_salmon": 0.5, "pink_salmon": 0.5},
                "weight": 0.5,
            })
            times.append(t_us)
        avg = sum(times) / len(times)
        assert avg < 2000, f"ingest_signal avg {avg:.1f} µs > 2000 µs"

    def test_ingest_catch_report_sub_ms(self):
        import time
        engine = FusionEngine()
        times = []
        for _ in range(50):
            t_us = engine.ingest_catch_report("chum_salmon", "mid", 10)
            times.append(t_us)
        avg = sum(times) / len(times)
        assert avg < 2000, f"ingest_catch_report avg {avg:.1f} µs > 2000 µs"


class TestHelpers:
    """Unit tests for internal helpers."""

    def test_normalize_log(self):
        logps = {"a": 0.0, "b": 0.0, "c": 0.0}
        normed = _normalize_log(logps)
        for k in normed:
            assert abs(math.exp(normed[k]) - 1.0 / 3) < 0.001

    def test_normalize_log_single(self):
        logps = {"only": 5.0}
        normed = _normalize_log(logps)
        assert abs(math.exp(normed["only"]) - 1.0) < 0.001

    def test_entropy_from_log_uniform(self):
        n = 10
        logps = {str(i): math.log(1.0 / n) for i in range(n)}
        H = _entropy_from_log(logps)
        assert abs(H - math.log(n)) < 0.001

    def test_entropy_from_log_deterministic(self):
        logps = {"x": 0.0}  # p=1
        H = _entropy_from_log(logps)
        assert abs(H - 0.0) < 0.001


class TestBeliefState:
    """belief_state() output format tests."""

    def test_belief_state_keys(self):
        engine = FusionEngine()
        bs = engine.belief_state()
        assert "probabilities" in bs
        assert "top_beliefs" in bs
        assert "entropy" in bs
        assert "entropy_breakdown" in bs
        assert "update_count" in bs
        assert "timestamp" in bs
        assert "last_sources" in bs

    def test_belief_state_is_json_serializable(self):
        engine = FusionEngine()
        engine.ingest_catch_report("chum_salmon", "mid", 10)
        bs = engine.belief_state()
        # Should not raise
        json.dumps(bs)


# ═══════════════════════════════════════════════════════════════════════
#  Runner
# ═══════════════════════════════════════════════════════════════════════

def run_tests() -> int:
    """Discover and run all Test* classes. Returns exit code (0 = pass)."""
    import types

    failed = 0
    passed = 0

    module = sys.modules[__name__]
    for name in sorted(dir(module)):
        if not name.startswith("Test"):
            continue
        cls = getattr(module, name)
        if not isinstance(cls, type):
            continue

        instance = cls()
        for attr in sorted(dir(instance)):
            if not attr.startswith("test_"):
                continue
            method = getattr(instance, attr)
            if not callable(method):
                continue

            full_name = f"{name}.{attr}"
            try:
                method()
                passed += 1
                print(f"  PASS {full_name}")
            except Exception as e:
                failed += 1
                print(f"  FAIL {full_name}: {e}")

    print(f"\n{'='*50}")
    print(f"  {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_tests())
