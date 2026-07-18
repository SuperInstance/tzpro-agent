#!/usr/bin/env python3
"""
tests/test_offline_llm.py — Tests for offline_llm.py.

Tests the template mode (the only mode guaranteed to work without
external dependencies). Markov and Gemma modes are optional and
tested only when their dependencies are available.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Make sure we can import the module under test
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import offline_llm  # type: ignore[import-untyped]


# ──────────────────────────────────────────────────────────────────────
#  Sample capture JSON for testing
# ──────────────────────────────────────────────────────────────────────

SAMPLE_CAPTURE: dict = {
    "capture_id": "1050_5546.846N_13141.895W",
    "ts_utc": "2026-07-17T18:50:03.615716+00:00",
    "ts_local": "2026-07-17T10:50:00.001714-08:00",
    "ts_local_hhmm": "1050",
    "frame_file": "1050_5546.846N_13141.895W.png",
    "position": {
        "lat_dd": 55.780772,
        "lon_dd": -131.69824216666666,
        "lat_ddmm": "5546.846",
        "lon_ddmm": "13141.895",
        "sog_kts": 1.491,
        "cog_deg": 111.13,
    },
    "display": {
        "offset_x": 1920,
        "offset_y": 0,
        "width": 1920,
        "height": 1080,
        "depth_max_fm": 60,
        "px_per_fm": 18.0,
    },
    "bands": {
        "lf": {
            "file": "1050_5546.846N_13141.895W_LF.png",
            "label": "low_freq",
            "x_px": [8, 945],
            "width_px": 937,
        },
        "hf": {
            "file": "1050_5546.846N_13141.895W_HF.png",
            "label": "high_freq",
            "x_px": [950, 1890],
            "width_px": 940,
        },
    },
    "analysis": {
        "schema_version": 1,
        "heuristic": None,
        "caption": None,
        "vocabulary": None,
    },
}

SAMPLE_CAPTURE_V1: dict = {
    "ts_utc": "2026-07-17T18:36:51.792300+00:00",
    "ts_local": "2026-07-17T10:36:47.540985-08:00",
    "filename": "1036_5546.962N_13142.420W.png",
    "position": {
        "lat": 55.78270416666667,
        "lon": -131.70699583333334,
        "sog_kts": 1.322,
        "cog_deg": 105.55,
    },
    "display": {
        "offset_x": 1920,
        "width": 1920,
        "height": 1080,
        "depth_max_fm": 60,
    },
}


# ──────────────────────────────────────────────────────────────────────
#  Tests — Template mode
# ──────────────────────────────────────────────────────────────────────

class TestTemplateMode(unittest.TestCase):
    """Tests for the rule-based template description generator."""

    def test_generates_nonempty_string(self) -> None:
        result = offline_llm.generate_template(SAMPLE_CAPTURE)
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 20,
                           "Template output should be a substantial string")

    def test_includes_position(self) -> None:
        result = offline_llm.generate_template(SAMPLE_CAPTURE)
        self.assertIn("5546.846N", result)
        self.assertIn("13141.895W", result)

    def test_includes_sog(self) -> None:
        result = offline_llm.generate_template(SAMPLE_CAPTURE)
        self.assertIn("SOG", result)
        self.assertIn("1.5", result)  # 1.491 rounds to 1.5

    def test_includes_cog(self) -> None:
        result = offline_llm.generate_template(SAMPLE_CAPTURE)
        self.assertIn("COG", result)

    def test_includes_bottom(self) -> None:
        result = offline_llm.generate_template(SAMPLE_CAPTURE)
        self.assertIn("Bottom", result)
        self.assertIn("fm", result)
        self.assertIn("confidence", result)

    def test_includes_thermal(self) -> None:
        result = offline_llm.generate_template(SAMPLE_CAPTURE)
        self.assertIn("thermal", result.lower())
        self.assertIn("layer", result.lower())

    def test_includes_echo_returns(self) -> None:
        result = offline_llm.generate_template(SAMPLE_CAPTURE)
        self.assertIn("echo", result.lower())
        self.assertIn("return", result.lower())

    def test_includes_mid_water(self) -> None:
        result = offline_llm.generate_template(SAMPLE_CAPTURE)
        self.assertIn("mid-water", result.lower())

    def test_includes_boat_assessment(self) -> None:
        result = offline_llm.generate_template(SAMPLE_CAPTURE)
        # Must contain some boat/interference language
        has_boat = any(
            phrase in result.lower()
            for phrase in [
                "vertical line", "sonar interference",
                "transducer", "clear water",
                "fleet", "boats",
            ]
        )
        self.assertTrue(has_boat,
                        f"Expected boat/interference language, got: {result[:120]}")

    def test_v1_capture_format(self) -> None:
        """Template mode handles v1 capture format (simpler JSON)."""
        result = offline_llm.generate_template(SAMPLE_CAPTURE_V1)
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 20)

    def test_deterministic_zones(self) -> None:
        """Zone classification is deterministic."""
        self.assertEqual(offline_llm._zone_for_depth(2.5), "surface")
        self.assertEqual(offline_llm._zone_for_depth(12.0), "upper")
        self.assertEqual(offline_llm._zone_for_depth(30.0), "mid")
        self.assertEqual(offline_llm._zone_for_depth(50.0), "lower")
        self.assertEqual(offline_llm._zone_for_depth(57.0), "floor")

    def test_plural_helper(self) -> None:
        self.assertEqual(offline_llm._plural(1, "layer"), "layer")
        self.assertEqual(offline_llm._plural(3, "layer"), "layers")
        self.assertEqual(offline_llm._plural(0, "layer"), "layers")

    def test_haze_assessment(self) -> None:
        has_feed, label = offline_llm._assess_haze(200, 60)
        self.assertTrue(has_feed)
        self.assertEqual(label, "dense")

        has_feed, label = offline_llm._assess_haze(40, 60)
        self.assertFalse(has_feed)


# ──────────────────────────────────────────────────────────────────────
#  Tests — Markov chain internals
# ──────────────────────────────────────────────────────────────────────

class TestMarkovChain(unittest.TestCase):
    """Tests for the Markov chain model (no external deps — just
    collections.Counter is fine)."""

    def test_empty_chain(self) -> None:
        chain = offline_llm.MarkovChain()
        result = chain.generate()
        self.assertIn("No training data", result)

    def test_single_sentence_training(self) -> None:
        chain = offline_llm.MarkovChain()
        chain.train(["Bottom detected at 57.3 fm high confidence."])
        self.assertGreater(len(chain.transitions), 0)
        self.assertGreater(len(chain.starts), 0)
        result = chain.generate(max_words=50)
        # Output should contain some of the training words
        self.assertIn("Bottom", result)
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 5)

    def test_multiple_captions(self) -> None:
        chain = offline_llm.MarkovChain()
        captions = [
            "Bottom detected at 57.3 fm (high confidence). "
            "11 thermal layers detected at 6.0 fm, 25.6 fm, 26.4 fm. "
            "19 echo returns detected in the LF band across 5 zones.",

            "Bottom detected at 57.2 fm (high confidence). "
            "3 thermal layers detected at 3.8 fm, 23.9 fm. "
            "456 echo returns detected in the LF band.",

            "Bottom detected at 57.2 fm (high confidence). "
            "7 thermal layers detected at 4.7 fm, 18.5 fm, 20.6 fm. "
            "6 vertical lines from other transducers — boats in the area.",
        ]
        chain.train(captions)
        result = chain.generate(max_words=80)
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 10)
        # Should contain nautical vocabulary
        self.assertIn("fm", result)


# ──────────────────────────────────────────────────────────────────────
#  Tests — Markdown extraction
# ──────────────────────────────────────────────────────────────────────

class TestMarkdownExtraction(unittest.TestCase):
    """Tests _extract_captions against known .md format."""

    def test_extracts_analysis_section(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            md = Path(td) / "test.md"
            md.write_text("""\
# Echogram Capture 0610_5546.779N_13141.210W

## Analysis

Bottom detected at 57.3 fm (high confidence). 11 thermal layers detected at 6.0 fm, 25.6 fm, 26.4 fm. 19 echo returns detected in the LF band across 5 zones (surface, upper, mid, lower, floor). Vocabulary predicts: chum. Mid-water column (20-40 fm) mean intensity 8.3/255, peak 255/255. No sounder interference currently. Boats in recent frames are gone - we may have our school back to ourselves.

### LF Band
- Bottom: 57.3 fm
""", encoding="utf-8")
            captions = offline_llm._extract_captions(Path(td))
            self.assertEqual(len(captions), 1)
            self.assertIn("Bottom detected at 57.3", captions[0])

    def test_skips_no_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            md = Path(td) / "test.md"
            md.write_text("""\
# Echogram Capture

## Analysis

*No analysis yet — raw capture phase.*
""", encoding="utf-8")
            captions = offline_llm._extract_captions(Path(td))
            self.assertEqual(len(captions), 0)

    def test_multiple_captions_from_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "a.md").write_text("""\
## Analysis
Bottom at 57.3 fm. Chum predicted.
""", encoding="utf-8")
            (base / "b.md").write_text("""\
## Analysis
Bottom at 57.2 fm. No returns.
""", encoding="utf-8")
            captions = offline_llm._extract_captions(base)
            self.assertEqual(len(captions), 2)


# ──────────────────────────────────────────────────────────────────────
#  Tests — CLI invocation
# ──────────────────────────────────────────────────────────────────────

class TestCLI(unittest.TestCase):
    """End-to-end CLI tests via main()."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.json_path = Path(self.tmp_dir.name) / "capture.json"
        self.json_path.write_text(json.dumps(SAMPLE_CAPTURE), encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_template_cli(self) -> None:
        """Template CLI runs without error and produces output."""
        import io
        orig_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            offline_llm.main(["template", "--capture", str(self.json_path)])
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = orig_stdout
        self.assertGreater(len(output), 30)
        self.assertIn("fm", output)

    def test_template_cli_missing_file(self) -> None:
        with self.assertRaises(FileNotFoundError):
            offline_llm.main(["template", "--capture", "nonexistent.json"])

    def test_markov_cli_generate_untrained(self) -> None:
        """Markov --generate without --train warns about no data."""
        import io
        orig_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            offline_llm.main(["markov", "--generate"])
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = orig_stdout
        self.assertIn("No training data", output)

    def test_markov_cli_train_then_generate(self) -> None:
        """Markov train+generate from .md files."""
        md_dir = Path(self.tmp_dir.name) / "captures"
        md_dir.mkdir()
        (md_dir / "test.md").write_text("""\
## Analysis
Bottom detected at 57.3 fm (high confidence). Chum predicted.
""", encoding="utf-8")

        import io
        orig_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            offline_llm.main([
                "markov",
                "--train", str(md_dir),
                "--generate",
                "--max-words", "30",
            ])
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = orig_stdout
        self.assertIn("fm", output)

    def test_gemma_cli_no_model(self) -> None:
        """Gemma CLI without model installed prints error."""
        import io
        orig_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            offline_llm.main([
                "gemma",
                "--capture", str(self.json_path),
                "--model", "nonexistent.gguf",
            ])
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = orig_stdout
        # Should produce an error message about missing model/deps
        self.assertTrue(
            "ERROR" in output or "not installed" in output.lower(),
            f"Expected error output, got: {output[:200]}"
        )


# ──────────────────────────────────────────────────────────────────────
#  Tests — Gemma prompt builder (doesn't need llama-cpp)
# ──────────────────────────────────────────────────────────────────────

class TestGemmaPrompt(unittest.TestCase):
    """Tests for the Gemma prompt builder (no llama-cpp needed)."""

    def test_builds_prompt(self) -> None:
        prompt = offline_llm._build_gemma_prompt(SAMPLE_CAPTURE)
        self.assertIsInstance(prompt, str)
        self.assertIn("5546.846N", prompt)
        self.assertIn("13141.895W", prompt)
        self.assertIn("SOG", prompt)
        self.assertIn("dual-band", prompt.lower())
        self.assertIn("60 fm", prompt)
        self.assertIn("Caption:", prompt)


# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
