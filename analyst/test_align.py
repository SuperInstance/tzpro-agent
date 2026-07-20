"""
Unit tests for analyst/align.py voice-telemetry alignment pipeline.

Tests use SYNTHETIC data only — no audio, no Whisper calls.
The CONTRACT is what matters; backend implementations are pluggable.
"""

import json
import tempfile
import unittest
from pathlib import Path

from analyst.align import (
    TranscriptWord,
    AlignedWord,
    TrainingWindow,
    QuarantineRecord,
    TelemetryPair,
    StubStage1Backend,
    StubStage2Backend,
    align_words,
    gate_windows,
    pair_with_telemetry,
    write_quarantine_log,
    process_audio_to_windows,
)


class TestTranscriptWord(unittest.TestCase):
    """Test TranscriptWord validation."""

    def test_valid_word(self):
        """Valid word should be created."""
        w = TranscriptWord("hello", 0, 500, 0.9)
        self.assertEqual(w.word, "hello")
        self.assertEqual(w.start_ms, 0)
        self.assertEqual(w.end_ms, 500)
        self.assertEqual(w.conf, 0.9)

    def test_negative_start_ms_raises(self):
        """Negative start_ms should raise."""
        with self.assertRaises(ValueError):
            TranscriptWord("hello", -100, 500, 0.9)

    def test_end_before_start_raises(self):
        """end_ms <= start_ms should raise."""
        with self.assertRaises(ValueError):
            TranscriptWord("hello", 500, 500, 0.9)
        with self.assertRaises(ValueError):
            TranscriptWord("hello", 500, 400, 0.9)

    def test_confidence_out_of_range_raises(self):
        """Confidence outside [0, 1] should raise."""
        with self.assertRaises(ValueError):
            TranscriptWord("hello", 0, 500, -0.1)
        with self.assertRaises(ValueError):
            TranscriptWord("hello", 0, 500, 1.1)


class TestAlignedWord(unittest.TestCase):
    """Test AlignedWord validation and properties."""

    def test_valid_aligned_word(self):
        """Valid aligned word should be created."""
        w = AlignedWord("hello", 0, 500, 0.85)
        self.assertEqual(w.word, "hello")
        self.assertEqual(w.duration_ms, 500)

    def test_validation_same_as_transcript_word(self):
        """AlignedWord has same validation as TranscriptWord."""
        with self.assertRaises(ValueError):
            AlignedWord("hello", -10, 500, 0.9)
        with self.assertRaises(ValueError):
            AlignedWord("hello", 500, 400, 0.9)


class TestTrainingWindow(unittest.TestCase):
    """Test TrainingWindow properties."""

    def test_window_properties(self):
        """Window properties should compute correctly."""
        words = [
            AlignedWord("hello", 0, 500, 0.9),
            AlignedWord("world", 600, 1000, 0.8),
        ]
        window = TrainingWindow(
            start_ms=0,
            end_ms=1000,
            words=words,
            mean_conf=0.85,
            status="PASS"
        )
        self.assertEqual(window.duration_ms, 1000)
        self.assertEqual(window.word_count, 2)
        self.assertEqual(window.midpoint_ms, 500)


class TestStubBackends(unittest.TestCase):
    """Test stub backends used for testing."""

    def test_stub_stage1_returns_configured_words(self):
        """Stub Stage 1 should return pre-configured words."""
        words = [
            {"word": "hello", "start_ms": 0, "end_ms": 500, "conf": 0.9},
            {"word": "world", "start_ms": 500, "end_ms": 1000, "conf": 0.8},
        ]
        backend = StubStage1Backend(words)
        result = backend.transcribe("dummy_audio.wav")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["word"], "hello")
        self.assertEqual(result[1]["conf"], 0.8)

    def test_stub_stage2_passthrough_with_confidence(self):
        """Stub Stage 2 should passthrough with confidence adjustment."""
        words = [
            TranscriptWord("hello", 0, 500, 0.9),
            TranscriptWord("world", 500, 1000, 0.8),
        ]
        backend = StubStage2Backend(base_confidence=0.95)
        result = backend.align(words, 1000)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].word, "hello")
        # Confidence should be adjusted
        self.assertAlmostEqual(result[0].conf, 0.9 * 0.95)


class TestAlignWords(unittest.TestCase):
    """Test Stage 2 alignment function."""

    def test_align_with_dict_input(self):
        """Should handle dict input (from Stage 1)."""
        input_words = [
            {"word": "hello", "start_ms": 0, "end_ms": 500, "conf": 0.9},
            {"word": "world", "start_ms": 500, "end_ms": 1000, "conf": 0.8},
        ]
        result = align_words(input_words, audio_duration_ms=1000)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], AlignedWord)
        self.assertEqual(result[0].word, "hello")

    def test_align_with_transcript_word_input(self):
        """Should handle TranscriptWord input."""
        input_words = [
            TranscriptWord("hello", 0, 500, 0.9),
            TranscriptWord("world", 500, 1000, 0.8),
        ]
        result = align_words(input_words, audio_duration_ms=1000)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].word, "hello")

    def test_align_uses_custom_backend(self):
        """Should use provided Stage 2 backend."""
        input_words = [
            {"word": "hello", "start_ms": 0, "end_ms": 500, "conf": 0.9},
        ]
        backend = StubStage2Backend(base_confidence=0.5)
        result = align_words(input_words, audio_duration_ms=1000, stage2_backend=backend)
        self.assertAlmostEqual(result[0].conf, 0.9 * 0.5)

    def test_align_empty_list(self):
        """Should handle empty input."""
        result = align_words([], audio_duration_ms=1000)
        self.assertEqual(len(result), 0)


class TestGateWindows(unittest.TestCase):
    """Test window gating with confidence and slack validation."""

    def test_good_window_passes(self):
        """Window with all high-confidence words and minimal slack should pass."""
        words = [
            AlignedWord("set", 0, 300, 0.9),
            AlignedWord("course", 400, 800, 0.85),
            AlignedWord("two", 900, 1100, 0.88),
        ]
        windows, quarantined = gate_windows(words, min_word_conf=0.6, max_slack_ms=500)

        self.assertEqual(len(windows), 1)
        self.assertEqual(len(quarantined), 0)
        self.assertEqual(windows[0].status, "PASS")
        self.assertIsNone(windows[0].quarantine_reason)

    def test_one_bad_word_quarantines_whole_window(self):
        """Window with one low-confidence word should be quarantined."""
        words = [
            AlignedWord("set", 0, 300, 0.9),
            AlignedWord("course", 400, 800, 0.5),  # Below 0.6 threshold
            AlignedWord("two", 900, 1100, 0.88),
        ]
        windows, quarantined = gate_windows(words, min_word_conf=0.6, max_slack_ms=500)

        self.assertEqual(len(windows), 0)
        self.assertEqual(len(quarantined), 1)
        self.assertEqual(quarantined[0].reason, "low_confidence")
        self.assertIn("course", quarantined[0].metadata["failed_words"])

    def test_excess_slack_quarantines_window(self):
        """Window with gaps > 500ms should be quarantined."""
        words = [
            AlignedWord("set", 0, 300, 0.9),
            AlignedWord("course", 400, 800, 0.85),
            # Large gap: 900ms gap before next word
            AlignedWord("two", 1700, 1900, 0.88),
        ]
        # Slack = (400-800) + (1700-800) = 100 + 900 = 1000ms
        windows, quarantined = gate_windows(words, min_word_conf=0.6, max_slack_ms=500)

        self.assertEqual(len(windows), 0)
        self.assertEqual(len(quarantined), 1)
        self.assertEqual(quarantined[0].reason, "excess_slack")
        self.assertEqual(quarantined[0].metadata["slack_ms"], 1000)

    def test_edge_case_slack_exactly_500ms_passes(self):
        """Slack exactly at threshold should pass."""
        words = [
            AlignedWord("set", 0, 300, 0.9),
            AlignedWord("course", 400, 800, 0.85),
            # Slack = 100 + (1000-800) = 300ms total
            AlignedWord("two", 1000, 1200, 0.88),
        ]
        # Add another gap to reach exactly 500ms
        words = [
            AlignedWord("set", 0, 300, 0.9),
            AlignedWord("course", 800, 1100, 0.85),  # 500ms gap
        ]
        windows, quarantined = gate_windows(words, min_word_conf=0.6, max_slack_ms=500)

        self.assertEqual(len(windows), 1)
        self.assertEqual(len(quarantined), 0)

    def test_edge_case_confidence_exactly_threshold_passes(self):
        """Confidence exactly at threshold should pass."""
        words = [
            AlignedWord("set", 0, 300, 0.6),  # Exactly at threshold
            AlignedWord("course", 400, 800, 0.85),
        ]
        windows, quarantined = gate_windows(words, min_word_conf=0.6, max_slack_ms=500)

        self.assertEqual(len(windows), 1)
        self.assertEqual(len(quarantined), 0)

    def test_empty_words_returns_empty(self):
        """Empty word list should return empty results."""
        windows, quarantined = gate_windows([], min_word_conf=0.6, max_slack_ms=500)

        self.assertEqual(len(windows), 0)
        self.assertEqual(len(quarantined), 0)

    def test_quarantine_status_set_on_window(self):
        """Quarantined window should have status and reason set."""
        words = [
            AlignedWord("hello", 0, 300, 0.5),  # Low confidence
        ]
        windows, quarantined = gate_windows(words, min_word_conf=0.6, max_slack_ms=500)

        self.assertEqual(len(quarantined), 1)
        self.assertEqual(quarantined[0].window.status, "QUARANTINED")
        self.assertIsNotNone(quarantined[0].window.quarantine_reason)


class TestPairWithTelemetry(unittest.TestCase):
    """Test telemetry pairing with nearest-row logic."""

    def setUp(self):
        """Create temporary telemetry file for tests."""
        self.temp_dir = tempfile.mkdtemp()
        self.telemetry_path = Path(self.temp_dir) / "telemetry.jsonl"

        # Create test telemetry: timestamps in milliseconds (Unix epoch format)
        # Using millisecond Unix timestamps that look like real timestamps (> 10000000000)
        # to ensure they're correctly identified as milliseconds
        telemetry_data = [
            {"ts": 1700000001000, "heading": 45.0, "speed": 5.2},
            {"ts": 1700000002000, "heading": 46.0, "speed": 5.3},
            {"ts": 1700000003000, "heading": 47.0, "speed": 5.1},
            {"ts": 1700000004000, "heading": 48.0, "speed": 5.4},
        ]
        with open(self.telemetry_path, 'w') as f:
            for row in telemetry_data:
                f.write(json.dumps(row) + '\n')

    def test_nearest_row_found(self):
        """Should find telemetry row closest to window midpoint."""
        # Window midpoint at 1700000002500 -> should match ts=1700000002000 (delta=500)
        # In case of tie, first found wins
        words = [AlignedWord("test", 1700000002000, 1700000003000, 0.9)]  # midpoint=1700000002500
        window = TrainingWindow(
            start_ms=1700000002000,
            end_ms=1700000003000,
            words=words,
            mean_conf=0.9,
            status="PASS"
        )

        aligned, misaligned = pair_with_telemetry(
            [window], self.telemetry_path, max_delta_ms=1000
        )

        self.assertEqual(len(aligned), 1)
        self.assertEqual(len(misaligned), 0)
        self.assertIsNotNone(aligned[0].telemetry)
        self.assertEqual(aligned[0].telemetry["heading"], 46.0)
        self.assertEqual(aligned[0].telemetry_delta_ms, 500)

    def test_misaligned_flag_at_300ms_delta(self):
        """Delta > 250ms should flag misaligned."""
        # Window midpoint at 1700000000800, nearest telemetry at 1700000001000 (delta=200ms)
        # Actually, let's use a midpoint far from any telemetry
        # Window: 1700000000400 to 1700000000600, midpoint=1700000000500
        # Nearest telemetry: 1700000001000, delta=500ms (> 250ms threshold)
        words = [AlignedWord("test", 1700000000400, 1700000000600, 0.9)]  # midpoint=1700000000500
        window = TrainingWindow(
            start_ms=1700000000400,
            end_ms=1700000000600,
            words=words,
            mean_conf=0.9,
            status="PASS"
        )

        aligned, misaligned = pair_with_telemetry(
            [window], self.telemetry_path, max_delta_ms=250
        )

        self.assertEqual(len(aligned), 0)
        self.assertEqual(len(misaligned), 1)
        self.assertTrue(misaligned[0].misaligned)
        self.assertEqual(misaligned[0].telemetry_delta_ms, 500)

    def test_delta_exactly_threshold_passes(self):
        """Delta exactly at threshold should not misalign."""
        words = [AlignedWord("test", 1700000001750, 1700000002250, 0.9)]  # midpoint=1700000002000
        window = TrainingWindow(
            start_ms=1700000001750,
            end_ms=1700000002250,
            words=words,
            mean_conf=0.9,
            status="PASS"
        )

        aligned, misaligned = pair_with_telemetry(
            [window], self.telemetry_path, max_delta_ms=250
        )

        self.assertEqual(len(aligned), 1)
        self.assertEqual(len(misaligned), 0)
        # Delta should be 0 since midpoint=1700000002000 matches telemetry ts=1700000002000
        self.assertEqual(aligned[0].telemetry_delta_ms, 0)

    def test_missing_telemetry_file(self):
        """Missing telemetry file should return pairs without telemetry."""
        words = [AlignedWord("test", 0, 500, 0.9)]
        window = TrainingWindow(
            start_ms=0,
            end_ms=500,
            words=words,
            mean_conf=0.9,
            status="PASS"
        )

        aligned, misaligned = pair_with_telemetry(
            [window], Path("nonexistent.jsonl"), max_delta_ms=250
        )

        self.assertEqual(len(aligned), 1)
        self.assertIsNone(aligned[0].telemetry)
        self.assertFalse(aligned[0].misaligned)


class TestWriteQuarantineLog(unittest.TestCase):
    """Test quarantine log writing."""

    def test_quarantine_log_written(self):
        """Quarantine log should be written as JSONL."""
        words = [AlignedWord("test", 0, 500, 0.5)]
        window = TrainingWindow(
            start_ms=0,
            end_ms=500,
            words=words,
            mean_conf=0.5,
            status="QUARANTINED",
            quarantine_reason="low_confidence"
        )
        record = QuarantineRecord(
            window=window,
            reason="low_confidence",
            metadata={"failed_count": 1}
        )

        temp_path = Path(tempfile.mkdtemp()) / "quarantine.jsonl"
        write_quarantine_log([record], temp_path)

        self.assertTrue(temp_path.exists())

        with open(temp_path, 'r') as f:
            lines = f.readlines()
            self.assertEqual(len(lines), 1)
            log_entry = json.loads(lines[0])
            self.assertEqual(log_entry["reason"], "low_confidence")
            self.assertEqual(log_entry["window_start_ms"], 0)
            self.assertEqual(log_entry["window_end_ms"], 500)
            self.assertEqual(log_entry["word_count"], 1)
            self.assertEqual(log_entry["mean_conf"], 0.5)
            self.assertEqual(log_entry["metadata"]["failed_count"], 1)

    def test_empty_quarantine_creates_file(self):
        """Empty quarantine should create empty file."""
        temp_path = Path(tempfile.mkdtemp()) / "empty.jsonl"
        write_quarantine_log([], temp_path)

        self.assertTrue(temp_path.exists())
        with open(temp_path, 'r') as f:
            content = f.read()
            self.assertEqual(content, "")


class TestProcessAudioToWindows(unittest.TestCase):
    """Test end-to-end pipeline orchestration."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.telemetry_path = self.temp_dir / "telemetry.jsonl"
        self.quarantine_path = self.temp_dir / "quarantine.jsonl"

        # Create test telemetry with Unix epoch timestamps (ms)
        telemetry_data = [
            {"ts": 1700000001350, "heading": 45.0, "speed": 5.2},
        ]
        with open(self.telemetry_path, 'w') as f:
            for row in telemetry_data:
                f.write(json.dumps(row) + '\n')

    def test_full_pipeline_good_window(self):
        """Good window should pass entire pipeline."""
        # Use Unix epoch timestamps matching telemetry reference frame
        transcript = [
            {"word": "set", "start_ms": 1700000001000, "end_ms": 1700000001300, "conf": 0.9},
            {"word": "course", "start_ms": 1700000001300, "end_ms": 1700000001700, "conf": 0.85},
        ]

        result = process_audio_to_windows(
            transcript_words=transcript,
            audio_duration_ms=2000,
            telemetry_jsonl_path=self.telemetry_path,
            min_word_conf=0.6,
            max_slack_ms=500,
            max_telemetry_delta_ms=250,
            quarantine_log_path=self.quarantine_path,
        )

        self.assertEqual(len(result["windows"]), 1)
        self.assertEqual(len(result["aligned_pairs"]), 1)
        self.assertEqual(len(result["misaligned_pairs"]), 0)
        self.assertEqual(len(result["quarantine_records"]), 0)

    def test_full_pipeline_quarantined_window(self):
        """Low confidence window should be quarantined."""
        transcript = [
            {"word": "set", "start_ms": 1000, "end_ms": 1300, "conf": 0.5},  # Below threshold
        ]

        result = process_audio_to_windows(
            transcript_words=transcript,
            audio_duration_ms=2000,
            telemetry_jsonl_path=self.telemetry_path,
            min_word_conf=0.6,
            max_slack_ms=500,
            quarantine_log_path=self.quarantine_path,
        )

        self.assertEqual(len(result["windows"]), 0)
        self.assertEqual(len(result["quarantine_records"]), 1)
        self.assertEqual(result["quarantine_records"][0].reason, "low_confidence")
        self.assertEqual(result["quarantine_log"], str(self.quarantine_path))

        # Verify quarantine log was written
        self.assertTrue(self.quarantine_path.exists())
        with open(self.quarantine_path, 'r') as f:
            log_entry = json.loads(f.readline())
            self.assertEqual(log_entry["reason"], "low_confidence")

    def test_full_pipeline_without_telemetry(self):
        """Pipeline should work without telemetry."""
        transcript = [
            {"word": "test", "start_ms": 0, "end_ms": 500, "conf": 0.9},
        ]

        result = process_audio_to_windows(
            transcript_words=transcript,
            audio_duration_ms=1000,
            telemetry_jsonl_path=None,
            min_word_conf=0.6,
        )

        self.assertEqual(len(result["windows"]), 1)
        self.assertEqual(len(result["aligned_pairs"]), 1)
        self.assertIsNone(result["aligned_pairs"][0].telemetry)


class TestQuarantinePrinciple(unittest.TestCase):
    """
    Verify docs/06 quarantine principle: never silent drops.

    All filtered data must be tracked with reasons.
    """

    def test_quarantine_never_silent_drops(self):
        """All filtered windows must appear in quarantine records."""
        words = [
            AlignedWord("set", 0, 300, 0.9),
            AlignedWord("course", 400, 800, 0.5),  # Low confidence
        ]
        windows, quarantined = gate_windows(words, min_word_conf=0.6, max_slack_ms=500)

        # Total words = 2, windows (pass) = 0, quarantined words should = 2
        self.assertEqual(len(windows), 0)
        self.assertEqual(len(quarantined), 1)
        # Quarantined window contains all words
        self.assertEqual(quarantined[0].window.word_count, 2)

    def test_quarantine_reasons_are_specific(self):
        """Quarantine reasons must be specific and actionable."""
        # Test low confidence reason
        words_low_conf = [AlignedWord("test", 0, 500, 0.5)]
        windows, quarantined = gate_windows(words_low_conf, min_word_conf=0.6, max_slack_ms=500)
        self.assertEqual(quarantined[0].reason, "low_confidence")
        self.assertIn("failed_words", quarantined[0].metadata)

        # Test excess slack reason
        words_slack = [
            AlignedWord("test", 0, 300, 0.9),
            AlignedWord("gap", 1000, 1200, 0.9),
        ]
        windows, quarantined = gate_windows(words_slack, min_word_conf=0.6, max_slack_ms=500)
        self.assertEqual(quarantined[0].reason, "excess_slack")
        self.assertIn("slack_ms", quarantined[0].metadata)


def print_test_summary():
    """Print test summary after running tests."""
    # Create test suite
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(__import__(__name__))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Print summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")

    if result.wasSuccessful():
        print("\n[OK] ALL TESTS PASSED")
    else:
        print("\n[FAIL] SOME TESTS FAILED")

    print("=" * 60)

    return result.wasSuccessful()


if __name__ == "__main__":
    import sys
    success = print_test_summary()
    sys.exit(0 if success else 1)
