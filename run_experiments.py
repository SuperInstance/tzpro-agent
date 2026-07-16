#!/usr/bin/env python3
"""
run_experiments.py — Batch experiment runner for Florence-2.

Runs experiments, captures output to timestamped log files,
so results survive rendering bugs and session resets.

Usage (from venv_cuda):
    venv_cuda\Scripts\python run_experiments.py
"""

import json, sys, time
from datetime import datetime
from pathlib import Path

# Add workspace to path
sys.path.insert(0, str(Path(__file__).parent.resolve()))

LOG_DIR = Path(__file__).parent / "_experiment_logs"
LOG_DIR.mkdir(exist_ok=True)

def log_result(name, data):
    path = LOG_DIR / f"{datetime.now():%H%M%S}_{name}.json"
    path.write_text(json.dumps(data, indent=2, default=str))
    return path

def step(name, fn):
    print(f"  {name}...", end=" ")
    try:
        result = fn()
        p = log_result(name, result)
        print(f"{result.get('status','ok')} -> {p.name}")
    except Exception as e:
        p = log_result(name, {"status": "error", "error": str(e)})
        print(f"error -> {p.name}")

# ── Experiment 1: Check GPU ─────────────────────────────────────
def check_gpu():
    import torch
    return {
        "torch": torch.__version__,
        "cuda": torch.cuda.is_available(),
        "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu",
        "vram_free_gb": round(torch.cuda.mem_get_info()[0]/1024**3, 2) if torch.cuda.is_available() else 0,
    }

# ── Experiment 2: Load Florence-2 ──────────────────────────────
def load_florence():
    from vision import load_model, _model, _processor
    ok = load_model()
    params = sum(p.numel() for p in _model.parameters()) if _model else 0
    return {
        "loaded": ok,
        "model_params_m": round(params/1e6) if params else 0,
        "device": str(_model.device) if _model else None,
    }

# ── Experiment 3: Analyze sounder crop ──────────────────────────
def analyze_sounder():
    from vision import analyze_sounder_vl
    captures = Path(__file__).parent / "captures"
    sounders = sorted(captures.glob("*sounder*.png"))
    if not sounders:
        return {"error": "no sounder images", "status": "skipped"}
    return analyze_sounder_vl(sounders[-1])

# ── Experiment 4: OpenCV comparison ────────────────────────────
def analyze_opencv():
    from sounder_analyzer import analyze_sounder
    captures = Path(__file__).parent / "captures"
    sounders = sorted(captures.glob("*sounder*.png"))
    if not sounders:
        return {"error": "no sounder images", "status": "skipped"}
    return analyze_sounder(sounders[-1])

# ── Experiment 5: Memory search warmup ──────────────────────────
def memory_search():
    from memory_search import embed
    v = embed("gear depth contour crossing at 48 fathoms")
    return {
        "model": "nomic-embed-text",
        "dims": len(v) if v else 0,
        "sample": v[:3] if v else None,
    }

# ── Experiment 6: Monologue ────────────────────────────────────
def monologue():
    from monologue import read_sensors, think, _ollama_generate
    sensors = read_sensors()
    if "error" in sensors:
        return {"status": "no_position", "sensors": sensors}
    entry = think(sensors)
    return {
        "sensors": {k: v for k, v in sensors.items() if k != "profile"},
        "monologue": entry.to_dict() if entry else None,
    }

if __name__ == "__main__":
    print("=" * 50)
    print("tzpro-agent Experiment Runner")
    print(f"Started: {datetime.now():%Y-%m-%d %H:%M:%S}")
    print("=" * 50)
    
    experiments = [
        ("GPU check", check_gpu),
        ("Memory search", memory_search),
        ("Florence-2 load", load_florence),
        ("Sounder VL analysis", analyze_sounder),
        ("OpenCV comparison", analyze_opencv),
    ]
    
    for name, fn in experiments:
        step(name, fn)
    
    print()
    print(f"Logs: {LOG_DIR}")
    print("Done. Results written to timestamped JSON files.")
