# TzPro-Agent — Intelligence Expansion Brainstorm

**Date**: 2026-07-18
**Hardware**: Windows 11, no GPU, 16 GB RAM, Python 3.14
**Existing Stack**: OpenCV, SQLite, Docker, DeepInfra API (remote models)
**Goal**: Extend on-device and remote intelligence capabilities for the fishing-vessel sensor node

---

## 1. On-Device Vision — YOLO-nano via ONNX Runtime

### Concept
Run YOLOv8-nano (3.2M params, ~8.7 MB ONNX file) directly on CPU using ONNX Runtime rather
than PyTorch, targeting the 370×900 px sounder frames already captured every 30 seconds.
Train a small classifier on labeled sounder shots (blob / no-blob / school / thermocline /
bottom type) using the existing pixel-threshold data from `analyzer.py` as ground truth.

### Cost
- **Training**: One-time DeepInfra run (~$0.50 in inference credits for label generation
  on existing captures.db), then export to ONNX — free thereafter.
- **Runtime**: ~10-15 ms per 370×900 frame on CPU via ONNX (no GPU needed).
- **Memory**: ~20 MB resident after model load.

### Effort
- **Medium (2-3 days)**: Install `onnxruntime`, export YOLO-nano from Ultralytics,
  write a 50-line wrapper replacing/supplementing `vision.py` pixel-threshold logic.
  Labeling is the bottleneck — could seed from existing threshold passes.

### Value
- **High**: Instant blob classification at 30× the current frame rate.
  Discards empty frames before they hit DeepInfra, cutting API costs.
  Enables real-time "fish here" alerts during a drift without network round-trip.

### Risk
- **Low**: ONNX Runtime is mature, YOLO-nano ONNX export is well-documented.
  No new dependencies — `onnxruntime` is a pip install. False positives on
  plankton/thermoclines can be tuned with confidence threshold.

---

## 2. Voice Catch Reports — Whisper Tiny

### Concept
Add a hotkey-activated (or continuous, low-power) audio capture loop that feeds
5-15 second clips to Whisper-tiny via `faster-whisper` (CTranslate2 backend, ~75 MB
model). Transcribes Captain's verbal catch reports ("nice king, about 20 pounds,
110 feet on the downrigger") into structured JSON and inserts into captures.db.

### Cost
- **Zero runtime cost**: Whisper-tiny runs on CPU in ~2-5 seconds for a 10-second clip.
- **Storage**: ~50 KB per 10-second WAV; can flush after transcription.
- **Model download**: ~75 MB one-time.

### Effort
- **Medium (2-3 days)**: Add `faster-whisper` to requirements.txt, write a 100-line
  `voice_listener.py` using `sounddevice` or `pyaudio` for mic capture, a hotkey
  trigger (or VAD-based), and a JSON-structured prompt fed to DeepInfra for
  entity extraction (species, weight, depth, lure, location).

### Value
- **Very High**: Eliminates manual log entry. Captain already talks through the
  day — this captures that stream. Links catch events to sounder frames by
  timestamp, enabling supervised training data for the vision system.

### Risk
- **Medium**: Background engine noise, wind, and VHF chatter create transcription
  errors. Mitigation: hotkey-gated recording (Captain presses a key to record),
  plus a DeepInfra correction pass. Microphone must be positioned in wheelhouse.

---

## 3. Offline LLM — Phi-3-mini for Resilience

### Concept
When the vessel is out of cell range (common in Southeast Alaska), fall back to
Microsoft Phi-3-mini-4k-instruct (3.8B params, Q4_K_M quantized ~2.2 GB) via
`llama-cpp-python` for:
- Generating sounder-frame descriptions ("patch of bait at 18 fm, scattered marks").
- Answering Captain's text queries against the local knowledge base.
- Queuing requests for DeepInfra when connectivity returns.

### Cost
- **Zero runtime cost**: Pure CPU inference.
- **Model download**: ~2.2 GB — fits easily on disk.
- **Latency**: 3-8 seconds per short prompt on 16 GB CPU (no GPU).

### Effort
- **Medium (1-2 days)**: Already explored in `_arch_mini_local.md`.
  Install `llama-cpp-python`, download GGUF from HuggingFace, write a 60-line
  `offline_llm.py` fallback wrapper with the same interface as the DeepInfra client.

### Value
- **Medium**: Useful for the 40% of fishing time spent outside cell coverage.
  Provides basic intel when connectivity drops — but responses will be slower
  and less nuanced than DeepInfra.

### Risk
- **Medium**: 2.2 GB is a quarter of available RAM. Must unload model between
  requests or accept permanent footprint. Phi-3-mini quality on fishing-specific
  prompts is unproven. Mitigation: lazy-load, unload after 5 minutes idle.

---

## 4. Signal Fusion — Bayesian Network

### Concept
Build a lightweight Bayesian network (pgmpy or custom numpy) that combines evidence
from all available sources to produce a single probability distribution over
fishing-relevant states: {fish_present, species, depth_productive, tide_phase_active,
bite_window}.

Inputs:
- Sounder frame classification (blob/returns at depth bands)
- NMEA sentences from the existing bridge (GPS position, SOG, COG, depth)
- Proximity to known bathymetric contours (from `bathy_contours.py`)
- Fleet activity (from `fleet_monitor.py` — AIS density, proximity of other boats)
- Recent catch reports (timestamp-linked from voice or manual entry)

### Cost
- **Zero runtime cost**: Inference on a 5-8 node Bayesian network is microseconds.
- **Library**: `pgmpy` is a pip install.

### Effort
- **High (4-6 days)**: Requires designing the conditional probability tables (CPTs)
  from data or expert elicitation. The network structure is straightforward but
  CPTs need real calibration — could seed from Captain's historical logbooks
  and existing captures.db. Integration touches `analyzer.py`, `config.py`,
  `forward_look.py`, and `fleet_monitor.py`.

### Value
- **Very High**: This is the "brain" that makes the system an advisor, not a data
  logger. A single fused probability replaces the current siloed alerts.
  "87% chance salmon are stacked at 14-18 fm on the east side of the pinnacle"
  beats "blobs detected at depth 14-18."

### Risk
- **Medium-High**: Bad CPTs produce confidently wrong advice. Mitigation: start with
  Captain-validated priors, log every prediction vs. outcome, recalibrate weekly.
  Transparency is critical — always show the evidence that drove a prediction.

---

## 5. Temporal Mining — PCA Anomaly Detection

### Concept
Run Principal Component Analysis on the 22-metric time series already logged
(via `deltalog.py` and `analyzer.py`) to detect anomalous fishing conditions.
The 22 metrics include: return intensity quantiles (p10/p50/p90), blob count,
blob area, depth, COG, SOG, tide phase, bottom hardness, fleet density, etc.

Reconstruct each 30-second observation from its top-3 principal components.
Flag any frame where reconstruction error exceeds 2.5σ as anomalous — these are
candidate "something changed" events: a bait ball arriving, tide shift, boat
maneuver, or sounder malfunction.

### Cost
- **Zero runtime cost**: numpy/scikit-learn PCA on 22 columns is near-instant.
  Fit once daily on the last 12 hours of data (1,440 rows).
- **Storage**: Negligible — the PCA model is a 22×3 matrix.

### Effort
- **Low (1 day)**: sklearn is already available. Write `temporal_miner.py`:
  - Load last 12h from captures.db
  - Standardize, fit PCA(3), compute reconstruction error
  - Log anomalies to `anomaly_logger.py` (already exists)
  - Optionally surface top-3 contributing metrics per anomaly.

### Value
- **High**: Catches regime changes that single-threshold alerts miss.
  A 30-second frame might look normal in isolation but be anomalous in the
  context of the last hour. Surfaces "the fish just showed up" or "the current
  is shifting" without needing a rule for every scenario.

### Risk
- **Low**: PCA is well-understood and lightweight. False positives from
  tide changes (normal, predictable) can be suppressed by adding tide phase
  as a feature. Main risk is poor interpretability — "anomaly detected" without
  "because…" is useless. Always report contributing features.

---

## 6. Feedback Loop — Suggest, Act, Measure

### Concept
Close the loop: the system doesn't just report — it suggests actions ("turn
port 15° toward the 27 fm contour, there's a bait school on the edge"), then
measures the outcome (did the sounder improve? was a fish caught within
5 minutes?). Log suggestion + outcome pairs for reinforcement learning.

### Cost
- **Zero runtime cost**: All logic is in-process.
- **DeepInfra cost**: One extra API call per suggestion cycle (~$0.001).
  Capped at 1 suggestion per 5 minutes to avoid spamming.

### Effort
- **High (5-8 days)**: This is the hardest subsystem conceptually.
  Requires:
  1. A suggestion generator (DeepInfra prompt with current fused state).
  2. An outcome tracker (did conditions improve within N minutes?).
  3. A feedback store (suggestion → outcome pairs in captures.db).
  4. A "was this helpful?" prompt for the Captain (simple yes/no).
  5. Integration with the Bayesian network (#4) and voice (#2).

### Value
- **Transformative**: Elevates from "observer" to "first mate." Over months,
  the system learns which suggestions correlate with positive outcomes for
  this specific boat, captain, and fishing grounds.

### Risk
- **High**: Bad suggestions erode trust fast. Mitigations:
  - Start passive ("FYI: bait at 18 fm") before giving active advice.
  - Always cite evidence.
  - Log every suggestion for Captain review.
  - Never suggest anything that contradicts COLREGS or safety.
  - Captain veto is always absolute.

---

## 7. CPU Tricks — ONNX, SQLite WAL, OpenCV DNN, Joblib

### Concept
Every optimization that squeezes more intelligence out of a CPU-only 16 GB machine:

| Trick | What | Gain |
|-------|------|------|
| **ONNX Runtime** | Export models to ONNX; run with `onnxruntime` CPU EP. 2-5× faster than PyTorch CPU. | YOLO, classifier, any DL model |
| **SQLite WAL mode** | `PRAGMA journal_mode=WAL` — writers don't block readers. | Concurrent capture + query without locks |
| **OpenCV DNN** | OpenCV's built-in DNN module runs ONNX/OpenVINO models without extra deps. | Vision inference in the same process as capture |
| **Joblib caching** | `joblib.Memory` for expensive numpy ops (PCA fits, contour lookups). | Avoid recomputing on every 30s cycle |
| **NumPy vectorization** | Replace Python loops in `analyzer.py` with numpy broadcasting. | 10-50× on pixel ops |
| **mmap for captures.db** | SQLite memory-mapped I/O reduces syscalls on frequent reads. | Lower latency on historical queries |
| **Process isolation** | Run capture in a subprocess so a vision crash doesn't kill NMEA bridge. | Reliability |
| **LZ4 compression** | Compress sounder frames before TileDB storage. | 3-5× storage reduction, negligible CPU |

### Cost
- **Zero monetary cost**: All are library-level or configuration changes.
- **Engineering cost**: 1-2 days of targeted optimization.

### Effort
- **Low-Medium (1-2 days)**: Most are one-line changes or config flags.
  ONNX export for existing models requires a build step. SQLite WAL is literally
  one PRAGMA. Joblib caching is a decorator. Vectorization requires careful
  numpy rewriting of hot loops in `analyzer.py`.

### Value
- **High**: Frees 20-40% CPU headroom for the intelligence subsystems above.
  Makes the difference between "Phi-3-mini steals all RAM" and "everything fits."

### Risk
- **Low**: All techniques are battle-tested. SQLite WAL increases disk usage
  slightly (separate WAL file). ONNX export can have operator compatibility
  issues — test each model individually. Vectorization introduces subtle
  bugs if not tested against reference output.

---

## 8. Multi-Agent Consensus — Weighted Voting

### Concept
When connectivity is available, send the same sounder frame (or fused state
from #4) to 3-5 different models on DeepInfra simultaneously:
- DeepSeek-v3 (reasoning)
- Llama-4 (vision-language, if Florence-2 is used)
- Claude (structured analysis)
- A fine-tuned fishing classifier

Each agent returns a prediction (fish species, depth recommendation, action).
Vote by weighted average, where each agent's weight is its historical accuracy
on this boat's data. The system self-calibrates: agents that consistently
match Captain's ground-truth catch reports get higher weights.

### Cost
- **Moderate**: 3-5× current DeepInfra API cost per query. At current rates,
  ~$0.005-0.01 per consensus round. Capped at 1 round per 5 minutes = ~$3/day
  in heavy use.
- **Latency**: Slowest model determines round-trip. Worst case ~5 seconds.

### Effort
- **Medium (3-4 days)**: Build `consensus.py`:
  - Async dispatch to N model endpoints.
  - Collect, parse, and normalize responses to a common JSON schema.
  - Weighted average with confidence scores.
  - Update agent weights after Captain confirms/rejects a prediction.
  - Integrate with the feedback loop (#6).

### Value
- **Medium-High**: Ensemble methods consistently outperform single models.
  A Claude hallucination about a nonexistent pinnacle is voted down by
  DeepSeek's more conservative geospatial reasoning. Over time, the boat
  gets a "personalized ensemble" tuned to its specific waters.

### Risk
- **Medium**: API costs scale linearly with agents. Latency compounds.
  Conflicting predictions without clear resolution confuse the operator.
  Mitigations: always report confidence and disagreement along with the
  consensus. If stddev > threshold, flag "agents disagree — Captain must decide."
  Never hide the uncertainty behind a synthetic consensus.

---

## Priority Stack (Recommended Build Order)

| # | Item | Why First |
|---|------|-----------|
| 1 | **#7 CPU Tricks** | Frees headroom for everything else. Zero risk. |
| 2 | **#1 YOLO-nano ONNX** | Cuts DeepInfra costs immediately. Runs offline. |
| 3 | **#5 PCA Anomaly Mining** | 1 day build. Surfaces patterns now. |
| 4 | **#2 Whisper Tiny** | Unlocks voice-to-data pipeline. Captain requested. |
| 5 | **#4 Bayesian Fusion** | The "brain." Makes alerts coherent. |
| 6 | **#3 Phi-3-mini** | Offline resilience. Only needed when out of range. |
| 7 | **#8 Multi-Agent Consensus** | Nice-to-have when budget allows more API spend. |
| 8 | **#6 Feedback Loop** | Hardest. Build last, once trust is established. |

---

## Resource Budget (Running All 8 Simultaneously)

| Resource | Usage | Status |
|----------|-------|--------|
| **CPU** | ~40-60% on 16 GB laptop | Comfortable with #7 optimizations |
| **RAM** | ~6-8 GB (Phi-3: 2.2 GB, ONNX models: 0.2 GB, Python: 1 GB, OS: 3 GB) | Tight but works |
| **Disk** | ~100 MB new dependencies + model files | Negligible on modern disk |
| **DeepInfra** | $1-5/day at max consensus frequency | Acceptable |
| **Network** | <1 MB/day for API calls (no image uploads if #1 filters locally) | Trivial |

---

*This is a brainstorm for discussion with Captain. Nothing is committed.
Every item can be built, tested, and rolled back independently.*
