#!/usr/bin/env python3
"""vision.py — Vision-language screen understanding for tzpro-agent.

Replaces OpenCV pixel thresholds with Florence-2 visual understanding.
Two prompt tracks:
  - <CAPTION> for chart state description (full screen, 4-min cadence)
  - Structured extraction for sounder analysis (cropped panel, 30-s cadence)

Florence-2 base (232M params) in FP16: ~500 MB VRAM, ~2-3s inference.
"""

from __future__ import annotations
import json, logging, re, time
from pathlib import Path
from typing import Optional, Tuple

log = logging.getLogger("tzpro.vision")

# ── Model globals (loaded once, reused) ─────────────────────────────
_model = None
_processor = None
_device = None
_loaded = False


def load_model(model_name: str = "microsoft/florence-2-base") -> bool:
    """Load Florence-2 model into VRAM. Returns True on success.

    Model stays resident until unload() is called. On a 6GB RTX 4050,
    this uses ~500 MB VRAM in FP16, leaving room for other processes.
    """
    global _model, _processor, _device, _loaded

    if _loaded:
        return True

    try:
        import torch
        from transformers import AutoProcessor, AutoModelForCausalLM

        _device = "cuda" if torch.cuda.is_available() else "cpu"
        log.info("Loading %s on %s...", model_name, _device)

        _processor = AutoProcessor.from_pretrained(model_name, trust_remote_code=True)
        _model = AutoModelForCausalLM.from_pretrained(
            model_name, trust_remote_code=True
        ).to(_device)

        if _device == "cuda":
            _model = _model.half()  # FP16 for VRAM efficiency

        _loaded = True
        log.info("Florence-2 loaded (device=%s)", _device)
        return True

    except ImportError as e:
        log.warning("Cannot load Florence-2: %s. Install with: pip install transformers torch", e)
    except Exception as e:
        log.warning("Florence-2 load failed: %s", e)

    return False


def unload():
    """Release model from VRAM. Call when switching to Ollama or other GPU tasks."""
    global _model, _processor, _loaded
    _model = None
    _processor = None
    _loaded = False
    if _device == "cuda":
        import torch
        torch.cuda.empty_cache()
    log.info("Florence-2 unloaded, VRAM released")


# ══════════════════════════════════════════════════════════════════════
#  Task: Chart State Description (4-min cadence)
# ══════════════════════════════════════════════════════════════════════

def describe_chart(image_path: Path, previous_description: str = "") -> dict:
    """Describe the current TZ Pro chart state using Florence-2 <CAPTION>.

    Returns dict with:
      - description: natural language description of chart state
      - changes: list of detected changes vs previous_description
      - marks: any new marks/waypoints detected
      - alerts: any boundary or hazard alerts
    """
    if not _loaded:
        load_model()

    try:
        from PIL import Image
        img = Image.open(image_path).convert("RGB")

        # Task prompt: describe the entire chart display
        prompt = "<CAPTION>"
        inputs = _processor(text=prompt, images=img, return_tensors="pt").to(_device)

        generated_ids = _model.generate(
            input_ids=inputs["input_ids"],
            pixel_values=inputs["pixel_values"],
            max_new_tokens=150,
            num_beams=3,
        )
        description = _processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
        description = _clean_text(description)

        # Structured extraction: marks and alerts
        marks = _extract_marks(description)
        alerts = _extract_alerts(description)
        changes = _detect_changes(description, previous_description)

        result = {
            "description": description,
            "changes": changes,
            "marks": marks,
            "alerts": alerts,
        }
        log.info("Chart: %s", description[:80])
        return result

    except Exception as e:
        log.warning("Chart description error: %s", e)
        return {"description": "", "changes": [], "marks": [], "alerts": []}


# ══════════════════════════════════════════════════════════════════════
#  Task: Sounder Analysis (30-s cadence)
# ══════════════════════════════════════════════════════════════════════

def analyze_sounder_vl(image_path: Path) -> dict:
    """Analyze sounder echogram using Florence-2 structured extraction.

    Uses a specialized prompt to extract: bottom depth, bottom type,
    fish presence and depth, thermoclines.

    Returns dict with structured fields.
    """
    if not _loaded:
        load_model()

    try:
        from PIL import Image
        img = Image.open(image_path).convert("RGB")

        # Structured extraction prompt for sounder
        prompt = (
            "<OD>What is in this fishfinder image? "
            "Describe: bottom depth, bottom type (hard/soft/muddy/rocky), "
            "fish or schools visible and at what depth, "
            "any temperature layers or thermoclines."
        )
        inputs = _processor(text=prompt, images=img, return_tensors="pt").to(_device)

        generated_ids = _model.generate(
            input_ids=inputs["input_ids"],
            pixel_values=inputs["pixel_values"],
            max_new_tokens=200,
            num_beams=3,
        )
        raw = _processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
        raw = _clean_text(raw)

        # Parse structured fields from VL response
        result = _parse_sounder_description(raw)
        result["raw_vl_description"] = raw
        log.info("Sounder VL: depth=%s type=%s", result.get("depth"), result.get("bottom_type"))
        return result

    except Exception as e:
        log.warning("Sounder VL analysis error: %s", e)
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════

def _clean_text(text: str) -> str:
    """Remove Florence-2 special tokens and clean whitespace."""
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _detect_changes(current: str, previous: str) -> list[str]:
    """Compare descriptions and identify meaningful changes.
    Basic implementation — will be refined with structured comparison."""
    if not previous:
        return ["initial observation"]
    changes = []
    words_cur = set(current.lower().split())
    words_prev = set(previous.lower().split())
    new_words = words_cur - words_prev
    if new_words:
        changes.append(f"new elements: {', '.join(list(new_words)[:5])}")
    return changes


def _extract_marks(description: str) -> list[dict]:
    """Extract mention of marks, waypoints, or course changes."""
    marks = []
    patterns = [
        r"(?:mark|waypoint|pin|flag)\s*(?:called|named|at)?\s*([^,\.]+)",
        r"(?:course|heading)\s*(?:changed|turned|adjusted)\s*(?:to\s*)?(\d+)",
        r"(?:speed|sog)\s*(?:changed|adjusted|set)\s*(?:to\s*)?([\d\.]+)",
    ]
    for p in patterns:
        matches = re.findall(p, description.lower())
        for m in matches:
            marks.append(m.strip())
    return marks


def _extract_alerts(description: str) -> list[str]:
    """Extract any alerts or warnings mentioned."""
    alerts = []
    alert_kw = ["boundary", "alert", "warning", "caution", "danger", "shoal", "obstruction"]
    for word in alert_kw:
        if word in description.lower():
            alerts.append(word)
    return alerts


def _parse_sounder_description(vl_text: str) -> dict:
    """Parse structured sounder data from Florence-2's natural language output."""
    result = {
        "depth": None,
        "bottom_type": None,
        "fish_detected": False,
        "fish_depth_range": None,
        "thermocline_detected": False,
        "notes": vl_text[:200],
    }

    depth_matches = re.findall(r'(\d+)\s*(?:fathom|fm|foot|ft|meter|m)', vl_text.lower())
    if depth_matches:
        result["depth"] = int(depth_matches[-1][0])

    type_kw = {"hard": "hard", "rock": "rock", "soft": "soft", "mud": "mud", "sand": "sand", "mixed": "mixed"}
    for kw, btype in type_kw.items():
        if kw in vl_text.lower():
            result["bottom_type"] = btype
            break

    school_kw = ["school", "fish", "arch", "return", "bait", "target"]
    result["fish_detected"] = any(kw in vl_text.lower() for kw in school_kw)

    thermo_kw = ["thermocline", "temperature layer", "thermal", "temperature break"]
    result["thermocline_detected"] = any(kw in vl_text.lower() for kw in thermo_kw)

    return result


# ══════════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════════

def cli():
    """CLI: analyze a screenshot with Florence-2."""
    import sys
    if len(sys.argv) < 2:
        print("Usage: python vision.py <image.png> [--chart|--sounder]")
        return

    path = Path(sys.argv[1])
    mode = sys.argv[2] if len(sys.argv) > 2 else "--sounder"

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if not load_model():
        print("Failed to load model. Install: pip install transformers torch")
        return

    if mode == "--chart":
        result = describe_chart(path)
    else:
        result = analyze_sounder_vl(path)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    cli()
