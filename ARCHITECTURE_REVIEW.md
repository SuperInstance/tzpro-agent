# FishingLog.ai — Architectural Review
## Systems Engineering Assessment for the DAW-Inspired Marine Intelligence Platform

**Reviewer**: Systems Engineering Subagent
**Date**: 2026-07-15
**Platform**: F/V EILEEN — Windows 11, RTX 4050 6GB, dual monitors
**Ecosystem**: CoCapn.com / ActiveLedger.ai / FishingLog.ai / TzPro-Agent v1 (operational)

---

## Executive Summary

The current codebase (tzpro-agent v1) is a working sensor node that captures, analyzes, and logs sounder observations from a TZ Pro display using OpenCV pixel thresholds. The v2 vision extends this into a full fishing intelligence platform with four major new subsystems: TileDB echogram storage, Florence-2 vision-language understanding, catch correlation, and a DAW-style web dashboard. All of this must run within a 30-second loop on a laptop-grade GPU (RTX 4050 6GB) alongside an existing NMEA bridge, Docker gateway, and Ollama instance.

This review validates the architectural direction, identifies concrete implementation paths, and flags resource constraints. Each section below addresses one of the five pillars with specific libraries, schemas, API shapes, and data formats.

---

## 1. TileDB Echogram Schema

### 1.1 Data Characteristics

| Property | Value |
|----------|-------|
| Frame dimensions | 370 × 900 px (RGB) |
| Capture interval | 30 seconds |
| Daily volume | ~1,440 frames / 12h |
| Raw pixel data/day | 370×900×3×1440 ≈ 1.44 GB uncompressed |
| Target row group | 1 fishing day |

### 1.2 Recommended Schema: Dense 3D Array

The natural representation is a **time × depth × horizontal** dense array where each time-slice is one sounder frame. This enables time-range queries ("show me 14:00–14:30"), depth-range queries ("returns between 5–15 fm"), and cross-frame arithmetic ("average bottom intensity for this pass").

```python
import tiledb

# Schema definition
echogram_schema = tiledb.ArraySchema(
    domain=tiledb.Domain(
        # Primary dimension: time in milliseconds since epoch
        tiledb.Dim(
            name="time_ms",
            domain=(0, int(1e15)),        # covers centuries
            tile=3600000,                  # 1 hour per tile fragment
            dtype="uint64",
        ),
        # Depth index: 0 = surface, 899 = bottom of frame
        tiledb.Dim(
            name="depth_px",
            domain=(0, 899),
            tile=900,                      # full depth in one tile
            dtype="uint16",
        ),
        # Horizontal position in frame: 0 = left, 369 = right
        tiledb.Dim(
            name="horizontal_px",
            domain=(0, 369),
            tile=370,                      # full width in one tile
            dtype="uint16",
        ),
    ),
    attributes=[
        # Grayscale intensity derived from RGB: 0-255
        tiledb.Attr(name="intensity", dtype="uint8", filters=[
            tiledb.FilterList([
                tiledb.ZstdFilter(level=7),
            ])
        ]),
        # Optional: store dominant color channel for palette analysis
        tiledb.Attr(name="color_channel", dtype="uint8", filters=[
            tiledb.FilterList([tiledb.ZstdFilter(level=5)])
        ]),
        # Placeholder for ML embedding: 256-dim float vector per pixel
        # tiledb.Attr(name="embedding", dtype="float32", shape=(256,)),
    ],
    cell_order="row-major",    # time-major: all pixels for one frame contiguous
    tile_order="row-major",
    capacity=370*900,          # one frame per tile cell
    sparse=False,              # dense: every pixel has a value
)

# Create the array
tiledb.Array.create("echograms/2026-07-15", echogram_schema)
```

### 1.3 Writing Frames

```python
def write_echogram_frame(array_uri: str, ts_ms: int, pixels: np.ndarray):
    """
    Write one 370×900 sounder frame to TileDB.
    pixels shape: (900, 370) grayscale uint8
    """
    depth_idx = np.arange(900)
    horiz_idx = np.arange(370)
    time_grid = np.full((900, 370), ts_ms, dtype=np.uint64)
    depth_grid, horiz_grid = np.meshgrid(horiz_idx, depth_idx)
    
    with tiledb.open(array_uri, "w") as A:
        A[ts_ms, :, :] = pixels
```

### 1.4 Reading Time Slices

```python
def read_time_window(array_uri: str, t_start_ms: int, t_end_ms: int) -> np.ndarray:
    """Read all frames in a time range. Returns shape (N, 900, 370)."""
    with tiledb.open(array_uri, "r") as A:
        data = A[t_start_ms:t_end_ms, :, :]["intensity"]
    return data
```

### 1.5 Fragment Strategy

| Parameter | Recommendation | Rationale |
|-----------|---------------|-----------|
| Fragment per | 6 hours (720 frames) | Keeps fragments ~350MB; manageable for committal |
| Consolidation | Daily, offline | Single fragment per day after consolidation |
| Vacuum | Weekly | Clean up consolidated fragments |
| Compression | Zstd level 7 | Good balance on real sonar data (expect 3-5x compression on natural images) |

### 1.6 Metadata Sidecar (SQLite)

TileDB handles the array. All **metadata** goes into SQLite for fast relational queries:

```sql
CREATE TABLE echogram_frames (
    frame_id INTEGER PRIMARY KEY,
    ts_utc TEXT NOT NULL,           -- ISO 8601
    ts_ms INTEGER UNIQUE NOT NULL,  -- aligned with TileDB dimension
    depth_scale_max_fm REAL,        -- calibrated max depth for this frame
    nmea_lat REAL,
    nmea_lon REAL,
    sog REAL,
    cog REAL,
    tiledb_fragment TEXT,           -- which TileDB fragment contains this frame
    image_path TEXT,                 -- path to original .png on disk
    file_size_bytes INTEGER
);

CREATE INDEX idx_frames_time ON echogram_frames(ts_ms);
CREATE INDEX idx_frames_position ON echogram_frames(nmea_lat, nmea_lon);
```

### 1.7 Storage Budget

| Component | Per Day | Per Season (90 days) |
|-----------|---------|----------------------|
| TileDB compressed | ~300–500 MB | ~27–45 GB |
| PNG source images | ~1.44 GB (1,440 × ~1 MB each) | ~130 GB |
| SQLite metadata | ~500 KB | ~45 MB |
| JSONL observations | ~5 MB | ~450 MB |
| **Total** | **~1.75–2 GB** | **~160–175 GB** |

The EILEEN host has ~290 GB free on C:. A full season fits with room to spare if PNG cleanup is applied (keep originals for 7 days, purge after consolidation).

---

## 2. Florence-2 for Screen Understanding

### 2.1 Model Selection for RTX 4050 6GB

| Model | Params | VRAM (FP16) | VRAM (int8) | Inference on 4050 | Est. Speed |
|-------|--------|-------------|-------------|-------------------|------------|
| `microsoft/Florence-2-base` | 232M | ~500 MB | ~300 MB | ✅ Comfortable | ~2-3s |
| `microsoft/Florence-2-large` | 771M | ~1.5 GB | ~800 MB | ✅ Feasible | ~3-5s |
| Florence-2-large + LoRA | 771M+~6M | ~1.6 GB | — | ✅ Feasible | ~3-5s |
| Qwen2-VL-2B | 2B | ~4 GB | ~2 GB | ⚠️ Tight | ~4-6s |
| LLaVA-NeXT-7B | 7B | ~14 GB | ~7 GB | ❌ Won't fit | — |

**Recommendation**: `microsoft/Florence-2-base` in FP16 with ONNX Runtime for GPU acceleration. The 232M parameter model completes inference in ~1.5-3s on an RTX 4050 at 1920×1080 input, leaving headroom for other GPU tasks (Ollama, TileDB).

### 2.2 Prompt Architecture

Florence-2 uses **task prompt tokens** that define the output mode. For the TZ Pro screen, we need two distinct tasks:

#### Task A: Full Frame (chart area) — 4-minute cadence

```python
from transformers import AutoProcessor, AutoModelForCausalLM

prompts = {
    # Detailed caption of chart state
    "chart_caption": "<CAPTION>Describe the navigation chart display: "
                     "position, course overlay, waypoints, alarms, and vessel track.",
    
    # Structured extraction (returns JSON-like output)
    "chart_elements": "<OD>What navigation elements are visible? "
                      "Report: [lat, lon, course_made_good, speed, waypoints, alarms, cursor_position]",
    
    # Change detection — compare to prior frame (requires two images)
    "chart_delta": "<CAPTION>What changed compared to the previous screenshot? "
                   "Report: new_alerts, course_changes, cursor_movement, new_marks.",
}
```

#### Task B: Sounder Crop — 30-second cadence (replaces current analyze_sounder)

```python
sounder_prompts = {
    "sounder_analysis": "<CAPTION>Analyze the fishfinder display. "
                        "Report: bottom_depth_fathoms, bottom_hardness, "
                        "fish_returns_density, fish_depth_range, "
                        "thermocline_layers, water_column_clutter_level.",
    
    "structured_extraction": "<CAPTION>Extract the following values as machine-readable JSON: "
                             "{'depth_max_meters': ?, "
                             "'bottom_y_px': ?, "
                             "'fish_return_count': ?, "
                             "'thermocline_count': ?, "
                             "'palette': 'blue'}",
}
```

### 2.3 Inference Pipeline (GPU-Optimized)

```python
import torch
from PIL import Image
from transformers import AutoProcessor, Florence2ForConditionalGeneration

class FlorenceSounderAnalyzer:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.processor = AutoProcessor.from_pretrained(
            "microsoft/Florence-2-base", trust_remote_code=True
        )
        self.model = Florence2ForConditionalGeneration.from_pretrained(
            "microsoft/Florence-2-base",
            torch_dtype=torch.float16,
            trust_remote_code=True,
        ).to(self.device)
        self.model.eval()
        # Warm up
        dummy = Image.new("RGB", (370, 900))
        self._infer(dummy, self.sounder_prompt)
        torch.cuda.empty_cache()

    def _infer(self, image: Image.Image, prompt: str) -> str:
        inputs = self.processor(text=prompt, images=image, return_tensors="pt").to(self.device)
        with torch.no_grad():
            generated_ids = self.model.generate(
                **inputs,
                max_new_tokens=256,
                num_beams=3,
                do_sample=False,
            )
        result = self.processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
        return result

    def analyze_sounder(self, image: Image.Image) -> dict:
        """Replace OpenCV analyzer with VL model. Returns structured dict."""
        raw = self._infer(image, sounder_prompts["structured_extraction"])
        # Parse JSON from model output
        return self._parse_response(raw)  # regex or json.loads fallback

    def describe_chart(self, image: Image.Image, prev_image: Image.Image = None) -> dict:
        """Full frame understanding. Returns structured chart state."""
        if prev_image:
            # Composite for delta: stack both images side-by-side
            composite = Image.new("RGB", (image.width * 2, image.height))
            composite.paste(prev_image, (0, 0))
            composite.paste(image, (image.width, 0))
            raw = self._infer(composite, prompts["chart_delta"])
        else:
            raw = self._infer(image, prompts["chart_caption"])
        return self._parse_response(raw)
```

### 2.4 Prompt Design Principles for TZ Pro

The VL model must be prompted with specific domain knowledge to produce useful output:

1. **Be explicit about output structure**: Florence-2 does not natively emit JSON. Use `<CAPTION>` mode and ask for a specific format. Post-process with regex/JSON parser.

2. **Two-pass for reliability** (if under 5s budget):
   - Pass 1: `<CAPTION>` for natural language description (fast, beam=1)
   - Pass 2 (if time allows): `<OD>` for structured detection (slower, beam=3)

3. **Color palette awareness**: The prompt should mention the blue palette. Example:
   ```
   "The fishfinder uses a blue background with cyan→yellow→orange→red returns.
    Describe the water column. Report coordinates of the strongest return."
   ```

4. **Negative prompting for null states**:
   ```
   "If no fish schools or thermoclines are visible, report 'empty water column'."
   ```

### 2.5 Training Data Pipeline for Fine-Tuning

Fine-tuning Florence-2 on TZ Pro displays requires a labeled dataset. The current OpenCV pipeline can **self-generate training data**:

```python
"""
Self-supervised training data pipeline:

Phase 1 — Bootstrap (manual labels, ~500 frames):
- Capture 500 sounder frames across varied conditions
- Human labels: bottom_depth, bottom_type, fish_count, thermocline_count
- Store as: {image_path, label_json}

Phase 2 — Semi-supervised (use current OpenCV as weak labeler):
- Run OpenCV analyzer on 5000 unlabeled frames
- Filter to high-confidence predictions only
- Use as pseudo-labels for fine-tuning

Phase 3 — Active learning:
- When Florence-2 and OpenCV disagree significantly
- Flag for human review on-demand
- Add to training set

Data format for LoRA fine-tuning:
"""
```

**LoRA fine-tuning setup**:

```python
from peft import LoraConfig, get_peft_model
from transformers import TrainingArguments, Trainer

lora_config = LoraConfig(
    r=8,
    lora_alpha=16,
    target_modules=["q_proj", "v_proj"],  # Florence-2 attention
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM",
)

# Dataset format: HuggingFace Dataset with
# { "image": PIL.Image, "prompt": str, "answer": str }

training_args = TrainingArguments(
    output_dir="./florence-tzpro-lora",
    per_device_train_batch_size=2,         # fits RTX 4050 6GB
    gradient_accumulation_steps=4,
    learning_rate=2e-4,
    num_train_epochs=3,
    fp16=True,
    logging_steps=10,
    save_strategy="epoch",
    remove_unused_columns=False,
)
```

### 2.6 VL Model → Structured Log Output

The model output must be parsed into the existing JSONL schema:

```python
def vl_to_observation(vl_result: str) -> dict:
    """
    Parse Florence-2 output into the observation schema.

    Natural language input like:
    "Bottom depth: 22.5 fathoms. Bottom type: hard.
     Fish returns: 45 moderate targets from 0.15 to 0.42 depth fraction."

    → structured JSON dict compatible with logger.py
    """
    # Regex extraction patterns
    patterns = {
        "depth_fm": r"bottom.depth[:\s]+([\d.]+)",
        "bottom_type": r"bottom.type[:\s]+(\w+)",
        "fish_count": r"fish.return[:\s]+(\d+)",
        "distribution": r"(scattered|moderate|dense|very.dense)",
    }
    result = {}
    for key, pattern in patterns.items():
        m = re.search(pattern, vl_result, re.IGNORECASE)
        if m:
            result[key] = m.group(1)

    # Map to observation schema
    return {
        "depth_fm": float(result.get("depth_fm", 0)),
        "bottom_type": result.get("bottom_type", "unknown"),
        "fish_returns": {
            "count": int(result.get("fish_count", 0)),
            "distribution": result.get("distribution", "unknown"),
        },
    }
```

---

## 3. Catch Correlation Loop

### 3.1 Data Model

The catch database lives alongside TileDB in SQLite:

```sql
CREATE TABLE catch_events (
    catch_id INTEGER PRIMARY KEY,
    ts_utc TEXT NOT NULL,
    ts_ms INTEGER NOT NULL,           -- aligned with TileDB time dimension
    species TEXT NOT NULL,             -- e.g. "chinook", "coho", "halibut"
    count INTEGER NOT NULL DEFAULT 1,
    depth_avg_fm REAL,                 -- average depth of gear when fish struck
    depth_range_fm TEXT,               -- "18-22"
    position_lat REAL,
    position_lon REAL,
    sog REAL,
    gear_type TEXT DEFAULT "troll",
    notes TEXT
);

CREATE INDEX idx_catch_time ON catch_events(ts_ms);
CREATE INDEX idx_catch_species ON catch_events(species);
CREATE INDEX idx_catch_position ON catch_events(position_lat, position_lon);
```

### 3.2 Algorithm: Simple Waveform Signature Matcher

The algorithm operates in three phases. This is the **minimal viable approach** — no deep learning, no complex spectrograms. Just statistical feature extraction + cosine similarity.

#### Phase (a): Extract Signature from Catch Time Window

For each catch event, extract a feature vector from the echogram window:

```python
import numpy as np
from scipy import signal

def extract_catch_signature(
    echogram: np.ndarray,          # shape (N_frames, 900, 370), time window
    catch_depth_fm: float,
    depth_scale_max: float,        # max depth for this echogram
) -> dict:
    """
    Extract a waveform "signature" from the echogram window around a catch.

    Returns a feature dict that serves as the signature for this catch type.
    """
    n_frames, h, w = echogram.shape

    # 1. Vertical profile: average across horizontal for each frame
    #    Shape: (N_frames, 900)
    vertical_profiles = echogram.mean(axis=2)

    # 2. Bottom intensity trace: max intensity in bottom ~20% of column
    bottom_zone = int(h * 0.8)
    bottom_trace = vertical_profiles[:, bottom_zone:].max(axis=1)

    # 3. Water column intensity (above bottom)
    water_column = vertical_profiles[:, :bottom_zone].mean(axis=1)

    # 4. Fish arch candidates: local peaks in water column
    fish_arch_count = 0
    for frame in vertical_profiles:
        peaks, props = signal.find_peaks(
            frame[:bottom_zone],
            height=30,       # minimum intensity
            distance=10,     # minimum separation between arches
            prominence=15,   # must stand out from background
        )
        fish_arch_count += len(peaks)
    fish_arch_rate = fish_arch_count / n_frames  # avg arches per frame

    # 5. Depth-stratified histogram: how is intensity distributed with depth?
    depth_bins = 10
    hist_bottom_zone = echogram[:, :bottom_zone, :].reshape(n_frames, -1)
    depth_layers = np.array_split(
        echogram[:, :, w//3:2*w//3],  # center column only (most representative)
        depth_bins,
        axis=1,
    )
    layer_means = np.array([layer.mean() for layer in depth_layers])

    # 6. Temporal variance: how much does the water column change?
    temporal_variance = np.var(vertical_profiles.mean(axis=1))

    signature = {
        "catch_depth_bin": int(catch_depth_fm / depth_scale_max * depth_bins),
        "bottom_intensity_mean": float(bottom_trace.mean()),
        "bottom_intensity_std": float(bottom_trace.std()),
        "water_column_mean": float(water_column.mean()),
        "water_column_std": float(water_column.std()),
        "fish_arch_rate": float(fish_arch_rate),
        "depth_layer_profile": layer_means.tolist(),
        "temporal_variance": float(temporal_variance),
        "n_frames": n_frames,
        "duration_seconds": n_frames * 30,
    }

    return signature
```

#### Phase (b): Build Signature Library

```python
class CatchSignatureLibrary:
    """
    In-memory library of catch signatures.
    Persisted to SQLite for durability.
    """

    def __init__(self, db_path: str = "data/catch_signatures.db"):
        self.db_path = db_path
        self._init_db()
        self.signatures = self._load_all()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS catch_signatures (
                signature_id INTEGER PRIMARY KEY,
                species TEXT NOT NULL,
                created_utc TEXT NOT NULL,
                signature_json TEXT NOT NULL,
                catch_count INTEGER DEFAULT 1,
                avg_confidence REAL DEFAULT 0.5
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS signature_catch_links (
                link_id INTEGER PRIMARY KEY,
                signature_id INTEGER NOT NULL,
                catch_id INTEGER NOT NULL,
                similarity REAL,
                FOREIGN KEY (signature_id) REFERENCES catch_signatures(signature_id)
            )
        """)
        conn.close()

    def add_signature(self, species: str, signature: dict, catch_ids: list) -> int:
        """Add or update a species signature."""
        conn = sqlite3.connect(self.db_path)
        # Serialize signature to JSON
        sig_json = json.dumps(signature)
        conn.execute(
            "INSERT INTO catch_signatures (species, created_utc, signature_json) "
            "VALUES (?, ?, ?)",
            (species, datetime.utcnow().isoformat(), sig_json),
        )
        sig_id = conn.lastrowid
        for cid in catch_ids:
            conn.execute(
                "INSERT INTO signature_catch_links (signature_id, catch_id) VALUES (?, ?)",
                (sig_id, cid),
            )
        conn.commit()
        conn.close()
        self.signatures[sig_id] = signature
        return sig_id
```

#### Phase (c): Predict from New Echogram Tiles

```python
def predict_catch_probability(
    live_signature: dict,
    library: dict[int, dict],
    species_lookup: dict[int, str],
) -> list[dict]:
    """
    Compare a live echogram window against all known signatures.

    Returns sorted list of predictions:
    [{"species": "chinook", "confidence": 0.87}, ...]
    """
    predictions = []

    for sig_id, ref_sig in library.items():
        similarity = _signature_similarity(live_signature, ref_sig)
        if similarity > 0.5:  # threshold
            predictions.append({
                "species": species_lookup[sig_id],
                "signature_id": sig_id,
                "confidence": round(similarity, 3),
            })

    predictions.sort(key=lambda x: x["confidence"], reverse=True)
    return predictions


def _signature_similarity(a: dict, b: dict) -> float:
    """Cosine similarity between two signature vectors."""
    # Build fixed-length feature vectors
    keys = [
        "bottom_intensity_mean", "bottom_intensity_std",
        "water_column_mean", "water_column_std",
        "fish_arch_rate", "temporal_variance",
    ]
    vec_a = np.array([a.get(k, 0) for k in keys])
    vec_b = np.array([b.get(k, 0) for k in keys])

    # Add depth layer profile (padded to common length)
    da = np.array(a.get("depth_layer_profile", []))
    db = np.array(b.get("depth_layer_profile", []))
    max_len = max(len(da), len(db))
    da = np.pad(da, (0, max_len - len(da)))
    db = np.pad(db, (0, max_len - len(db)))

    vec_a = np.concatenate([vec_a, da])
    vec_b = np.concatenate([vec_b, db])

    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)
    if norm_a == 0 or norm_b == 0:
        return 0.0

    return float(np.dot(vec_a, vec_b) / (norm_a * norm_b))
```

### 3.3 Complexity Analysis

| Operation | Complexity | Time on ~100k pixels |
|-----------|------------|---------------------|
| Signature extraction (one 10-frame window) | O(10 × 900 × 370) | ~15ms (NumPy) |
| Library comparison (100 signatures) | O(100 × 10 features) | ~1ms |
| Full match check (live window vs all lib) | ~16ms | ✅ Under budget |

### 3.4 Simple Improvement Path

```
v0.1 → Statistical feature vectors + cosine similarity  (NOW)
v0.2 → Add depth-relative intensity profiles             (week 1)
v0.3 → Add temporal autocorrelation (is fish density cycling?)  (week 2)
v1.0 → Replace with embedding model (echogram → 128-dim via small CNN)  (season 2)
```

---

## 4. DAW Frontend Architecture

### 4.1 Backend: Lightweight Web Server

```python
# backend/app.py — FastAPI web server
from fastapi import FastAPI, WebSocket, Query
from fastapi.responses import StreamingResponse
import tiledb
import sqlite3
import json
import asyncio
from datetime import datetime, timedelta

app = FastAPI(title="FishingLog.ai DAW")

ENGINE_DB = "data/fishinglog.db"
TILEDB_ROOT = "echograms"

# ─── REST Endpoints ─────────────────────────────────────────────

@app.get("/api/v1/tracks")
async def list_tracks(
    date: str = Query(None, description="Date YYYY-MM-DD, default today")
):
    """List available sensor tracks for a given day."""
    date = date or datetime.utcnow().strftime("%Y-%m-%d")
    conn = sqlite3.connect(ENGINE_DB)
    cursor = conn.execute("""
        SELECT name, data_type, sample_count, min_ts, max_ts
        FROM tracks WHERE date = ?
    """, (date,))
    tracks = [dict(zip([d[0] for d in cursor.description], row)) for row in cursor.fetchall()]
    conn.close()
    return {"date": date, "tracks": tracks}


@app.get("/api/v1/tracks/{track_name}/data")
async def get_track_data(
    track_name: str,
    t_start: str = Query(None, description="ISO 8601 start"),
    t_end: str = Query(None, description="ISO 8601 end"),
    downsample: int = Query(1, description="Downsample factor (1 = full res)"),
):
    """Get time-series data for a track within a window."""
    # Subselect based on track type
    # Returns GeoJSON-compatible FeatureCollection for track overlay
    pass


@app.get("/api/v1/echogram/tiles")
async def get_echogram_tiles(
    t_start: str = Query(...),
    t_end: str = Query(...),
    bins: int = Query(370, description="Horizontal bins for resampling"),
):
    """
    Return echogram data as a lightweight 2D intensity array
    for the given time window. The browser renders this as a canvas.

    Returns: { "time_dims": [...], "depth_dims": [...], "intensity": [[...], ...] }
    """
    t0 = int(datetime.fromisoformat(t_start).timestamp() * 1000)
    t1 = int(datetime.fromisoformat(t_end).timestamp() * 1000)

    # Read from TileDB
    array_uri = f"{TILEDB_ROOT}/{t_start[:10]}"
    with tiledb.open(array_uri, "r") as A:
        data = A[t0:t1, :, :]["intensity"]

    # Downsample time axis
    n_frames = data.shape[0]
    stride = max(1, n_frames // bins)
    data = data[::stride, :, :]

    return {
        "time_dims": [datetime.utcfromtimestamp(ts/1000).isoformat()
                       for ts in range(t0, t1, (t1-t0)//stride)][:data.shape[0]],
        "depth_dims": list(range(900)),
        "intensity": data.tolist(),  # shape (N, 900, 370)
    }


@app.get("/api/v1/echogram/thumbnail")
async def get_echogram_thumbnail(
    t_start: str = Query(...), t_end: str = Query(...),
    max_width: int = Query(800), max_height: int = Query(200),
):
    """Return a tiny pre-rendered PNG thumbnail for the timeline overview."""
    # Render echogram to a small PNG on the server, return as bytes
    # This avoids sending 2MB arrays for the overview timeline
    pass


@app.get("/api/v1/catches")
async def get_catches(
    t_start: str = None, t_end: str = None, species: str = None
):
    """Get catch events as GeoJSON features."""
    conn = sqlite3.connect(ENGINE_DB)
    query = "SELECT * FROM catch_events WHERE 1=1"
    params = []
    if t_start:
        query += " AND ts_utc >= ?"
        params.append(t_start)
    if t_end:
        query += " AND ts_utc <= ?"
        params.append(t_end)
    if species:
        query += " AND species = ?"
        params.append(species)

    cursor = conn.execute(query, params)
    features = []
    for row in cursor.fetchall():
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [row[5], row[4]],
            },
            "properties": {
                "catch_id": row[0],
                "ts": row[1],
                "species": row[3],
                "count": row[4],
                "depth": row[5],
            },
        })
    conn.close()
    return {"type": "FeatureCollection", "features": features}


# ─── WebSocket for real-time ─────────────────────────────────────

@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    """
    Real-time push of new observations.
    The daemon publishes to a Redis channel (or in-process Queue);
    the WebSocket endpoint subscribes and fans out.
    """
    await websocket.accept()
    try:
        while True:
            # Get latest from daemon message queue
            data = await live_queue.get()
            await websocket.send_json(data)
    except WebSocketDisconnect:
        pass


# ─── Static Files ────────────────────────────────────────────────

from fastapi.staticfiles import StaticFiles
app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")
```

### 4.2 Track Catalog (SQLite)

```sql
-- Track catalog: every sensor stream is a row
CREATE TABLE tracks (
    track_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,          -- "echogram", "rudder", "compass", "sog", "catches"
    data_type TEXT NOT NULL,     -- "echogram_3d", "time_series", "event_stream"
    date TEXT NOT NULL,          -- "2026-07-15"
    sample_count INTEGER,
    min_ts TEXT,
    max_ts TEXT,
    tile_source TEXT,            -- for echograms: TileDB array URI
    jsonl_source TEXT,           -- for events: path to JSONL
    config_json TEXT             -- display configuration for frontend
);

CREATE UNIQUE INDEX idx_track_name_date ON tracks(name, date);
```

### 4.3 Frontend Rendering Strategy

The DAW dashboard is an HTML5 single-page app. The key challenge: **rendering 12 hours of 30-second echogram tiles without crashing the browser**.

#### Solution: Multi-Resolution Timeline with Virtual Rendering

```
┌─────────────────────────────────────────────────────┐
│ [12h Overview Bar ─────────────────────────────]    │  ← 800px wide = 1px/min
│  25px height, canvas, every pixel is ~2 min         │
├─────────────────────────────────────────────────────┤
│ [Sounder Track ━━━━━━━━━━━━━━━━━━━━━━━━━━]          │  ← Visible window
│  Canvas 900px height × viewport width               │
│  Loads only visible time range                      │
│  370px wide per frame, resampled to fit viewport    │
├─────────────────────────────────────────────────────┤
│ [Rudder ─────────────────────────────────────]       │  ← SVG line chart
│ [Compass ────────────────────────────────────]       │  ← SVG line chart
│ [SOG ───────────────────────────────────────]        │  ← SVG line chart
├─────────────────────────────────────────────────────┤
│ [Catch Events ●●○●○○○●○○]                         │  ← Event markers
└─────────────────────────────────────────────────────┘
```

#### Rendering Pipeline

```javascript
// frontend/src/echogram-track.js

class EchogramTrack {
    constructor(container, { date, tileServer }) {
        this.container = container;
        this.tileServer = tileServer;
        this.canvas = document.createElement('canvas');
        this.canvas.height = 300;  // display height (downsampled depth)
        this.container.appendChild(this.canvas);
        this.ctx = this.canvas.getContext('2d');
        this.visibleWindow = null;  // { tStart, tEnd }
        this.level = 0;             // zoom level
    }

    async renderViewport(tStart, tEnd) {
        this.visibleWindow = { tStart, tEnd };

        // Choose resolution based on zoom level
        // Level 0 (12h overview): fetch 800 time bins
        // Level 1 (1h view): fetch 3600 time bins (1 per second)
        // Level 2 (10min view): fetch full 30s resolution

        // This determines the API call
        const binCount = this.getBinCount(tStart, tEnd);
        const url = `/api/v1/echogram/tiles?t_start=${tStart}&t_end=${tEnd}&bins=${binCount}`;

        const response = await fetch(url);
        const { time_dims, depth_dims, intensity } = await response.json();

        // Downsample depth to fit canvas height
        const depthStep = Math.max(1, Math.floor(depth_dims.length / this.canvas.height));
        const width = this.canvas.width;
        const height = this.canvas.height;

        // Render to ImageData for performance
        const imageData = this.ctx.createImageData(width, height);
        for (let y = 0; y < height; y++) {
            for (let x = 0; x < width; x++) {
                const depthIdx = Math.min(y * depthStep, depth_dims.length - 1);
                const timeIdx = Math.min(x, intensity.length - 1);
                const val = intensity[timeIdx]?.[depthIdx]?.[180] || 0; // center column
                // Map to palette (blue → cyan → yellow → orange → red)
                const [r, g, b] = this.paletteMap(val);
                const idx = (y * width + x) * 4;
                imageData.data[idx] = r;
                imageData.data[idx + 1] = g;
                imageData.data[idx + 2] = b;
                imageData.data[idx + 3] = 255;
            }
        }
        this.ctx.putImageData(imageData, 0, 0);
    }

    getBinCount(tStart, tEnd) {
        const durationMs = new Date(tEnd) - new Date(tStart);
        if (durationMs > 3600000) return 800;           // >1h: overview
        if (durationMs > 600000) return 2000;            // 10-60min: medium
        return Math.min(370, durationMs / 30000);        // <10min: full res
    }

    paletteMap(val) {
        // Replicate TZ Pro blue palette
        if (val < 30)  return [14, 29, 52];    // dark blue bg
        if (val < 60)  return [0, 100, 200];    // blue
        if (val < 90)  return [0, 180, 200];    // cyan
        if (val < 120) return [200, 200, 0];    // yellow
        if (val < 150) return [255, 120, 0];    // orange
        return [255, 40, 0];                     // red
    }
}
```

#### Virtual Timeline with RxJS (or lightweight vanilla)

```javascript
// frontend/src/timeline.js

class DAWTimeline {
    constructor() {
        this.zoomLevel = 0;      // 0=12h, 1=4h, 2=1h, 3=10min
        this.visibleRange = { start: null, end: null };

        // Wheel zoom
        this.container.addEventListener('wheel', (e) => {
            e.preventDefault();
            this.zoomAt(e.deltaY < 0 ? 1 : -1, e.clientX);
        });

        // Pan
        this.container.addEventListener('mousedown', this.startPan.bind(this));
    }

    zoomAt(direction, xPixel) {
        this.zoomLevel = Math.max(0, Math.min(4, this.zoomLevel + direction));
        const centerRatio = xPixel / this.container.clientWidth;
        // Adjust visibleRange centered on the zoom point
        this.updateVisibleRange();
        this.renderTracks();
    }
}
```

### 4.4 Data Flow: TileDB → Browser

```
TileDB (disk)
    │
    ▼
FastAPI Server (Python)
    ├── /api/v1/echogram/tiles?t_start=...&t_end=...&bins=...
    │   └── Reads TileDB → numpy → downsampled 2D int array → JSON
    │
    ├── /api/v1/echogram/thumbnail?t_start=...&t_end=...
    │   └── Reads TileDB → renders tiny PNG server-side → base64
    │
    └── /ws/live (WebSocket)
        └── New frames pushed in real-time via in-process queue
              │
              ▼
        Browser (Vanilla JS / Svelte / Preact)
            ├── Canvas: echogram track (ImageData blitting)
            ├── SVG: time-series tracks (rudder, compass, SOG)
            └── DOM: catch event markers
```

### 4.5 Performance Budget (Frontend)

| Operation | Budget | Technique |
|-----------|--------|-----------|
| Load 12h overview | < 500ms | 800-bin downsampled fetch + thumbnail |
| Pan 1h window | < 200ms | 2000-bin fetch, ~40KB payload |
| Full-res 10min | < 300ms | 20 frames, ~370×900×20 → downsampled to viewport |
| Real-time update | < 50ms | WebSocket push + ImageData.blit |

---

## 5. The 30-Second Loop

### 5.1 Daemon Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                      30-Second Loop                                 │
│                                                                     │
│  T+0.0s ─ Capture Screen (PowerShell)                               │
│             ├── Full frame 1920×1080 → full_{ts}.png                 │
│             └── → 1-2 seconds                                        │
│                                                                     │
│  T+2.0s ─ VL Model — Chart Understanding                             │
│             ├── Florence-2 → chart description + deltas              │
│             ├── Parse lat/lon/SOG from LLM output                    │
│             │   (or prefer NMEA bridge if available)                 │
│             └── → 2-4 seconds                                        │
│                                                                     │
│  T+5.0s ─ Crop Sounder (PIL)                                         │
│             ├── Crop 370×900 from full frame                         │
│             └── → < 0.1 seconds                                      │
│                                                                     │
│  T+5.1s ─ VL Model — Sounder Analysis                                │
│             ├── Florence-2 → bottom, fish, thermoclines              │
│             └── → 2-4 seconds (GPU already loaded)                   │
│                                                                     │
│  T+8.0s ─ Write to TileDB                                            │
│             ├── Convert RGB to grayscale                             │
│             ├── Write array (dense write, ~333k cells)               │
│             ├── Append to SQLite metadata                            │
│             └── → 0.5-1 second                                       │
│                                                                     │
│  T+9.0s ─ Log Observations (JSONL)                                   │
│             ├── NMEA fetch from hermitd (:8654)                      │
│             ├── Merge VL results + NMEA → structured observation     │
│             ├── Append to YYYY-MM-DD.jsonl                           │
│             └── → 0.2 seconds                                         │
│                                                                     │
│  T+9.5s ─ Catch Pattern Match                                        │
│             ├── Load last 10 frames signature (already in memory)    │
│             ├── Compare against signature library (in-memory)        │
│             ├── If confidence > threshold → log prediction           │
│             └── → 0.1-0.5 seconds                                    │
│                                                                     │
│  T+10s ─ Sleep until next 30s boundary                               │
│             ├── Elapsed: ~10s                                        │
│             └── Sleep: ~20s                                          │
│                                                                     │
│  ═══════════════════════════════════════════════════════════         │
│  Total budget: ~10s active + 20s sleep = 30s loop                   │
│  Headroom: 66% margin for NMEA timeouts, GPU scheduling, GC         │
└─────────────────────────────────────────────────────────────────────┘
```

### 5.2 Implementation: pipeline.py

```python
#!/usr/bin/env python3
"""pipeline.py — The 30-second capture-analyze-store loop.

Orchestrates multi-stage pipeline with configurable parallelism.
Runs as a background daemon on Windows 11 / RTX 4050.

Usage:
    python pipeline.py              # run daemon
    python pipeline.py --oneshot    # single pipeline run
"""

from __future__ import annotations
import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

from config import SOUNDER_CROP, CAPTURES_DIR
from screenshot import capture_full
from logger import log_observation
from nmea_client import NmeaClient  # lightweight HTTP pull from hermitd

log = logging.getLogger("tzpro.pipeline")


@dataclass
class PipelineContext:
    """Shared context for one pipeline iteration."""
    ts_utc: str
    ts_ms: int
    full_frame_path: Optional[Path] = None
    sounder_array: Optional[np.ndarray] = None  # (900, 370) uint8
    nmea: dict = field(default_factory=dict)
    chart_deltas: dict = field(default_factory=dict)
    sounder_analysis: dict = field(default_factory=dict)
    catch_prediction: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)


class CapturePipeline:
    """Orchestrates one capture-analyze-store cycle."""

    def __init__(self):
        self.nmea = NmeaClient("http://127.0.0.1:8654/vessel")
        self.signature_lib = None  # Lazy load CatchSignatureLibrary
        self.last_chart_state = None
        self.sounder_analyzer = None  # Lazy load Florence model
        self.chart_analyzer = None    # Lazy load chart model

    async def run_once(self) -> PipelineContext:
        """Execute one full pipeline iteration."""
        ctx = PipelineContext(
            ts_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ts_ms=int(time.time() * 1000),
        )

        try:
            # Stage 1: Capture
            ctx.full_frame_path = await self._capture()
            if not ctx.full_frame_path:
                raise RuntimeError("Screen capture failed")

            # Stage 2: VL chart understanding (parallelizable)
            if self.chart_analyzer:
                chart_task = asyncio.create_task(
                    self._analyze_chart(ctx.full_frame_path, self.last_chart_state)
                )

            # Stage 3: Crop sounder
            sounder_img = self._crop_sounder(ctx.full_frame_path)
            ctx.sounder_array = np.array(sounder_img.convert("L"))  # grayscale

            # Stage 4: VL sounder analysis (or OpenCV fallback)
            if self.sounder_analyzer:
                ctx.sounder_analysis = await self._analyze_sounder_vl(sounder_img)
            else:
                from sounder_analyzer import analyze_sounder
                ctx.sounder_analysis = analyze_sounder(ctx.full_frame_path)

            # Stage 5: Wait for chart analysis if running in parallel
            if self.chart_analyzer:
                ctx.chart_deltas = await chart_task

            # Stage 6: NMEA
            ctx.nmea = self.nmea.fetch()

            # Stage 7: Write to TileDB
            await self._write_tiledb(ctx)

            # Stage 8: Write observations (JSONL)
            observation = self._build_observation(ctx)
            log_observation(observation)

            # Stage 9: Catch pattern match
            ctx.catch_prediction = await self._match_patterns(ctx)

            log.info(
                "Pipeline: ts=%s depth=%s bottom=%s fish=%s",
                ctx.ts_utc,
                ctx.sounder_analysis.get("bottom_depth_fm"),
                ctx.sounder_analysis.get("bottom_type"),
                ctx.sounder_analysis.get("fish_returns", {}).get("distribution"),
            )

        except Exception as e:
            ctx.errors.append(str(e))
            log.error("Pipeline error: %s", e)

        return ctx

    async def _capture(self) -> Optional[Path]:
        return await asyncio.to_thread(capture_full)

    def _crop_sounder(self, full_path: Path) -> Image.Image:
        img = Image.open(full_path)
        return img.crop(SOUNDER_CROP)

    async def _analyze_chart(self, full_path: Path, prev_state) -> dict:
        """Run Florence-2 on full frame for chart understanding."""
        # Lazy load
        if self.chart_analyzer is None:
            from models.florence import ChartAnalyzer
            self.chart_analyzer = ChartAnalyzer()
        img = Image.open(full_path)
        prev_img = Image.open(prev_state) if prev_state else None
        result = await asyncio.to_thread(
            self.chart_analyzer.describe_chart, img, prev_img
        )
        self.last_chart_state = full_path
        return result

    async def _analyze_sounder_vl(self, sounder_img: Image.Image) -> dict:
        if self.sounder_analyzer is None:
            from models.florence import SounderAnalyzer
            self.sounder_analyzer = SounderAnalyzer()
        return await asyncio.to_thread(self.sounder_analyzer.analyze_sounder, sounder_img)

    async def _write_tiledb(self, ctx: PipelineContext):
        """Write sounder frame to TileDB array."""
        import tiledb
        date_str = ctx.ts_utc[:10]
        array_uri = f"echograms/{date_str}"
        if not tiledb.array_exists(array_uri):
            self._create_schema(array_uri)

        intensity = ctx.sounder_array  # (900, 370) uint8
        with tiledb.open(array_uri, "w") as A:
            A[ctx.ts_ms, :, :] = intensity

    def _create_schema(self, array_uri: str):
        echogram_schema = tiledb.ArraySchema(
            domain=tiledb.Domain(
                tiledb.Dim(name="time_ms", domain=(0, int(1e15)),
                           tile=3600000, dtype="uint64"),
                tiledb.Dim(name="depth_px", domain=(0, 899),
                           tile=900, dtype="uint16"),
                tiledb.Dim(name="horizontal_px", domain=(0, 369),
                           tile=370, dtype="uint16"),
            ),
            attributes=[
                tiledb.Attr(name="intensity", dtype="uint8", filters=[
                    tiledb.FilterList([tiledb.ZstdFilter(level=7)])
                ]),
            ],
            cell_order="row-major",
            tile_order="row-major",
            capacity=370*900,
            sparse=False,
        )
        tiledb.Array.create(array_uri, echogram_schema)
        log.info("Created TileDB array: %s", array_uri)

    def _build_observation(self, ctx: PipelineContext) -> dict:
        return {
            "ts": ctx.ts_utc,
            "sounder_frame": ctx.full_frame_path.name if ctx.full_frame_path else None,
            "position": {
                "lat": ctx.nmea.get("lat"),
                "lon": ctx.nmea.get("lon"),
            },
            "vessel": {
                "sog": ctx.nmea.get("sog"),
                "cog": ctx.nmea.get("cog"),
            },
            "sounder_analysis": {
                "depth_fm": ctx.sounder_analysis.get("bottom_depth_fm"),
                "bottom_type": ctx.sounder_analysis.get("bottom_type"),
                "confidence": ctx.sounder_analysis.get("confidence"),
                "fish": ctx.sounder_analysis.get("fish_returns"),
                "thermoclines": ctx.sounder_analysis.get("thermoclines"),
            },
            "chart_state": ctx.chart_deltas,
            "catch_prediction": ctx.catch_prediction,
        }

    async def _match_patterns(self, ctx: PipelineContext) -> dict:
        if not self.signature_lib:
            self.signature_lib = CatchSignatureLibrary()
            if not self.signature_lib.signatures:
                return {"matched": False, "reason": "no_signatures"}

        # Build live signature from recent frames
        recent = self._get_recent_frames(ctx.ts_ms, window_frames=10)
        if recent is None:
            return {"matched": False, "reason": "insufficient_data"}

        live_sig = extract_catch_signature(recent, catch_depth_fm=0, depth_scale_max=80)
        predictions = predict_catch_probability(
            live_sig, self.signature_lib.signatures, {}
        )

        return {
            "matched": len(predictions) > 0,
            "predictions": predictions[:3],
            "top_species": predictions[0]["species"] if predictions else None,
            "top_confidence": predictions[0]["confidence"] if predictions else 0,
        }

    def _get_recent_frames(self, ts_ms: int, window_frames: int = 10):
        """Read last N frames from TileDB for signature extraction."""
        import tiledb
        date_str = datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")
        array_uri = f"echograms/{date_str}"
        if not tiledb.array_exists(array_uri):
            return None

        window_ms = window_frames * 30000
        t0 = ts_ms - window_ms
        with tiledb.open(array_uri, "r") as A:
            try:
                data = A[t0:ts_ms, :, :]["intensity"]
                return data
            except Exception:
                return None


async def daemon_loop():
    """Main daemon loop — runs every 30 seconds, aligned to :00/:30."""
    pipeline = CapturePipeline()
    log.info("Pipeline daemon starting")

    while True:
        now = time.time()
        # Align to next 30-second boundary
        next_tick = (int(now) // 30 + 1) * 30
        sleep_s = next_tick - now
        if sleep_s > 0:
            await asyncio.sleep(sleep_s)

        await pipeline.run_once()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if "--oneshot" in sys.argv:
        import json
        loop = asyncio.new_event_loop()
        pipeline = CapturePipeline()
        ctx = loop.run_until_complete(pipeline.run_once())
        print(json.dumps(ctx.__dict__, indent=2, default=str, skipkeys=True))
        return

    try:
        asyncio.run(daemon_loop())
    except KeyboardInterrupt:
        log.info("Shutdown")


if __name__ == "__main__":
    main()
```

### 5.3 Resource Budget (Windows 11 / RTX 4050 6GB)

| Component | VRAM | CPU | Notes |
|-----------|------|-----|-------|
| Florence-2 base (FP16) | ~500 MB | — | Loaded once, inference ~2-3s |
| Ollama (qwen3:4b) | ~3 GB | — | Existing; avoid simultaneous inference |
| TileDB (write path) | ~100 MB | + | Zstd compression, ~500ms per write |
| NMEA bridge + Docker | ~200 MB | + | Already running |
| Windows + background | ~2 GB | + | |
| **Total GPU VRAM** | **~3.6-4 GB** | | **1.5-2.4 GB headroom** ✅ |
| **Total RAM** | **~4-5 GB** | | **Headroom on 16GB machine** ✅ |

**Key constraint**: Florence-2 and Ollama cannot run inference simultaneously on a 6GB GPU. The pipeline must schedule them sequentially:
- Sounder loop (30s): Florence-2 active, Ollama idle
- Full-frame loop (240s): Florence-2 + chart analysis, Ollama idle
- User queries: Ollama active, Florence-2 idle (pipeline skips VL, falls back to OpenCV)
- Or: batch VL inference during low-demand periods

### 5.4 Process Model (Windows Service)

The daemon should run as a Windows scheduled task or lightweight service:

```xml
<!-- Scheduled task XML for Windows Task Scheduler -->
<Task>
  <Triggers>
    <BootTrigger>
      <Delay>PT30S</Delay>
    </BootTrigger>
  </Triggers>
  <Actions>
    <Exec>
      <Command>python</Command>
      <Arguments>C:\Users\casey\tzpro-agent\pipeline.py</Arguments>
      <WorkingDirectory>C:\Users\casey\tzpro-agent</WorkingDirectory>
    </Exec>
  </Actions>
  <Settings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <MultipleInstancesPolicy>StopExisting</MultipleInstancesPolicy>
  </Settings>
</Task>
```

Or use a simple wrapper for user control:

```powershell
# start-pipeline.ps1
$job = Start-Job -ScriptBlock {
    Set-Location C:\Users\casey\tzpro-agent
    python pipeline.py
}
Write-Host "Pipeline started (Job ID: $($job.Id))"
Register-ScheduledJob -Name FishingLogPipeline -ScriptBlock {
    Set-Location C:\Users\casey\tzpro-agent
    python C:\Users\casey\tzpro-agent\pipeline.py
} -Trigger (New-JobTrigger -AtStartup)
```

### 5.5 Error Recovery

| Failure | Detection | Recovery |
|---------|-----------|----------|
| Screen capture timeout | >15s in `_capture()` | Retry once, skip this cycle |
| Florence-2 OOM | `torch.cuda.OutOfMemoryError` | Fall back to OpenCV analyzer, log error |
| NMEA bridge down | HTTP timeout in NmeaClient | Continue with position=None, retry each cycle |
| TileDB write failure | IOError | Queue to local buffer, retry next cycle |
| Disk full | Disk quota monitoring | Purge old PNGs (>7 days), alert captain |

---

## Summary: Build Order & Dependencies

### Phase 2a (Immediate — Week 1-2)

```
1. tile · TileDB schema + write pipeline
   → Dep: tiledb pip package, numpy, schema from Section 1
   → Test: write 100 frames, verify readback

2. florence · VL model integration
   → Dep: transformers, torch, Florence-2 weights
   → Test: 100 frames vs OpenCV baseline, measure accuracy + timing

3. pipeline · New daemon loop (Section 5)
   → Integrates #1 + #2, replaces current capture.py
   → Feature flag: VL_ONLY, OPENCV_FALLBACK, HYBRID

4. signature · Catch signature library (Section 3)
   → Dep: SQLite, scipy.signal
   → Test: synthetic catch patterns against noise
```

### Phase 2b (Near term — Week 3-4)

```
5. chart · VL model for full-frame chart understanding
   → Same Florence-2 model, different prompt
   → Log chart deltas to observations

6. api · FastAPI backend (Section 4.1)
   → Dep: fastapi, uvicorn, tiledb, sqlite3
   → Endpoints: /api/v1/tracks, /api/v1/echogram/tiles

7. frontend · DAW dashboard (Section 4.3)
   → Dep: canvas API, fetch, WebSocket
   → Skeleton: timeline + echogram track + SOG/compass
```

### Phase 3 (Season 1)

```
8. catch-ui · Catch entry + correlation display
9. replay · Day-replay mode (scrub through timeline)
10. fleet · Multi-boat data aggregation
```

---

## Appendix: Dependency Checklist

```bash
# Core
pip install tiledb          # ~50MB binary wheel, requires MSVC runtime
pip install pillow           # already installed
pip install numpy            # needed for TileDB arrays
pip install scipy            # signal.find_peaks for catch signatures

# VL Model
pip install torch            # 2.x with CUDA 12.x, ~2.5GB download
pip install transformers     # HuggingFace, ~500MB
pip install microsoft/florence-2  # via transformers AutoModel
pip install peft             # LoRA fine-tuning

# Web Backend
pip install fastapi uvicorn

# Frontend
# Vanilla JS + Canvas API — zero framework dependencies
# Optional: install Svelte for component model
# npm install svelte vite   # if framework desired
```

**TileDB gotcha on Windows**: The official PyPI wheel for Windows requires the TileDB DLL. Install via `pip install tiledb` — the wheel bundles the DLL for x64. If it fails, install via conda: `conda install -c conda-forge tiledb-py`.

---

## Architecture Decisions Record

| Decision | Choice | Rationale |
|----------|--------|-----------|
| VL Model | Florence-2 base (232M) | Smallest model that does visual understanding; fits in 6GB VRAM alongside Ollama (with careful scheduling) |
| TileDB dim order | time × depth × hz | Time-major for efficient time-slice queries |
| Frame compression | Zstd level 7 | Best quality/speed tradeoff for natural images |
| Metadata store | SQLite | Zero-dependency, single-file, already familiar to team |
| API style | REST + WebSocket | REST for historical queries, WS for live push |
| Frontend rendering | Canvas ImageData | Blazing fast, no DOM overhead for pixel data |
| Timeline rendering | Multi-resolution lazy load | Only loads visible time window; server-side downsampling |
| Fallback model | Current OpenCV analyzer | Always available, no GPU, ~50ms inference |
| Pipeline alignment | 30-second wall-clock ticks | Aligns with sounder data rate, simplifies replay |

---
*Architectural review prepared for the CoCapn ecosystem — CoCapn.com / ActiveLedger.ai / FishingLog.ai*
*F/V EILEEN — Ketchikan, Alaska — July 15, 2026*
