# _INTELLIGENCE_EXPANSION.md

## Smarter on Limited Hardware: 8 Ways to Level Up

**Date:** 2026-07-18  
**Hardware:** Windows 11, Intel iGPU (no CUDA/OpenCL), 16 GB RAM, LTE/Starlink  
**Current stack:** Python 3.14, OpenCV, SQLite (22K blobs), DeepInfra API, ~500 blobs/10-min capture

Below, 8 concrete ideas. Each rated on a 1–5 scale: hardware cost, effort, value, risk.
**"Hardware cost"** = extra RAM/disk/CPU cost, not $$$. 1 = negligible, 5 = needs new hardware.
**"Effort"** = implementation weeks. 1 = one afternoon, 5 = months of R&D.
**"Value"** = impact on system intelligence. 1 = nice-to-have, 5 = game-changer.
**"Risk"** = chance of failure/regression. 1 = practically zero, 5 = high likelihood of wasting time.

---

## 1. On-Device Vision Models for Blob Classification

### Concept

Run a tiny CNN classifier on CPU via ONNX Runtime that classifies individual sonar blobs at inference time. Every capture produces ~500 blobs. Right now they're raw shapes (area, intensity, aspect ratio, centroid depth). We manually label some via catch reports (post-hoc Bayesian matching). What if the system could say "this blob looks chum-like" at analysis time?

A simple approach: export ONNX models from PyTorch. Even a 4-layer CNN on a 32×32 blob thumbnail (grayscale) takes < 1 ms per blob on CPU. At 500 blobs/capture, that's ~500 ms inference, well within the 10-min cadence.

### Concrete Implementation

```
pip install onnxruntime  # CPU-only wheel, ~15 MB
pip install torch torchvision  # for training only (or use on another machine)
```

**Model:** MobileNetV3-Small 0.75× or a custom tiny CNN (4 conv layers, ~200K params).

```python
import onnxruntime as ort
import numpy as np

# One-time: export from PyTorch on a GPU machine
# torch.onnx.export(model, dummy_input, "blob_classifier.onnx")

class BlobClassifier:
    """ONNX blob classifier — runs on Intel CPU, ~200K params, ~1ms/blob."""
    
    def __init__(self, onnx_path="blob_classifier.onnx"):
        self.session = ort.InferenceSession(
            onnx_path,
            providers=['CPUExecutionProvider'],
            sess_options=self._make_options(),
        )
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name
        self.classes = ["noise", "chum", "pollock", "rockfish", "halibut", "bait_ball"]
    
    def _make_options(self):
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 4        # leave cores for other stuff
        opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        return opts
    
    def classify_blob(self, blob_patch: np.ndarray) -> tuple[str, float]:
        """blob_patch: (H, W) grayscale, will be resized to 32×32."""
        from PIL import Image
        
        img = Image.fromarray(blob_patch).resize((32, 32))
        arr = np.array(img, dtype=np.float32) / 255.0
        arr = arr.reshape(1, 1, 32, 32)  # (N, C, H, W)
        
        logits = self.session.run([self.output_name], {self.input_name: arr})[0]
        probs = self._softmax(logits[0])
        idx = int(np.argmax(probs))
        return self.classes[idx], float(probs[idx])
    
    def classify_batch(self, blob_patches: list[np.ndarray]) -> list[tuple[str, float]]:
        """Batch classify multiple blobs."""
        from PIL import Image
        batch = np.zeros((len(blob_patches), 1, 32, 32), dtype=np.float32)
        for i, patch in enumerate(blob_patches):
            img = Image.fromarray(patch).resize((32, 32))
            batch[i, 0] = np.array(img, dtype=np.float32) / 255.0
        
        logits = self.session.run([self.output_name], {self.input_name: batch})[0]
        results = []
        for i in range(len(blob_patches)):
            probs = self._softmax(logits[i])
            idx = int(np.argmax(probs))
            results.append((self.classes[idx], float(probs[idx])))
        return results

    @staticmethod
    def _softmax(x):
        e_x = np.exp(x - np.max(x))
        return e_x / e_x.sum()
```

**Training data bootstrap:** Extract blob patches from existing captures, assign initial labels from the vocabulary system (catches that have been matched to capture windows). Even 200 labeled patches per class is enough to start.

**Integration:** Call `classifier.classify_batch(blob_patches)` during `analyzer.py`'s blob extraction loop. Append `predicted_species` and `prediction_confidence` to each blob dict (the blob table already has those columns). No pipeline change needed.

### OpenCV DNN Alternative (Zero New Dependencies)

If ONNX Runtime is too heavy, OpenCV's built-in DNN module reads ONNX directly:

```python
net = cv2.dnn.readNetFromONNX("blob_classifier.onnx")
net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
# OpenCV's DNN automatically uses Intel's Inference Engine if available
blob = cv2.dnn.blobFromImage(patch, 1/255.0, (32,32), swapRB=False)
net.setInput(blob)
outputs = net.forward()
```

This avoids the `onnxruntime` pip dependency entirely, though it's slightly slower (~2–3ms/blob instead of ~1ms).

### Assessment

| Metric | Score | Notes |
|--------|-------|-------|
| Hardware cost | 1 | CPU-only, ~20 MB RAM for model + runtime |
| Effort | 2 | Train on another machine, export ONNX, 1 week integration |
| Value | 4 | Real-time species classification for every blob; feeds vocabulary |
| Risk | 2 | Low accuracy with small training sets; will improve with more catches |

**Best path:** Start with OpenCV DNN (zero new deps). If it works well, optimize with ONNX Runtime later. Training data comes from linking catch reports to their capture windows — a feedback loop already being built.

---

## 2. Voice Catch Reports via Whisper

### Concept

The Captain is on a boat. Typing catch reports on a phone or laptop is slow. Voice is faster. `whisper-tiny.en` (39 MB, ONNX) runs on CPU in < 1 second per short utterance.

"Chum at 35 on the green flasher" → auto-filled catch report form → `catch_labels` table. Completely local inference — works 30 miles offshore with zero connectivity.

### Concrete Implementation

```
pip install faster-whisper          # CTranslate2 backend, ~2× faster than OpenAI Whisper
# OR
pip install openai-whisper          # Original implementation
```

**Model:** `whisper-tiny.en` — 39 MB download, ~500 MB RAM during inference, ~0.5s for a 5-second clip.

```python
from faster_whisper import WhisperModel

class VoiceCatchReporter:
    """
    Continuous listening for catch report voice commands.
    Uses a wake-word approach: "Hey boat" or "cockpit report" triggers recording.
    """

    def __init__(self):
        # tiny.en: English only, 39MB, fastest
        self.model = WhisperModel("tiny.en", device="cpu", compute_type="int8")
        self.keywords = {
            "species": ["chum", "coho", "chinook", "king", "halibut", "pollock", "rockfish",
                        "sockeye", "pink", "lingcod", "yelloweye", "black cod", "sablefish"],
            "numbers": re.compile(r"(\d+)\s*(?:fm|fathom|feet|ft|on the)"),
            "gear": ["flasher", "spoon", "hoochie", "herring", "plug", "jig", "hali", "troll",
                     "divers", "spreader", "gurdie"],
        }

    def transcribe(self, audio_path: str) -> str:
        segments, info = self.model.transcribe(
            audio_path,
            beam_size=5,
            language="en",
            vad_filter=True,  # filter silence
        )
        text = " ".join(s.text for s in segments)
        return text

    def parse_report(self, transcript: str) -> dict:
        """Parse spoken catch report into structured form."""
        result = {"species": None, "depth_fm": None, "count": 1, "gear": None, "notes": []}

        text = transcript.lower()

        # Species
        for sp in self.keywords["species"]:
            if sp in text:
                result["species"] = sp
                break

        # Depth: "at 35 fm", "at thirty five fathoms", "at 20 on the wire"
        depth_match = self.keywords["numbers"].search(text)
        if depth_match:
            result["depth_fm"] = int(depth_match.group(1))

        # Gear
        for gear in self.keywords["gear"]:
            if gear in text:
                result["gear"] = gear
                break

        result["notes"] = [text]  # keep raw for later refinement
        return result
```

**Integration approach:**

- **Option A (simplest):** Add a `voice_catch.py` script. Captain records a .wav on his phone, drops it in a watched folder, the watcher transcribes and inserts into `catch_labels`.
- **Option B (continuous):** `pyaudio` loop that listens for wake words. Slightly more effort, more immersive.
- **Option C (Telegram voice note):** Already possible. Telegram bot receives voice notes, downloads .ogg, converts with ffmpeg, transcribes. This is the lowest-friction path — the Captain already uses Telegram for alerts.

**Telegram voice note path:**

```python
# In the Telegram bot handler:
async def handle_voice(message):
    file = await bot.get_file(message.voice.file_id)
    ogg_path = f"/tmp/{message.voice.file_id}.ogg"
    wav_path = f"/tmp/{message.voice.file_id}.wav"
    await file.download_to_drive(ogg_path)

    # Convert OGG to WAV (ffmpeg must be installed)
    import subprocess
    subprocess.run(["ffmpeg", "-i", ogg_path, "-ar", "16000", "-ac", "1", wav_path, "-y"])

    # Transcribe
    reporter = VoiceCatchReporter()
    text = reporter.transcribe(wav_path)
    report = reporter.parse_report(text)

    # Confirm back to Captain
    if report["species"]:
        await message.reply(f"Got it: {report['species']} at {report['depth_fm']}fm — logging.")
        insert_catch_label(report)
    else:
        await message.reply(f"Heard: '{text}' — couldn't parse species. Try again?")
```

### Assessment

| Metric | Score | Notes |
|--------|-------|-------|
| Hardware cost | 2 | ~500 MB RAM during inference, releases after; 39 MB disk |
| Effort | 2 | Telegram voice note integration is ~1 day; continuous mode ~3 days |
| Value | 5 | Removes the biggest friction to catch labeling — typing on a boat |
| Risk | 2 | Accuracy on noisy pilothouse audio; need to test in real conditions |

**Best path:** Telegram voice notes first (Option C). Zero new hardware. Captain already uses Telegram. If it works well, graduate to continuous listening later.

---

## 3. Offline Tiny LLM

### Concept

When Starlink drops and DeepInfra is unreachable, the system can still generate intelligent descriptions from recent data. A small local LLM (Phi-3-mini or Llama-3.2-1B) runs entirely on CPU, using ~2 GB RAM.

This isn't meant to replace DeepInfra — it's a **fallback** that keeps the monologue flowing. The local model's output is simpler ("3 blobs in mid-zone, bottom at 57 fm, no thermoclines") vs. the cloud model's richer narrative. But better than silence.

### Concrete Implementation

```
pip install llama-cpp-python  # GGUF inference, CPU-optimized
```

**Models to try (from smallest to largest):**

| Model | File size | RAM | Speed (CPU) | Quality |
|-------|-----------|-----|-------------|---------|
| `SmolLM2-135M-Instruct` Q4 | ~90 MB | ~200 MB | ~200 tok/s | Basic facts |
| `Qwen2.5-0.5B-Instruct` Q4 | ~350 MB | ~500 MB | ~80 tok/s | Decent summaries |
| `Llama-3.2-1B-Instruct` Q4 | ~700 MB | ~1 GB | ~40 tok/s | Good descriptions |
| `Phi-3-mini-4k-instruct` Q4 | ~2 GB | ~2.5 GB | ~15 tok/s | Very coherent |

```python
from llama_cpp import Llama

class OfflineLLM:
    """Local LLM fallback when DeepInfra is unreachable."""

    def __init__(self, model_path="Llama-3.2-1B-Instruct-Q4_K_M.gguf"):
        self.llm = Llama(
            model_path=model_path,
            n_ctx=2048,
            n_threads=6,           # leave 2 for other processes
            n_batch=256,
            verbose=False,
        )
        self._warmed = False

    def _warm(self):
        """Prime the model with a dummy prompt to load into RAM."""
        if not self._warmed:
            self.llm("ping", max_tokens=1)
            self._warmed = True

    def generate_description(self, capture_data: dict) -> str:
        """Generate a natural-language description from recent sounder data."""
        self._warm()

        # Build a compact prompt from structured data
        blobs = capture_data.get("blobs", [])
        blob_summary = self._summarize_blobs(blobs)
        bottom = capture_data.get("bottom_depth_fm", "?")
        thermo = capture_data.get("thermocline_count", 0)
        pos = capture_data.get("position", {})
        sog = pos.get("sog_kts", "?")
        cog = pos.get("cog_deg", "?")

        prompt = f"""<|user|>
You are a fishing vessel's sonar interpreter. Describe this capture in 2-3 sentences.

Data:
- Bottom depth: {bottom} fathoms
- Thermoclines: {thermo}
- Blob summary: {blob_summary}
- Speed: {sog} knots, Course: {cog}°

Keep it terse. Pilot house tone.
<|assistant|>"""

        response = self.llm(
            prompt,
            max_tokens=100,
            temperature=0.3,
            stop=["<|user|>", "\n\n"],
        )
        return response["choices"][0]["text"].strip()

    def _summarize_blobs(self, blobs: list) -> str:
        """Compress blob list into a compact summary string."""
        if not blobs:
            return "no fish returns detected"

        depths = [b.get("centroid_depth_fm") for b in blobs if b.get("centroid_depth_fm")]
        if not depths:
            return f"{len(blobs)} returns"

        min_d, max_d = min(depths), max(depths)
        mid_zone = sum(1 for d in depths if 20 <= d <= 40)
        return (f"{len(blobs)} returns, {mid_zone} in mid-zone, "
                f"depth range {min_d:.0f}-{max_d:.0f} fm")
```

**Switch logic (in agent.py or monologue.py):**

```python
def get_llm():
    """Return the best available LLM client."""
    if deepinfra_available():  # ping DeepInfra, < 2s timeout
        return DeepInfraClient()
    elif offline_llm:
        log.warning("DeepInfra unreachable — using local LLM")
        return offline_llm
    else:
        # Fallback to template-based descriptions
        return TemplateDescriber()
```

### Assessment

| Metric | Score | Notes |
|--------|-------|-------|
| Hardware cost | 3 | 1–2.5 GB RAM permanently consumed if model stays loaded |
| Effort | 3 | llama-cpp-python setup, model download, prompt engineering |
| Value | 4 | Keeps intelligence running offshore; offline resience is critical |
| Risk | 3 | Q4-quantized small models may produce gibberish on domain-specific data |

**Best path:** Start with `Llama-3.2-1B-Instruct` Q4 (700 MB, runs on 6 threads with 1 GB RAM). If too slow, `Qwen2.5-0.5B` is the sweet spot between speed and coherence for simple descriptions. Don't even try Phi-3-mini on CPU — 15 tok/s is unusably slow for interactive use.

**Important:** Load the model lazily and unload it when DeepInfra is available. Use `del llm; gc.collect()` to free RAM. Don't keep both loaded simultaneously.

---

## 4. Signal Fusion — Multi-Sensor Probabilistic Model

### Concept

The system already collects multiple independent sensor streams. Right now they're analyzed separately:

| Signal | Source | What it captures |
|--------|--------|-----------------|
| Sounder pixels | 370×900 RGB crop | Blob count, intensities, depth distribution, bottom type |
| NMEA | hermitd :8654 | Lat, lon, SOG, COG (position, speed, heading) |
| Boat proximity | Vertical lines in HF band | Other vessels nearby (creates white vertical streaks) |
| Feed haze | Texture analysis | Dispensed bait cloud in water column |
| Catch reports | Captain via Telegram or voice | Species, depth, gear (ground truth labels) |
| Chart alerts | agent_loop.py | Gear contour crossings, anchor hazards, complex bottom |

These are analyzed independently. But they're all observing the same physical reality. A chum school at 35 fm should show up as:
1. **Pixels:** mid-zone blob cluster with chum-like intensity/size signature
2. **NMEA:** boat is on or near a known chum contour
3. **Boat proximity:** nearby boats also circling this spot (fleet pressure)
4. **Catch reports:** recent chum catches from this zone and depth
5. **Feed haze:** if bait is being dispensed, haze texture increases

### Bayesian Fusion Approach

Instead of "pixels say X, NMEA says Y, catch says Z", fuse them into one probabilistic distribution:

```
P(species | all_signals) ∝ P(pixels | species) × P(NMEA | species) × P(fleet | species) × P(catches | species)
```

```python
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

@dataclass
class SensorEvidence:
    """One sensor's belief about what species is present."""
    name: str
    species_probs: Dict[str, float]  # {species: P(this sensor data | species)}
    weight: float = 1.0  # per-sensor reliability weight
    timestamp: float = field(default_factory=lambda: time.time())


class SignalFusion:
    """
    Bayesian fusion of multiple independent sensor streams.

    Each sensor produces a likelihood vector P(sensor_data | species).
    We multiply them (naive Bayes assumption) then normalize.
    Sensor weights (0-1) allow de-weighting unreliable sensors.
    """

    def __init__(self, species_list: List[str]):
        self.species = species_list
        self.n_species = len(species_list)
        self.species_index = {s: i for i, s in enumerate(species_list)}

    def fuse(self, evidence_list: List[SensorEvidence]) -> Dict[str, float]:
        """
        Combine multiple sensor likelihoods into one posterior.

        Returns {species: probability} dict.
        """
        if not evidence_list:
            return {s: 1.0/self.n_species for s in self.species}

        # Start with uniform prior
        log_probs = np.zeros(self.n_species)

        for ev in evidence_list:
            for species, prob in ev.species_probs.items():
                idx = self.species_index.get(species)
                if idx is not None and prob > 0:
                    log_probs[idx] += ev.weight * np.log(prob + 1e-10)

        # Normalize
        probs = np.exp(log_probs - np.max(log_probs))
        probs /= probs.sum()

        return {s: float(probs[i]) for i, s in enumerate(self.species)}

    def confidence(self, fused: Dict[str, float]) -> float:
        """
        How confident is the fused prediction?
        Measures entropy — high entropy = low confidence.
        """
        probs = np.array(list(fused.values()))
        entropy = -np.sum(probs * np.log(probs + 1e-10))
        max_entropy = np.log(len(probs))
        return 1.0 - (entropy / max_entropy)  # 0=total uncertainty, 1=certain
```

**Likelihood functions for each sensor:**

```python
def pixels_to_species_likelihood(blobs: list, classifier: BlobClassifier) -> SensorEvidence:
    """Aggregate blob-level classification into per-capture species likelihoods."""
    species_counts = {}
    for blob in blobs:
        species, conf = classifier.classify_blob(blob["patch"])
        species_counts[species] = species_counts.get(species, 0) + conf

    total = sum(species_counts.values()) or 1
    probs = {s: c / total for s, c in species_counts.items()}
    return SensorEvidence(name="pixels", species_probs=probs, weight=1.0)


def nmea_to_species_likelihood(lat: float, lon: float, depth_fm: float,
                                 hot_spot_db) -> SensorEvidence:
    """Look up position/depth in known species hotspot database."""
    # Query: "at this position and depth, what species are historically caught?"
    # Returns likelihoods based on past catches in similar areas
    matches = hot_spot_db.query(lat, lon, depth_fm, radius_nm=2)
    if not matches:
        return SensorEvidence(name="nmea", species_probs={}, weight=0.3)

    total = sum(m["count"] for m in matches) or 1
    probs = {m["species"]: m["count"] / total for m in matches}
    return SensorEvidence(name="nmea", species_probs=probs, weight=0.6)


def fleet_pressure_to_likelihood(boat_proximity_score: float,
                                  past_fleet_zones) -> SensorEvidence:
    """More boats nearby → higher likelihood of fish (any species).
    Also: specific zones where fleet clusters → species associated with that zone."""
    # Simplistic version: boat proximity just raises overall fish probability
    if boat_proximity_score < 0.3:
        return SensorEvidence(name="fleet", species_probs={}, weight=0.1)

    # Check if current position is in a known fleet aggregation zone
    zone = past_fleet_zones.match(lat, lon)
    if zone:
        return SensorEvidence(
            name="fleet",
            species_probs={zone["common_species"]: 0.7},
            weight=boat_proximity_score * 0.5,
        )
    return SensorEvidence(
        name="fleet",
        species_probs={"fish_present": 0.6},
        weight=boat_proximity_score * 0.3,
    )


def catch_history_to_likelihood(capture_ts: str, species_db: sqlite3.Connection) -> SensorEvidence:
    """Recent catch history in this area biases species prediction."""
    # Query: catches within last 2 hours, within 2nm
    cur = species_db.execute("""
        SELECT species, COUNT(*) as cnt FROM catch_events
        WHERE ts_utc >= datetime(?, '-2 hours')
        GROUP BY species ORDER BY cnt DESC
    """, (capture_ts,))
    rows = cur.fetchall()
    if not rows:
        return SensorEvidence(name="catches", species_probs={}, weight=0.4)

    total = sum(r[1] for r in rows) or 1
    probs = {r[0]: r[1] / total for r in rows}
    return SensorEvidence(name="catches", species_probs=probs, weight=0.8)
```

**Integration into the analysis loop:**

```python
# In analyzer.py after blob extraction:
fuser = SignalFusion(["chum", "coho", "chinook", "pollock", "rockfish", "noise"])

evidence = [
    pixels_to_species_likelihood(blobs, classifier),
    nmea_to_species_likelihood(lat, lon, depth, hot_spot_db),
    fleet_pressure_to_likelihood(boat_prox, fleet_zones),
    catch_history_to_likelihood(ts, catch_db),
]

fused = fuser.fuse(evidence)
conf = fuser.confidence(fused)

log.info("Fusion: %s (confidence: %.2f)", fused, conf)

if conf > 0.7 and max(fused.values()) > 0.5:
    top_species = max(fused, key=fused.get)
    capture_data["fusion"] = {
        "prediction": top_species,
        "confidence": conf,
        "species_probs": fused,
    }
```

### Assessment

| Metric | Score | Notes |
|--------|-------|-------|
| Hardware cost | 1 | Pure math; < 1 KB extra RAM; no GPU needed |
| Effort | 3 | Build likelihood functions, tune weights, 2–3 weeks |
| Value | 5 | **This is the killer feature.** Multi-signal fusion gives higher confidence than any single sensor |
| Risk | 2 | Naive Bayes assumes independence (violated in reality); Kalman filter would be more correct but harder |

**Best path:** Build the multi-signal fusion alongside the other improvements. Each new sensor (ONNX classifier, catch history, fleet) feeds into the fuser. The fuser gets smarter as each sensor improves.

---

## 5. Temporal Pattern Mining

### Concept

With 30+ captures/day and 22K+ blobs, the system has a multivariate time series spanning weeks. Patterns are hiding in the data — we just need to surface them.

### 5a. Diel Migration Correlation

Basic hypothesis: fish move vertically with daylight. Test it.

```python
import numpy as np
from datetime import datetime

def diel_analysis(captures: list[dict]) -> dict:
    """
    Simple analysis: does blob depth correlate with time of day?
    Returns Pearson r and p-value for each depth zone.
    """
    times = []
    mid_zone_counts = []
    surface_counts = []

    for cap in captures:
        ts = datetime.fromisoformat(cap["ts_utc"])
        hour = ts.hour + ts.minute / 60.0
        times.append(hour)

        blobs = cap.get("blobs", [])
        mid = sum(1 for b in blobs if 20 <= (b.get("centroid_depth_fm") or 0) <= 40)
        surf = sum(1 for b in blobs if (b.get("centroid_depth_fm") or 0) < 10)
        mid_zone_counts.append(mid)
        surface_counts.append(surf)

    from scipy.stats import pearsonr
    r_mid, p_mid = pearsonr(times, mid_zone_counts)
    r_surf, p_surf = pearsonr(times, surface_counts)

    return {
        "mid_zone_diel_r": r_mid,
        "mid_zone_diel_p": p_mid,
        "surface_diel_r": r_surf,
        "surface_diel_p": p_surf,
        "n_samples": len(captures),
    }
```

### 5b. Tidal Phase Correlation

Alaska tides are extreme (15+ ft range). Fish behavior likely changes with tide.

```python
import requests

def get_tidal_phase(lat: float, lon: float, ts: datetime) -> dict:
    """
    Fetch tidal prediction for nearby station.
    NOAA CO-OPS API: free, no key needed.
    """
    station_id = find_nearest_tide_station(lat, lon)  # pre-computed lookup
    url = (f"https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
           f"?station={station_id}&product=predictions"
           f"&datum=MLLW&time_zone=lst_ldt&units=english"
           f"&format=json&interval=hilo"
           f"&begin_date={ts.strftime('%Y%m%d')}&end_date={ts.strftime('%Y%m%d')}")
    # Parse and compute: is tide rising? falling? slack? what's the current height?
```

### 5c. Boat Proximity → Blob Count Lag Effect

The competition theory: nearby boats scare fish away, but with a lag. The fish come back.

```python
def boat_proximity_lag(captures: list[dict], lag_minutes: int = 20) -> dict:
    """
    For each capture, look at the boat_proximity_score.
    Then check blob_count 20 minutes later.
    Compute correlation.
    """
    prox = []
    blob_lagged = []

    for i, cap in enumerate(captures):
        ts = datetime.fromisoformat(cap["ts_utc"])
        prox_score = cap.get("boat_proximity_score", 0)
        prox.append(prox_score)

        # Find capture closest to ts + lag_minutes
        target_ts = ts + timedelta(minutes=lag_minutes)
        best = None
        for future_cap in captures[i:]:
            future_ts = datetime.fromisoformat(future_cap["ts_utc"])
            diff = abs((future_ts - target_ts).total_seconds())
            if diff < 300:  # within 5 min of target
                best = future_cap.get("blob_count", 0)
                break
        blob_lagged.append(best or 0)

    from scipy.stats import pearsonr
    r, p = pearsonr(prox, blob_lagged)
    return {"lag_minutes": lag_minutes, "r": r, "p": p}
```

### 5d. Online Anomaly Detection

Instead of batch analysis, maintain a rolling baseline and flag unusual captures.

```python
from collections import deque

class RollingBaseline:
    """
    Maintains a rolling window of N captures.
    Each new capture is scored against the baseline using simple PCA.
    High residual = unusual = investigate.
    """

    def __init__(self, window_size: int = 100):
        self.window = deque(maxlen=window_size)
        self.feature_names = [
            "blob_count", "mid_zone_mean", "bottom_depth_fm",
            "thermocline_count", "sog_kts", "water_column_mean",
            "fish_arch_rate", "temporal_variance",
        ]

    def add(self, capture: dict):
        features = self._extract_features(capture)
        self.window.append(features)

    def score(self, capture: dict) -> float:
        """
        Score a capture against the rolling baseline.
        Returns anomaly score (0 = normal, higher = weirder).
        """
        if len(self.window) < 20:
            return 0.0  # not enough data

        features = np.array(self._extract_features(capture))

        # Simple approach: Mahalanobis distance from baseline mean
        baseline = np.array(list(self.window))
        mean = baseline.mean(axis=0)
        cov = np.cov(baseline.T)
        cov_inv = np.linalg.pinv(cov)

        diff = features - mean
        mahalanobis = np.sqrt(diff @ cov_inv @ diff)

        # Normalize to 0-1-ish
        return min(1.0, mahalanobis / 10.0)

    def _extract_features(self, capture: dict) -> list:
        return [
            capture.get("blob_count", 0),
            capture.get("mid_zone_mean", 0) or 0,
            capture.get("bottom_depth_fm", 0) or 0,
            capture.get("thermocline_count", 0),
            capture.get("sog_kts", 0) or 0,
            capture.get("water_column_mean", 0),
            capture.get("fish_arch_rate", 0),
            capture.get("temporal_variance", 0),
        ]
```

**Dashboard integration:** When anomaly score > 0.7, flag the capture in the agent loop. Generate an alert: "Unusual capture detected (score 0.85) — mid-zone density way above baseline."

### Assessment

| Metric | Score | Notes |
|--------|-------|-------|
| Hardware cost | 1 | Pure NumPy math, < 1 MB for rolling window |
| Effort | 3 | Build feature extraction, run on historical data, iterate on features |
| Value | 5 | Discover patterns the Captain might miss; anomaly detection is high-value |
| Risk | 1 | Low risk; even false positives are interesting; easy to tune thresholds |

**Best path:** Start with the anomaly detector (5d) — it's the easiest to build and immediately useful. Add diel/tidal correlation as curiosity-driven research. The competition theory (5c) is fun but lower priority until the other systems are solid.

---

## 6. Feedback Loops

### Concept

Currently: system observes → describes → Captain reads → Captain acts → effects happen. There's no loop back. The system doesn't know if its predictions were right.

Closing the loop means:

1. **System suggests** something (e.g., "boats approaching from east, recommend 20° port" or "high chum probability at 35 fm based on blob signature")
2. **Measure** whether the Captain took that advice (did he turn 20° port? did he set gear at 35 fm?)
3. **Record** the outcome (did the suggestion lead to fish?)
4. **Learn** — adjust future suggestions based on what worked

### Lightweight Implementation

Don't build a full RL system. Build a **suggestion log** with simple outcome tracking.

```python
@dataclass
class Suggestion:
    id: str
    ts_utc: str
    type: str              # "course_change", "depth_recommendation", "gear_alert"
    message: str           # what was suggested
    params: dict           # {target_heading: 220, reason: "fleet_approach"}
    position: dict         # {lat, lon} where suggested
    outcome: Optional[str] = None      # "accepted", "rejected", "partial", "unknown"
    result: Optional[str] = None       # "fish_caught", "avoided_hazard", "no_effect"
    feedback_ts: Optional[str] = None
    feedback_source: Optional[str] = None  # "nmea_track", "catch_report", "captain_ack"
```

**Measuring acceptance:**

```python
def check_suggestion_outcome(suggestion: Suggestion,
                              recent_positions: list[dict]) -> str:
    """
    Did the Captain act on a suggestion?

    For course_change: check if vessel heading changed toward suggested heading
                       within 2 minutes of suggestion.
    For depth_recommendation: check if vessel moved toward recommended contour.
    For gear_alert: check if SOG dropped below 2 kts (setting gear) near suggested depth.
    """
    if suggestion.type == "course_change":
        target = suggestion.params.get("target_heading")
        # Get heading 2 minutes after suggestion
        post_positions = filter_positions_after(recent_positions, suggestion.ts_utc, window_s=120)
        actual_cog = post_positions[0]["cog"] if post_positions else None

        if actual_cog and abs(actual_cog - target) < 15:
            return "accepted"
        return "rejected"

    if suggestion.type == "depth_recommendation":
        target_depth = suggestion.params.get("target_depth_fm")
        post = filter_positions_after(recent_positions, suggestion.ts_utc, window_s=300)
        actual_depth = get_depth_fm(post[-1]["lat"], post[-1]["lon"]) if post else None

        if actual_depth and abs(actual_depth - target_depth) < 5:
            return "accepted"
        return "rejected"

    return "unknown"
```

**Learning from outcomes:**

```python
class SuggestionLearner:
    """
    Tracks which suggestions are accepted and which lead to fish.
    Simple counting approach: accepted rate per suggestion type.
    """

    def __init__(self):
        self.db = sqlite3.connect("suggestions.db")
        self._init_db()

    def record(self, suggestion: Suggestion):
        self.db.execute("""
            INSERT INTO suggestions (id, ts, type, message, outcome, result)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (suggestion.id, suggestion.ts_utc, suggestion.type,
              suggestion.message, suggestion.outcome, suggestion.result))

    def get_acceptance_rate(self, suggestion_type: str) -> float:
        cur = self.db.execute("""
            SELECT outcome, COUNT(*) FROM suggestions
            WHERE type = ? AND outcome IS NOT NULL
            GROUP BY outcome
        """, (suggestion_type,))
        counts = dict(cur.fetchall())
        accepted = counts.get("accepted", 0)
        total = sum(counts.values())
        return accepted / total if total > 0 else 0.0

    def get_effective_rate(self, suggestion_type: str) -> float:
        """Of accepted suggestions, how many led to fish?"""
        cur = self.db.execute("""
            SELECT result, COUNT(*) FROM suggestions
            WHERE type = ? AND outcome = 'accepted' AND result IS NOT NULL
            GROUP BY result
        """, (suggestion_type,))
        counts = dict(cur.fetchall())
        fish = counts.get("fish_caught", 0)
        total = sum(counts.values())
        return fish / total if total > 0 else 0.0

    def should_suggest(self, suggestion_type: str) -> bool:
        """
        Only suggest if historical acceptance AND effectiveness are decent.
        Don't annoy the Captain with low-value suggestions.
        """
        acceptance = self.get_acceptance_rate(suggestion_type)
        effectiveness = self.get_effective_rate(suggestion_type)

        if acceptance < 0.3:
            return False  # Captain ignores these, stop suggesting
        if effectiveness < 0.2:
            return False  # Even when accepted, rarely produces fish

        return True

    def _init_db(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS suggestions (
                id TEXT PRIMARY KEY,
                ts TEXT,
                type TEXT,
                message TEXT,
                outcome TEXT,
                result TEXT,
                params_json TEXT,
                position_json TEXT
            )
        """)
```

### Assessment

| Metric | Score | Notes |
|--------|-------|-------|
| Hardware cost | 1 | SQLite table + < 1 KB per suggestion |
| Effort | 4 | Building outcome measurement, integrating with NMEA track, A/B testing suggestions |
| Value | 4 | **Nirvana state**: system that gets smarter every trip. But hard to measure acceptance reliably |
| Risk | 4 | High: misreading Captain's intent (he turned for a different reason), annoying with bad suggestions |

**Best path:** Start very conservatively. Only suggest things with high confidence (> 0.85). Log outcomes silently (no nagging). After 50+ suggestions, check the numbers. If acceptance is < 30%, the system isn't ready to suggest — go back to passive observation.

---

## 7. CPU Acceleration Tricks

### Concept

No GPU, but Intel CPUs have hidden acceleration capabilities that most Python code doesn't use. A few targeted optimizations can 2–5× existing analysis speed.

### 7a. ONNX Runtime CPU Backend

Already covered under #1, but applies more broadly. Any small neural model (blob classifier, depth scale OCR correction, haze detector) should run through ONNX Runtime with the CPU execution provider.

```python
# ONNX Runtime session optimization
opts = ort.SessionOptions()
opts.intra_op_num_threads = 6       # leave 2 cores free
opts.inter_op_num_threads = 2
opts.execution_mode = ort.ExecutionMode.ORT_PARALLEL
opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
opts.enable_mem_pattern = True
opts.enable_cpu_mem_arena = True
```

### 7b. OpenCV DNN with Intel Inference Engine

OpenCV's `cv2.dnn` module can use Intel's Inference Engine backend if OpenVINO is installed. Even without a GPU, this provides optimized CPU inference.

```bash
pip install openvino  # adds Intel DNN acceleration
```

```python
net = cv2.dnn.readNetFromONNX("model.onnx")
net.setPreferableBackend(cv2.dnn.DNN_BACKEND_INFERENCE_ENGINE)
net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
# Inference Engine will auto-detect SSE4.2, AVX2, AVX-512 etc.
```

### 7c. NumPy Vectorization

The current analyzer.py uses OpenCV's pixel operations, which are already fast. But any custom NumPy should avoid Python loops:

```python
# BAD: Python loop over pixels
for i in range(len(blobs)):
    blobs[i]["intensity_ratio"] = blobs[i]["hf_intensity"] / blobs[i]["lf_intensity"]

# GOOD: Vectorized
arr = np.array([(b["hf_intensity"], b["lf_intensity"]) for b in blobs])
intensity_ratios = arr[:, 0] / np.maximum(arr[:, 1], 1)  # avoid div by zero
```

### 7d. joblib for Batch Processing

When processing a batch of captures (e.g., initial sync of 22K+ blobs), use joblib for parallel CPU:

```python
from joblib import Parallel, delayed

def classify_blob_batch(blob_batch):
    """Classify a batch of blobs in a worker process."""
    classifier = BlobClassifier()  # each process gets its own model
    return [classifier.classify_blob(b["patch"]) for b in blob_batch]

# Split 500 blobs into 4 chunks, process in parallel
chunks = np.array_split(blobs, 4)
results = Parallel(n_jobs=4)(delayed(classify_blob_batch)(chunk) for chunk in chunks)
```

### 7e. SQLite WAL + Memory-Mapped I/O

Already partially configured in `db.py`, but confirm these PRAGMAs are set:

```sql
PRAGMA journal_mode=WAL;           -- concurrent readers + writer
PRAGMA synchronous=NORMAL;         -- safe for WAL mode, faster
PRAGMA temp_store=MEMORY;          -- temp tables in RAM
PRAGMA mmap_size=268435456;        -- 256 MB memory map
PRAGMA cache_size=-65536;          -- 64 MB page cache
PRAGMA page_size=4096;             -- 4K pages (match OS)
```

The current `db.py` already sets WAL, NORMAL, TEMP_STORE, and mmap_size. Add `cache_size` and confirm `page_size`.

### 7f. Python Profiling (Find the Real Bottleneck)

Before optimizing, measure:

```python
import cProfile
# Run analyzer on 100 captures
cProfile.run("sync_all(force=True)", sort="cumtime")
```

The bottleneck is almost certainly I/O (reading 1920×1080 PNGs from disk) or OpenCV's pixel operations (already optimized). Optimize the slowest 10% only.

### Assessment

| Metric | Score | Notes |
|--------|-------|-------|
| Hardware cost | 1 | Same hardware, just better usage |
| Effort | 2 | Mostly config changes; ONNX export is the main work |
| Value | 3 | 2–3× speedup on analysis; frees CPU for other tasks |
| Risk | 1 | All reversible; profile before optimizing |

**Best path:** Start with profiling (#7f). Don't optimize blind. Then apply in priority order: SQLite PRAGMAs → ONNX Runtime for blob classifier → OpenCV OpenVINO backend → joblib for one-time batch syncs.

---

## 8. Multi-Agent Consensus

### Concept

Instead of one DeepInfra model making all decisions, run multiple smaller/cheaper models in parallel and let them "vote." Different models have different strengths:

| Model | DeepInfra ID | Strengths | Weaknesses |
|-------|-------------|-----------|------------|
| Hermes 3 70B | `NousResearch/Hermes-3-Llama-3.1-70B` | Long reasoning, nuanced descriptions | Expensive, slow |
| Nemotron 70B | `nvidia/Llama-3.1-Nemotron-70B-Instruct` | Structured output, reliable | Verbose |
| V4 Flash | `deepseek/deepseek-v4-flash` | Fast, cheap, good for simple tasks | Less nuanced |
| Seed2 | `aion-labs/deepseek-seed2` | Experimental, creative | Unpredictable |

Run the **cheap** model (V4 Flash) on every capture. Run the **expensive** model (Hermes) only on captures flagged as interesting.

Run multiple models on **important** captures and compare. If V4 Flash and Nemotron agree on "chum at 35 fm" but Seed2 says "no fish," go with the consensus.

### Lightweight Implementation

```python
import asyncio
import aiohttp

DEEPINFRA_URL = "https://api.deepinfra.ai/v1/openai/chat/completions"

class MultiAgentConsensus:
    """
    Query multiple DeepInfra models and reach consensus.

    The cheap model runs every time. Expensive models only on edge cases.
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.models = {
            "cheap": {
                "model": "deepseek/deepseek-v4-flash",
                "cost_per_1k": 0.0001,  # approximate
                "weight": 1.0,
            },
            "nemotron": {
                "model": "nvidia/Llama-3.1-Nemotron-70B-Instruct",
                "cost_per_1k": 0.0004,
                "weight": 1.5,
            },
            "hermes": {
                "model": "NousResearch/Hermes-3-Llama-3.1-70B",
                "cost_per_1k": 0.0004,
                "weight": 2.0,
            },
            "seed2": {
                "model": "aion-labs/deepseek-seed2",
                "cost_per_1k": 0.0001,
                "weight": 0.5,  # experimental, lower trust
            },
        }

    async def query_model(self, model_id: str, prompt: str, max_tokens: int = 200) -> dict:
        """Query a single DeepInfra model."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.3,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(DEEPINFRA_URL, json=payload, headers=headers, timeout=15) as resp:
                result = await resp.json()
                return {
                    "model": model_id,
                    "text": result["choices"][0]["message"]["content"],
                    "tokens": result.get("usage", {}).get("total_tokens", 0),
                    "success": True,
                }

    async def consensus(self, prompt: str, models: list[str] = None) -> dict:
        """
        Query multiple models and reach consensus.

        If models is None, query all.
        Returns consensus prediction with confidence.
        """
        if models is None:
            models = list(self.models.keys())

        # Fire all queries in parallel
        tasks = [
            self.query_model(self.models[m]["model"], prompt) for m in models
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Extract valid results
        valid = []
        for r in results:
            if isinstance(r, Exception):
                continue
            if r.get("success"):
                valid.append(r)

        if not valid:
            return {"consensus": None, "confidence": 0, "results": []}

        # Extract predictions from each model's output
        predictions = []
        for r in valid:
            parsed = self._parse_prediction(r["text"])
            if parsed:
                predictions.append({
                    "model": r["model"],
                    "species": parsed["species"],
                    "confidence": parsed.get("confidence", 0.5),
                    "weight": self._get_weight(r["model"]),
                })

        if not predictions:
            return {"consensus": None, "confidence": 0, "results": valid}

        # Weighted vote
        species_votes = {}
        for p in predictions:
            sp = p["species"]
            species_votes[sp] = species_votes.get(sp, 0) + p["weight"] * p["confidence"]

        total = sum(species_votes.values()) or 1
        consensus = max(species_votes, key=species_votes.get)
        confidence = species_votes[consensus] / total

        return {
            "consensus": consensus,
            "confidence": round(confidence, 3),
            "votes": species_votes,
            "predictions": predictions,
        }

    def _parse_prediction(self, text: str) -> dict:
        """Extract structured prediction from model output."""
        # Simple pattern matching
        text_lower = text.lower()
        species_list = ["chum", "coho", "chinook", "pollock", "rockfish", "halibut", "noise", "none"]

        for sp in species_list:
            if sp in text_lower:
                return {"species": sp, "confidence": 0.7}
        return None

    def _get_weight(self, model_id: str) -> float:
        for key, info in self.models.items():
            if info["model"] in model_id:
                return info["weight"]
        return 1.0
```

**Smart routing — cheap model decides when to escalate:**

```python
async def smart_capture_analysis(capture_data: dict, consensus: MultiAgentConsensus):
    """
    Quick analysis with cheap model. If confidence is low or anomaly score is high,
    escalate to full multi-agent consensus.
    """
    # Step 1: Quick analysis with Flash
    cheap_prompt = build_basic_prompt(capture_data)
    flash_result = await consensus.query_model(
        consensus.models["cheap"]["model"], cheap_prompt
    )

    # Step 2: Decide if escalation is needed
    anomaly_score = capture_data.get("anomaly_score", 0)
    flash_confidence = extract_confidence(flash_result["text"])

    if anomaly_score > 0.7 or flash_confidence < 0.6:
        log.info("Escalating to consensus — anomaly=%.2f, flash_conf=%.2f",
                 anomaly_score, flash_confidence)

        # Step 3: Full consensus with all models
        detailed_prompt = build_detailed_prompt(capture_data)
        consensus_result = await consensus.consensus(detailed_prompt, ["nemotron", "hermes"])

        return {
            "description": consensus_result["results"][0]["text"] if consensus_result.get("results") else flash_result["text"],
            "consensus": consensus_result["consensus"],
            "consensus_confidence": consensus_result["confidence"],
            "escalated": True,
        }

    return {
        "description": flash_result["text"],
        "consensus": None,
        "consensus_confidence": 0,
        "escalated": False,
    }
```

### Historical Accuracy Tracking

Weight models by their actual historical accuracy, not just reputation:

```python
class ModelAccuracyTracker:
    """Tracks which model was right about species in the past."""

    def __init__(self, db_path="model_accuracy.db"):
        self.db = sqlite3.connect(db_path)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS model_track (
                id INTEGER PRIMARY KEY,
                model TEXT,
                predicted_species TEXT,
                actual_species TEXT,
                capture_ts TEXT,
                correct INTEGER
            )
        """)

    def record(self, model: str, predicted: str, actual: str, ts: str):
        correct = 1 if predicted == actual else 0
        self.db.execute(
            "INSERT INTO model_track (model, predicted_species, actual_species, capture_ts, correct) "
            "VALUES (?, ?, ?, ?, ?)",
            (model, predicted, actual, ts, correct),
        )
        self.db.commit()

    def get_accuracy(self, model: str, window_days: int = 30) -> float:
        cur = self.db.execute("""
            SELECT AVG(correct) FROM model_track
            WHERE model = ? AND capture_ts >= datetime('now', ? || ' days')
        """, (model, f"-{window_days}"))
        result = cur.fetchone()[0]
        return result or 0.5  # default to neutral if no data
```

Then replace the static weights in `MultiAgentConsensus` with dynamic ones:

```python
def _get_weight(self, model_id: str) -> float:
    accuracy = self.tracker.get_accuracy(model_id, window_days=30)
    # Weight = accuracy × base_weight, clamped to 0.2–3.0
    base = self.models.get(model_id, {}).get("weight", 1.0)
    return max(0.2, min(3.0, accuracy * base))
```

### Cost Control

Multi-agent consensus multiplies API costs. Mitigation:

1. **Cheap model first, always.** V4 Flash costs ~$0.0001/1K tokens.
2. **Escalate only on edge cases.** High anomaly score or low Flash confidence triggers consensus.
3. **Batch non-urgent consensus.** If 5 captures in a row have low confidence, batch them into one consensus call after the fishing day.
4. **Cap daily spend.** Track tokens consumed. If daily cost exceeds threshold, fall back to cheap-only mode.

### Assessment

| Metric | Score | Notes |
|--------|-------|-------|
| Hardware cost | 1 | Zero local cost; API calls only |
| Effort | 3 | Prompt engineering, parsing, accuracy tracking — 2 weeks |
| Value | 4 | Better decisions on edge cases; model diversity reduces blind spots |
| Risk | 3 | API costs spiral if escalation fires too often; accuracy tracking needs ground truth |

**Best path:** Start with cheap-first routing only. Don't build consensus until you have accuracy data showing which models perform well on this domain. The static approach (pick one model, always use it) is 80% of the value at 20% of the cost.

---

## Priority Matrix

Sorted by (Value / Effort), highest ROI first:

| # | Idea | HW Cost | Effort | Value | Risk | ROI (V÷E) |
|---|------|---------|--------|-------|------|-----------|
| 5 | Temporal Pattern Mining | 1 | 3 | 5 | 1 | **1.67** ★★★ |
| 1 | On-Device Vision Models | 1 | 2 | 4 | 2 | **2.00** ★★★ |
| 4 | Signal Fusion | 1 | 3 | 5 | 2 | **1.67** ★★★ |
| 2 | Voice Catch Reports | 2 | 2 | 5 | 2 | **2.50** ★★☆ |
| 7 | CPU Acceleration | 1 | 2 | 3 | 1 | **1.50** ★★☆ |
| 8 | Multi-Agent Consensus | 1 | 3 | 4 | 3 | **1.33** ★★☆ |
| 3 | Offline Tiny LLM | 3 | 3 | 4 | 3 | **1.33** ★★☆ |
| 6 | Feedback Loops | 1 | 4 | 4 | 4 | **1.00** ★☆☆ |

★ = Ready now. ★★ = After basics are solid. ★ = Major effort or risk — do later.

---

## Suggested Build Order

### Sprint 1: Quick Wins (Week 1–2)

1. **CPU profiling** (#7 — find the real bottleneck, apply SQLite PRAGMAs)
2. **Anomaly detection** (#5d — rolling baseline, flag unusual captures)
3. **Voice catch reports via Telegram** (#2 — simplest path, immediate value)

### Sprint 2: Core Intelligence (Week 3–4)

4. **ONNX blob classifier** (#1 — train on another machine, export, integrate into analyzer)
5. **Signal fusion** (#4 — combine classifier output + NMEA + catch history)
6. **Diel/tidal correlation** (#5a, #5b — discover what patterns exist)

### Sprint 3: Resilience (Week 5–6)

7. **Offline LLM** (#3 — Llama-3.2-1B fallback for when DeepInfra is down)
8. **Cheap-first model routing** (#8 — V4 Flash by default, escalate on anomaly)

### Sprint 4: Learning System (Week 7+)

9. **Feedback loops** (#6 — suggestion logging, outcome tracking)
10. **Multi-agent consensus** (#8 full — accuracy-weighted voting)

---

## What NOT To Do (Anti-Patterns to Avoid)

1. **Don't try to run Florence-2 on CPU.** The 232M param model takes 30+ seconds on Intel iGPU — too slow for the 10-min cadence and it'll peg the CPU. Stick with OpenCV heuristics + tiny ONNX classifiers.

2. **Don't load both Ollama AND a local LLM simultaneously.** On 16 GB RAM with no GPU, you can't have both. Pick one: either Ollama with a small model, or llama-cpp-python with a GGUF model. Unload one before loading the other.

3. **Don't run multi-agent consensus on every capture.** API costs will spiral. Cheap model first, escalate only when anomaly score > 0.7.

4. **Don't optimize before profiling.** The current pipeline's bottleneck might not be what you think. Profile first.

5. **Don't build a full reinforcement learning system for feedback loops.** A SQLite table of suggestions + outcomes with simple counting is 90% of the value.

---

*Written 2026-07-18 — brainstorm for making the tzpro-agent smarter on F/V EILEEN's limited but capable hardware.*
