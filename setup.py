#!/usr/bin/env python3
"""
setup.py — One-command setup for tzpro-agent pipeline.

Installs dependencies, pulls Ollama models, builds the contour grid,
and initializes the anomaly database. Designed to be run once on a fresh clone.

Usage:
    python setup.py                    # Full setup
    python setup.py --quick            # Skip contour grid build (10 min)
    python setup.py --models           # Only install Ollama models
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

WORKSPACE = Path(__file__).parent.resolve()

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
RESET = "\033[0m"


def step(msg: str) -> None:
    print(f"\n{CYAN}▸ {msg}{RESET}")


def ok(msg: str = "OK") -> None:
    print(f"  {GREEN}✓{RESET} {msg}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}⚠{RESET} {msg}")


def fail(msg: str) -> None:
    print(f"  {RED}✗{RESET} {msg}")


def run(cmd: list[str], timeout: int = 120) -> bool:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode == 0:
            ok(r.stdout.strip()[:80] if r.stdout else "done")
            return True
        else:
            fail(r.stderr.strip()[:120] if r.stderr else f"exit code {r.returncode}")
            return False
    except FileNotFoundError:
        fail(f"command not found: {cmd[0]}")
        return False
    except subprocess.TimeoutExpired:
        fail("timed out")
        return False


def check_python() -> bool:
    """Verify Python 3.10+."""
    v = sys.version_info
    if v.major >= 3 and v.minor >= 10:
        ok(f"Python {v.major}.{v.minor}.{v.micro}")
        return True
    fail(f"Python {v.major}.{v.minor} — need 3.10+")
    return False


def check_pip_deps() -> bool:
    """Install Python dependencies."""
    step("Installing Python dependencies")
    deps = ["pillow", "numpy"]
    return run([sys.executable, "-m", "pip", "install"] + deps, timeout=120)


def check_ollama() -> bool:
    """Verify Ollama is running."""
    step("Checking Ollama")
    try:
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags")
        with urllib.request.urlopen(req, timeout=5) as r:
            import json
            models = json.loads(r.read()).get("models", [])
            model_names = [m["name"] for m in models]
            ok(f"Ollama running, models: {', '.join(model_names)}")
            
            # Pull required models
            for model in ["nomic-embed-text"]:
                if model not in model_names:
                    warn(f"Pulling {model}...")
                    run(["ollama", "pull", model], timeout=300)
                else:
                    ok(f"{model} already present")
            
            return True
    except Exception as e:
        warn(f"Ollama not responding: {e}")
        return False


def check_tesseract() -> bool:
    """Verify Tesseract is installed."""
    step("Checking Tesseract")
    return run(["tesseract", "--version"], timeout=10)


def check_nmea_bridge() -> bool:
    """Verify NMEA bridge is running."""
    step("Checking NMEA bridge")
    try:
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:8654/status")
        with urllib.request.urlopen(req, timeout=3) as r:
            ok("NMEA bridge responding")
            return True
    except Exception:
        warn("NMEA bridge not responding (expected if not running)")
        return False


def build_contours() -> bool:
    """Build the contour grid from XYZ data."""
    step("Building contour grid (10 min)")
    xyz_path = Path(r"C:\Users\casey\all\71326.xyz")
    if not xyz_path.exists():
        warn(f"XYZ file not found at {xyz_path}")
        warn("Skipping contour grid build. Run 'python bathy_contours.py' when data is available.")
        return True
    
    contours_dir = WORKSPACE / "bathymetry" / "contours"
    grid_path = contours_dir / "elevation_grid.npy"
    
    if grid_path.exists():
        ok(f"Grid already exists ({grid_path.stat().st_size / 1024**2:.0f} MB)")
        return True
    
    return run([sys.executable, str(WORKSPACE / "bathy_contours.py")], timeout=1800)


def init_anomaly_db() -> bool:
    """Initialize the anomaly database."""
    step("Initializing anomaly database")
    return run([sys.executable, str(WORKSPACE / "anomaly_logger.py"), "--stats"], timeout=15)


def test_capture() -> bool:
    """Run a test capture to verify the pipeline."""
    step("Running test capture")
    return run([sys.executable, str(WORKSPACE / "capture.py"), "--oneshot"], timeout=30)


def main():
    print("=" * 60)
    print(f"  {CYAN}tzpro-agent — First Sensor Node Setup{RESET}")
    print(f"  {CYAN}F/V EILEEN, Ketchikan Alaska{RESET}")
    print("=" * 60)
    
    quick = "--quick" in sys.argv
    models_only = "--models" in sys.argv
    
    checks = [
        ("Python version", check_python),
    ]
    
    if models_only:
        checks += [
            ("Python deps", check_pip_deps),
            ("Ollama", check_ollama),
        ]
    elif quick:
        checks += [
            ("Python deps", check_pip_deps),
            ("Ollama", check_ollama),
            ("Tesseract", check_tesseract),
            ("NMEA bridge", check_nmea_bridge),
            ("Anomaly DB", init_anomaly_db),
            ("Test capture", test_capture),
        ]
    else:
        checks += [
            ("Python deps", check_pip_deps),
            ("Ollama", check_ollama),
            ("Tesseract", check_tesseract),
            ("NMEA bridge", check_nmea_bridge),
            ("Contour grid", build_contours),
            ("Anomaly DB", init_anomaly_db),
            ("Test capture", test_capture),
        ]
    
    passed = 0
    failed = 0
    
    for name, fn in checks:
        if models_only and name not in ("Python deps", "Ollama"):
            continue
        if fn():
            passed += 1
        else:
            failed += 1
    
    print(f"\n{'=' * 60}")
    if failed == 0:
        print(f"  {GREEN}✓ Setup complete — {passed}/{passed} checks passed{RESET}")
        print(f"\n  Next: python capture.py          # Start capture daemon")
        print(f"        python agent_loop.py        # Start agent loop")
        print(f"        python monologue.py          # Start internal monologue")
    else:
        print(f"  {YELLOW}⚠ Setup with {failed} warning(s) — {passed}/{passed + failed} passed{RESET}")
        print(f"  Review warnings above; system is partially operational.")
    
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
