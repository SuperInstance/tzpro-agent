# Analyst — Voice-Telemetry Alignment Pipeline

Voice-telemetry alignment for the Analyst learning loop. Two-stage pipeline with confidence gating and telemetry pairing for training data generation.

## Overview

The Analyst pipeline transforms raw audio + telemetry into training windows for learning from demonstration. It implements the two-stage alignment strategy validated in research literature:

**Stage 1: Transcript Generation** (External Whisper)
- Whisper CLI, API, or whisper-timestamped
- Output: Coarse word timestamps with per-word confidence

**Stage 2: Forced Alignment** (Pluggable Backend)
- WhisperX (ICASSP 2023: 20-50ms tolerance)
- Cross-attention-DTW (Yeh 2025: 20-50ms tolerance)
- Custom forced alignment implementations

**Output**: Training windows paired with telemetry, quarantined low-quality data.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        STAGE 1: Transcript                         │
│                   (External Whisper Backend)                        │
│  Input: Audio                                                       │
│  Output: [{word, start_ms, end_ms, conf}, ...]                     │
└──────────────────────────────┬────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        STAGE 2: Alignment                            │
│                   (Pluggable Alignment Backend)                      │
│  Input: Coarse transcript                                           │
│  Output: AlignedWord[] with refined timestamps + confidence         │
└──────────────────────────────┬────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         Gating Layer                                 │
│  • Per-word confidence threshold (default 0.6)                      │
│  • Max slack validation (default 500ms)                             │
│  • QUARANTINE with reasons (no silent drops)                        │
└──────────────────────────────┬────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Telemetry Pairing                                 │
│  • Nearest-row telemetry by timestamp                               │
│  • Delta calculation (window midpoint vs telemetry ts)              │
│  • Misalignment flag if delta > 250ms (RQ-001)                      │
└──────────────────────────────┬────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Training Windows                                 │
│  [{window, telemetry_snapshot, delta_ms, misaligned}, ...]         │
└─────────────────────────────────────────────────────────────────────┘
```

## The 500ms Budget Rationale

Why do we need two-stage alignment? Research evidence:

| Source | Finding | Relevance |
|--------|---------|-----------|
| [HAL 2024](https://hal.science/hal-04404777v1/document) | Whisper native timestamps are "very inaccurate" | **FAILS 500ms budget** |
| [WhisperX ICASSP 2023](https://arxiv.org/abs/2303.00747) | Forced alignment achieves 20-50ms tolerance | **PASSES 500ms budget** |
| [Yeh 2025](https://arxiv.org/pdf/2509.09987) | Cross-attention filtering: 20-50ms | **PASSES 500ms budget** |

**Conclusion**: Whisper native timestamps cannot be trusted for sensor-aligned learning. Forced alignment is required.

## Usage

### Basic Pipeline

```python
from analyst.align import process_audio_to_windows

# Stage 1 output (from Whisper CLI/API)
transcript = [
    {"word": "set", "start_ms": 1000, "end_ms": 1300, "conf": 0.9},
    {"word": "course", "start_ms": 1300, "end_ms": 1700, "conf": 0.85},
    {"word": "two", "start_ms": 1700, "end_ms": 2000, "conf": 0.88},
]

result = process_audio_to_windows(
    transcript_words=transcript,
    audio_duration_ms=5000,
    telemetry_jsonl_path="telemetry.jsonl",
    min_word_conf=0.6,      # Per-word confidence threshold
    max_slack_ms=500,       # Max gap between words
    max_telemetry_delta_ms=250,  # Max telemetry delta
    quarantine_log_path="quarantine.jsonl",
)

# Access results
for pair in result["aligned_pairs"]:
    window = pair.window
    telemetry = pair.telemetry
    print(f"Window: {window.start_ms}-{window.end_ms}ms")
    print(f"Words: {' '.join(w.word for w in window.words)}")
    print(f"Mean confidence: {window.mean_conf:.2f}")
    print(f"Telemetry delta: {pair.telemetry_delta_ms}ms")
```

### Stage 1: Transcript Backend Interface

```python
from analyst.align import Stage1Backend, StubStage1Backend

# Custom Stage 1 backend (call Whisper CLI/API)
class WhisperBackend:
    def transcribe(self, audio_path: str | Path) -> list[dict]:
        # Call whisper CLI or API
        # Return: [{"word": "...", "start_ms": ..., "end_ms": ..., "conf": ...}]
        pass

# Use stub for testing
stub = StubStage1Backend(words=[...])
transcript = stub.transcribe("audio.wav")
```

### Stage 2: Alignment Backend Interface

```python
from analyst.align import Stage2Backend, AlignedWord, TranscriptWord

# Custom Stage 2 backend (forced alignment)
class WhisperXBackend:
    def align(self, transcript_words: list[TranscriptWord], audio_duration_ms: int) -> list[AlignedWord]:
        # Run WhisperX forced alignment
        # Return: AlignedWord[] with refined timestamps
        pass

# Use stub for testing
from analyst.align import StubStage2Backend
stub = StubStage2Backend(base_confidence=0.95)
aligned = stub.align(transcript_words, audio_duration_ms)
```

### Gating: Confidence and Slack

```python
from analyst.align import gate_windows, AlignedWord

words = [
    AlignedWord("set", 0, 300, 0.9),
    AlignedWord("course", 400, 800, 0.85),
    AlignedWord("two", 900, 1100, 0.88),
]

windows, quarantined = gate_windows(
    words,
    min_word_conf=0.6,   # All words must have conf >= 0.6
    max_slack_ms=500,     # Total gaps between words <= 500ms
)

# windows: PASSing training windows
# quarantined: Failed windows with reasons
```

### Telemetry Pairing

```python
from analyst.align import pair_with_telemetry, TrainingWindow

window = TrainingWindow(
    start_ms=1000,
    end_ms=2000,
    words=[...],
    mean_conf=0.85,
    status="PASS"
)

aligned, misaligned = pair_with_telemetry(
    windows=[window],
    telemetry_jsonl_path="telemetry.jsonl",
    max_delta_ms=250,  # Flag if delta > 250ms
)

# aligned: Pairs with telemetry delta <= 250ms
# misaligned: Pairs with telemetry delta > 250ms
```

## Data Structures

### AlignedWord
```python
@dataclass
class AlignedWord:
    word: str           # Word text
    start_ms: int       # Start time in milliseconds
    end_ms: int         # End time in milliseconds
    conf: float         # Per-word confidence [0, 1]

    @property
    def duration_ms(self) -> int: ...
```

### TrainingWindow
```python
@dataclass
class TrainingWindow:
    start_ms: int
    end_ms: int
    words: List[AlignedWord]
    mean_conf: float
    status: str  # "PASS" | "QUARANTINED"
    quarantine_reason: str | None

    @property
    def duration_ms(self) -> int: ...

    @property
    def word_count(self) -> int: ...

    @property
    def midpoint_ms(self) -> int: ...
```

### TelemetryPair
```python
@dataclass
class TelemetryPair:
    window: TrainingWindow
    telemetry: dict[str, Any] | None  # Nearest telemetry row
    telemetry_ts: int | None
    telemetry_delta_ms: int | None
    misaligned: bool  # True if delta > 250ms
```

## Quarantine Principle (docs/06)

**Never silently drop data.** All filtered windows are:

1. **Tracked**: Every filtered window appears in quarantine records
2. **Explained**: Each record includes a specific reason
   - `low_confidence`: One or more words below threshold
   - `excess_slack`: Gaps between words exceed 500ms budget
3. **Logged**: Written to JSONL with metadata for analysis
4. **Actionable**: Reasons include enough detail to investigate

Example quarantine record:
```json
{
  "reason": "low_confidence",
  "window_start_ms": 1000,
  "window_end_ms": 2000,
  "word_count": 3,
  "mean_conf": 0.52,
  "metadata": {
    "min_word_conf": 0.6,
    "failed_count": 1,
    "failed_words": ["course"]
  }
}
```

## Training Consumption

The downstream training loop consumes `aligned_pairs`:

```python
for pair in result["aligned_pairs"]:
    if pair.misaligned:
        continue  # Skip misaligned pairs

    window = pair.window
    telemetry = pair.telemetry

    # Training example:
    # Input: telemetry state
    # Output: narrated action (window.words)
    # Confidence: window.mean_conf (for weighted loss)
```

## Testing

Run tests with synthetic data (no audio, no Whisper):

```bash
python -m analyst.test_align
```

Tests verify:
- Per-word confidence gating
- Slack validation (500ms budget)
- Telemetry pairing with nearest-row logic
- Misalignment flag at >250ms delta
- Quarantine logging with reasons
- No silent drops (quarantine principle)

## Pluggable Backends

### Stage 1 Backends (Transcript)

| Backend | Type | Confidence | Notes |
|---------|------|------------|-------|
| whisper CLI | Native | No | Coarse timestamps only |
| whisper-timestamped | Extended | Yes | Per-word confidence |
| Whisper API (OpenAI) | Cloud | Yes | Per-word confidence |
| Custom | — | — | Implement `Stage1Backend` |

### Stage 2 Backends (Alignment)

| Backend | Method | Tolerance | Notes |
|---------|--------|-----------|-------|
| WhisperX | Forced alignment | 20-50ms | ICASSP 2023 validated |
| Cross-attention-DTW | Attention filtering | 20-50ms | Yeh 2025 |
| Custom | — | — | Implement `Stage2Backend` |

## Configuration

Default thresholds (configurable):

| Parameter | Default | Rationale |
|-----------|---------|-----------|
| `min_word_conf` | 0.6 | Balance quality vs quantity |
| `max_slack_ms` | 500 | Per HAL 2024 findings |
| `max_telemetry_delta_ms` | 250 | RQ-001 threshold |

## References

- **HAL 2024**: "Whisper native timestamps are very inaccurate"
- **WhisperX ICASSP 2023**: Forced alignment achieves 20-50ms tolerance
- **Yeh 2025**: Cross-attention filtering achieves 20-50ms tolerance
- **docs/25_RESEARCH_LANDSCAPE.md Stream 4**: Two-stage alignment for voice learning
- **docs/06**: Quarantine principle — never silent drops
- **RQ-001**: Telemetry alignment threshold (250ms)

## Files

- `analyst/align.py` — Core pipeline implementation
- `analyst/test_align.py` — Unit tests with synthetic data
- `analyst/README.md` — This file

## Design Principles

1. **Contract First**: Backends are pluggable via Protocol interfaces
2. **Stdlib Only**: Core uses only Python standard library
3. **Deterministic**: No wall-clock in logic; all timing is input-based
4. **Quarantine with Reasons**: Never silently drop data (docs/06)
5. **Research Grounded**: 500ms budget backed by literature (docs/25)
