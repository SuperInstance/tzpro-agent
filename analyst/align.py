"""
Voice-telemetry alignment pipeline for Analyst learning loop.

Two-stage architecture:
  Stage 1: Transcript generation (external Whisper CLI/API)
  Stage 2: Forced alignment via cross-attention-DTW or forced alignment

The 500ms budget rationale (docs/25_RESEARCH_LANDSCAPE.md Stream 4):
- Whisper's native timestamps FAIL the 500ms poisoning budget (HAL 2024: "very inaccurate")
- Forced alignment (WhisperX) passes the 500ms budget
- Cross-attention filtering achieves 20-50ms tolerance (Yeh 2025)

Core principle: Quarantine with reasons, never silent drops (docs/06).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Protocol

# =============================================================================
# Data Structures
# =============================================================================


@dataclass
class TranscriptWord:
    """A single word from Stage 1 transcript with coarse timestamps."""
    word: str
    start_ms: int
    end_ms: int
    conf: float  # Per-word confidence from Whisper

    def __post_init__(self):
        if self.start_ms < 0:
            raise ValueError(f"start_ms must be >= 0, got {self.start_ms}")
        if self.end_ms <= self.start_ms:
            raise ValueError(f"end_ms ({self.end_ms}) must be > start_ms ({self.start_ms})")
        if not 0.0 <= self.conf <= 1.0:
            raise ValueError(f"conf must be in [0, 1], got {self.conf}")


@dataclass
class AlignedWord:
    """A word after Stage 2 alignment with precise timestamps and confidence."""
    word: str
    start_ms: int
    end_ms: int
    conf: float  # Per-word confidence from Stage 2 backend

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    def __post_init__(self):
        if self.start_ms < 0:
            raise ValueError(f"start_ms must be >= 0, got {self.start_ms}")
        if self.end_ms <= self.start_ms:
            raise ValueError(f"end_ms ({self.end_ms}) must be > start_ms ({self.start_ms})")
        if not 0.0 <= self.conf <= 1.0:
            raise ValueError(f"conf must be in [0, 1], got {self.conf}")


@dataclass
class TrainingWindow:
    """A time-bounded slice of aligned words suitable for training."""
    start_ms: int
    end_ms: int
    words: List[AlignedWord]
    mean_conf: float
    status: str = "PASS"  # PASS | QUARANTINED
    quarantine_reason: str | None = None

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    @property
    def word_count(self) -> int:
        return len(self.words)

    @property
    def midpoint_ms(self) -> int:
        return (self.start_ms + self.end_ms) // 2


@dataclass
class TelemetryPair:
    """A training window joined with its nearest telemetry snapshot."""
    window: TrainingWindow
    telemetry: dict[str, Any] | None
    telemetry_ts: int | None
    telemetry_delta_ms: int | None
    misaligned: bool  # True if delta > 250ms (RQ-001 threshold)


@dataclass
class QuarantineRecord:
    """Record of a quarantined window with explanation."""
    window: TrainingWindow
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Stage 1: Transcript Backend Interface (External Whisper)
# =============================================================================


class Stage1Backend(Protocol):
    """
    Interface for Stage 1 transcript generation.

    Implementations call external Whisper (CLI, API, or whisper-timestamped).
    The CONTRACT is what matters; real backends are plugged in at runtime.
    """

    def transcribe(self, audio_path: str | Path) -> list[dict]:
        """
        Transcribe audio and return words with coarse timestamps.

        Returns:
            List of dicts with keys: {word, start_ms, end_ms, conf}
        """
        ...


class StubStage1Backend:
    """
    Stub backend for testing. Returns synthetic word-level transcripts.
    In production, replace with actual Whisper CLI/API calls.
    """

    def __init__(self, words: list[dict] | None = None):
        self.words = words or []

    def transcribe(self, audio_path: str | Path) -> list[dict]:
        # Stub: return pre-configured synthetic data
        return [
            {
                "word": w["word"],
                "start_ms": w["start_ms"],
                "end_ms": w["end_ms"],
                "conf": w["conf"]
            }
            for w in self.words
        ]


# =============================================================================
# Stage 2: Alignment Backend Interface (Forced Alignment)
# =============================================================================


class Stage2Backend(Protocol):
    """
    Interface for Stage 2 forced alignment.

    Implementations use:
    - WhisperX (forced alignment, 20-50ms per ICASSP 2023)
    - cross-attention-DTW (20-50ms per Yeh 2025)
    - Custom forced alignment

    The CONTRACT is what matters; real backends are plugged in at runtime.
    """

    def align(
        self,
        transcript_words: list[TranscriptWord],
        audio_duration_ms: int,
        audio_path: str | Path | None = None
    ) -> list[AlignedWord]:
        """
        Refine timestamps via forced alignment.

        Args:
            transcript_words: Coarse words from Stage 1
            audio_duration_ms: Total audio duration in ms
            audio_path: Optional path to audio file

        Returns:
            Refined AlignedWord list with precise timestamps and confidence
        """
        ...


class StubStage2Backend:
    """
    Stub backend for testing. Implements passthrough with confidence.
    In production, replace with WhisperX or custom forced alignment.
    """

    def __init__(self, base_confidence: float = 0.8):
        self.base_confidence = base_confidence

    def align(
        self,
        transcript_words: list[TranscriptWord],
        audio_duration_ms: int,
        audio_path: str | Path | None = None
    ) -> list[AlignedWord]:
        # Stub: passthrough with confidence adjustment
        # Real implementation would run forced alignment
        return [
            AlignedWord(
                word=w.word,
                start_ms=w.start_ms,
                end_ms=w.end_ms,
                conf=w.conf * self.base_confidence
            )
            for w in transcript_words
        ]


# =============================================================================
# Core Pipeline Functions
# =============================================================================


def align_words(
    transcript_words: list[dict | TranscriptWord],
    audio_duration_ms: int,
    stage2_backend: Stage2Backend | None = None
) -> list[AlignedWord]:
    """
    Stage 2 alignment: refine coarse transcript via forced alignment.

    Args:
        transcript_words: List of {word, start_ms, end_ms, conf} from Stage 1
        audio_duration_ms: Total audio duration in ms
        stage2_backend: Optional alignment backend (uses stub if None)

    Returns:
        List of AlignedWord with refined timestamps and confidence

    Contract:
        - Input timestamps are coarse (Whisper native)
        - Output timestamps are precise (forced alignment)
        - Per-word confidence is preserved/refined from Stage 2 backend
    """
    # Normalize input to TranscriptWord objects
    words = []
    for w in transcript_words:
        if isinstance(w, TranscriptWord):
            words.append(w)
        else:
            words.append(TranscriptWord(
                word=w["word"],
                start_ms=w["start_ms"],
                end_ms=w["end_ms"],
                conf=w["conf"]
            ))

    # Use stub backend if none provided
    backend = stage2_backend or StubStage2Backend()

    # Run alignment
    aligned = backend.align(words, audio_duration_ms)

    return aligned


def gate_windows(
    aligned_words: list[AlignedWord],
    min_word_conf: float = 0.6,
    max_slack_ms: int = 500
) -> tuple[list[TrainingWindow], list[QuarantineRecord]]:
    """
    Gate aligned words into training windows with confidence and slack validation.

    A window PASSes only if:
        1. EVERY word has confidence >= min_word_conf
        2. Total slack (gaps between words) <= max_slack_ms

    Windows that fail are QUARANTINED with reasons (docs/06 principle).
    Never silently drop data.

    Args:
        aligned_words: List of aligned words from Stage 2
        min_word_conf: Minimum confidence threshold per word (default 0.6)
        max_slack_ms: Maximum allowed gap between words (default 500ms per docs/25)

    Returns:
        (windows, quarantine_records) - Both lists; nothing is silently dropped

    The 500ms budget rationale (docs/25 Stream 4):
        - Whisper native timestamps have >500ms error (HAL 2024)
        - Forced alignment achieves 20-50ms (WhisperX ICASSP 2023, Yeh 2025)
        - This gating ensures only aligned windows enter training
    """
    if not aligned_words:
        return [], []

    windows: list[TrainingWindow] = []
    quarantined: list[QuarantineRecord] = []

    # Single window implementation (can be extended for sliding window)
    # For now, each call creates one window from all provided words

    # Check per-word confidence
    low_conf_words = [w for w in aligned_words if w.conf < min_word_conf]
    if low_conf_words:
        # Quarantine entire window if any word fails confidence
        window = TrainingWindow(
            start_ms=aligned_words[0].start_ms,
            end_ms=aligned_words[-1].end_ms,
            words=aligned_words,
            mean_conf=sum(w.conf for w in aligned_words) / len(aligned_words),
            status="QUARANTINED",
            quarantine_reason=f"low_confidence: {len(low_conf_words)} words below {min_word_conf}"
        )
        quarantined.append(QuarantineRecord(
            window=window,
            reason="low_confidence",
            metadata={
                "min_word_conf": min_word_conf,
                "failed_count": len(low_conf_words),
                "failed_words": [w.word for w in low_conf_words]
            }
        ))
        return windows, quarantined

    # Check slack (gaps between consecutive words)
    slack_ms = 0
    for i in range(1, len(aligned_words)):
        gap = aligned_words[i].start_ms - aligned_words[i-1].end_ms
        if gap > 0:
            slack_ms += gap

    if slack_ms > max_slack_ms:
        # Quarantine due to excessive slack
        window = TrainingWindow(
            start_ms=aligned_words[0].start_ms,
            end_ms=aligned_words[-1].end_ms,
            words=aligned_words,
            mean_conf=sum(w.conf for w in aligned_words) / len(aligned_words),
            status="QUARANTINED",
            quarantine_reason=f"excess_slack: {slack_ms}ms > {max_slack_ms}ms"
        )
        quarantined.append(QuarantineRecord(
            window=window,
            reason="excess_slack",
            metadata={
                "slack_ms": slack_ms,
                "max_slack_ms": max_slack_ms
            }
        ))
        return windows, quarantined

    # Window passes all gates
    window = TrainingWindow(
        start_ms=aligned_words[0].start_ms,
        end_ms=aligned_words[-1].end_ms,
        words=aligned_words,
        mean_conf=sum(w.conf for w in aligned_words) / len(aligned_words),
        status="PASS"
    )
    windows.append(window)

    return windows, quarantined


def pair_with_telemetry(
    windows: list[TrainingWindow],
    telemetry_jsonl_path: str | Path,
    max_delta_ms: int = 250
) -> tuple[list[TelemetryPair], list[TelemetryPair]]:
    """
    Pair training windows with nearest telemetry snapshots.

    For each window, finds the telemetry row with timestamp closest to the
    window's midpoint. Records the delta and flags misalignment if > max_delta_ms.

    Args:
        windows: List of training windows from gate_windows()
        telemetry_jsonl_path: Path to telemetry JSONL file
        max_delta_ms: Maximum allowed delta in ms (default 250ms per RQ-001)

    Returns:
        (aligned_pairs, misaligned_pairs) - Separated for convenience

    Telemetry JSONL format:
        {"ts": 1234567890, "field1": "value1", ...}
        where ts is Unix timestamp in milliseconds
    """
    # Load telemetry
    telemetry_path = Path(telemetry_jsonl_path)
    telemetry_data: list[dict] = []

    if telemetry_path.exists():
        with open(telemetry_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    telemetry_data.append(json.loads(line))

    aligned: list[TelemetryPair] = []
    misaligned: list[TelemetryPair] = []

    for window in windows:
        if not telemetry_data:
            # No telemetry available
            pair = TelemetryPair(
                window=window,
                telemetry=None,
                telemetry_ts=None,
                telemetry_delta_ms=None,
                misaligned=False  # Can't determine without telemetry
            )
            aligned.append(pair)
            continue

        # Find nearest telemetry by timestamp
        midpoint = window.midpoint_ms

        # Assume telemetry timestamps are in ms (convert from seconds if needed)
        nearest = None
        min_delta = float('inf')

        for row in telemetry_data:
            ts = row.get('ts')
            if ts is None:
                continue

            # Handle both seconds and ms timestamps
            ts_ms = int(ts) if ts > 10000000000 else int(ts * 1000)

            delta = abs(ts_ms - midpoint)
            if delta < min_delta:
                min_delta = delta
                nearest = row

        delta_ms = int(min_delta)
        is_misaligned = delta_ms > max_delta_ms

        pair = TelemetryPair(
            window=window,
            telemetry=nearest,
            telemetry_ts=int(nearest['ts']) if nearest else None,
            telemetry_delta_ms=delta_ms,
            misaligned=is_misaligned
        )

        if is_misaligned:
            misaligned.append(pair)
        else:
            aligned.append(pair)

    return aligned, misaligned


def write_quarantine_log(
    records: list[QuarantineRecord],
    output_path: str | Path
) -> None:
    """
    Write quarantine log to JSONL file.

    Each line: {reason, window_start_ms, window_end_ms, word_count, mean_conf, metadata}

    Args:
        records: List of quarantine records from gate_windows()
        output_path: Path to output JSONL file
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        for record in records:
            log_entry = {
                "reason": record.reason,
                "window_start_ms": record.window.start_ms,
                "window_end_ms": record.window.end_ms,
                "word_count": record.window.word_count,
                "mean_conf": record.window.mean_conf,
                "metadata": record.metadata
            }
            f.write(json.dumps(log_entry) + '\n')


# =============================================================================
# Convenience Pipeline Orchestration
# =============================================================================


def process_audio_to_windows(
    transcript_words: list[dict],
    audio_duration_ms: int,
    telemetry_jsonl_path: str | Path | None = None,
    min_word_conf: float = 0.6,
    max_slack_ms: int = 500,
    max_telemetry_delta_ms: int = 250,
    stage2_backend: Stage2Backend | None = None,
    quarantine_log_path: str | Path | None = None
) -> dict:
    """
    End-to-end pipeline: transcript -> aligned -> gated -> telemetry paired.

    Args:
        transcript_words: Stage 1 output (list of {word, start_ms, end_ms, conf})
        audio_duration_ms: Total audio duration in ms
        telemetry_jsonl_path: Optional path to telemetry JSONL
        min_word_conf: Minimum confidence threshold per word
        max_slack_ms: Maximum allowed gap between words
        max_telemetry_delta_ms: Maximum allowed telemetry delta
        stage2_backend: Optional Stage 2 alignment backend
        quarantine_log_path: Optional path to write quarantine log

    Returns:
        Dict with keys:
            - windows: List of TrainingWindow (PASS only)
            - aligned_pairs: List of TelemetryPair (delta <= threshold)
            - misaligned_pairs: List of TelemetryPair (delta > threshold)
            - quarantine_records: List of QuarantineRecord
            - quarantine_log: Path to quarantine log (if written)
    """
    # Stage 2: Align
    aligned = align_words(transcript_words, audio_duration_ms, stage2_backend)

    # Gate into windows
    windows, quarantined = gate_windows(aligned, min_word_conf, max_slack_ms)

    # Write quarantine log
    log_path = None
    if quarantine_log_path and quarantined:
        write_quarantine_log(quarantined, quarantine_log_path)
        log_path = str(quarantine_log_path)

    # Pair with telemetry
    if telemetry_jsonl_path:
        aligned_pairs, misaligned_pairs = pair_with_telemetry(
            windows, telemetry_jsonl_path, max_telemetry_delta_ms
        )
    else:
        aligned_pairs = [TelemetryPair(w, None, None, None, False) for w in windows]
        misaligned_pairs = []

    return {
        "windows": windows,
        "aligned_pairs": aligned_pairs,
        "misaligned_pairs": misaligned_pairs,
        "quarantine_records": quarantined,
        "quarantine_log": log_path
    }
