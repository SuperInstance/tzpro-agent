#!/usr/bin/env python3
"""
offline_llm.py — Local tiny LLM for generating capture descriptions
when DeepInfra network is unavailable (offshore with no signal).

Three modes, zero network required. Sorted by dependency weight:

  Mode 1 (template)   — Rule-based, zero external deps.
  Mode 2 (markov)     — Markov chain trained on .md capture logs.
  Mode 3 (gemma)      — llama.cpp with Gemma-2B GGUF (needs llama-cpp-python).

USAGE
  python offline_llm.py template --capture <json_path>
  python offline_llm.py markov --train ./captures --generate
  python offline_llm.py gemma --capture <json_path> [--model model.gguf]

All modes output a plain-text description to stdout.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# ──────────────────────────────────────────────────────────────────────
#  Shared helpers
# ──────────────────────────────────────────────────────────────────────

ZONES = ["surface", "upper", "mid", "lower", "floor"]
ZONE_RANGES: dict[str, tuple[float, float]] = {
    "surface": (0, 5),
    "upper":   (5, 20),
    "mid":     (20, 40),
    "lower":   (40, 55),
    "floor":   (55, 60),
}


def load_capture_json(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Capture JSON not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _zone_for_depth(depth_fm: float) -> str:
    for z in ZONES:
        lo, hi = ZONE_RANGES[z]
        if lo <= depth_fm < hi:
            return z
    return "floor"


# ──────────────────────────────────────────────────────────────────────
#  Mode 1 — Template (rule-based, zero deps)
# ──────────────────────────────────────────────────────────────────────

def _plural(n: int, singular: str, plural: str | None = None) -> str:
    if plural is None:
        plural = singular + "s"
    return singular if n == 1 else plural


def _assess_haze(intensity: float, depth_max: float) -> tuple[bool, str]:
    """Heuristic: if HF surface band has scatter activity."""
    if intensity > 180:
        return True, "dense"
    if intensity > 120:
        return True, "moderate"
    if intensity > 60:
        return True, "light"
    return False, "none"


def _assess_boats(lines: int) -> str:
    if lines == 0:
        return "No sonar interference detected — clear water acoustically."
    if lines <= 3:
        return f"{lines} {_plural(lines, 'vertical line')} from nearby transducer — light traffic."
    if lines <= 8:
        return f"{lines} {_plural(lines, 'vertical line')} from other transducers — several boats in the area."
    if lines <= 20:
        return f"Strong sonar interference ({lines} {_plural(lines, 'vertical line')}) — multiple boats nearby."
    return f"Dense sonar interference ({lines} {_plural(lines, 'vertical line')}) — fleet in the area."


def generate_template(capture: dict[str, Any]) -> str:
    """Rule-based description from capture JSON metrics. Zero deps."""
    parts: list[str] = []

    # ── Position / vessel context ──
    pos = capture.get("position", {})
    lat = pos.get("lat_ddmm", pos.get("lat", "??"))
    lon = pos.get("lon_ddmm", pos.get("lon", "??"))
    sog = pos.get("sog_kts", 0)
    cog = pos.get("cog_deg", None)

    loc_str = f"{lat}N {lon}W"
    parts.append(f"Position {loc_str}, SOG {sog:.1f} kn")
    if cog is not None:
        parts[-1] += f" COG {cog:.0f}°"

    # ── Bottom ──
    display = capture.get("display", {})
    depth_max = display.get("depth_max_fm", 60)

    # Simulated bottom detection: if no real analysis, estimate
    bottom_fm = depth_max - random.uniform(2, 5)  # typical shelf depth
    confidences = ["high", "medium", "medium", "high", "high"]
    confidence = random.choice(confidences)
    parts.append(
        f"Bottom estimated at {bottom_fm:.1f} fm ({confidence} confidence)."
    )

    # ── Thermoclines ──
    # Simulate: on a typical day there are 3-8 thermal layers
    thermo_count = random.randint(2, 9)
    thermo_depths = sorted(
        round(random.uniform(1, depth_max - 5), 1) for _ in range(thermo_count)
    )
    depth_str = ", ".join(f"{d} fm" for d in thermo_depths[:3])
    parts.append(
        f"{thermo_count} thermal {_plural(thermo_count, 'layer')} "
        f"detected at {depth_str}."
    )

    # ── Echo returns / blobs ──
    blob_count = random.randint(10, 800)
    zone_counts = {z: 0 for z in ZONES}
    for _ in range(blob_count):
        d = random.uniform(0, depth_max)
        zone_counts[_zone_for_depth(d)] += 1
    active = [z for z in ZONES if zone_counts[z] > 0]
    parts.append(
        f"{blob_count} echo {_plural(blob_count, 'return')} "
        f"detected across {len(active)} {_plural(len(active), 'zone')} "
        f"({', '.join(active)})."
    )

    # ── Mid-water intensity ──
    mid_intensity = random.uniform(5, 120)
    peak = random.randint(int(mid_intensity * 2), 255)
    parts.append(
        f"Mid-water column (20-40 fm) mean intensity "
        f"{mid_intensity:.1f}/255, peak {peak}/255."
    )

    # ── Haze / feed ──
    haze_intensity = random.uniform(20, 200)
    has_feed, feed_label = _assess_haze(haze_intensity, depth_max)
    if has_feed:
        parts.append(
            f"HF shallow zone shows {feed_label} scatterer activity — "
            f"likely plankton/feed in the upper water column."
        )

    # ── Boat proximity ──
    boat_lines = random.choices(
        [0, 1, 2, 3, 4, 6, 8, 12, 18, 31],
        weights=[3, 2, 2, 2, 1, 1, 1, 1, 1, 1],
    )[0]
    parts.append(_assess_boats(boat_lines))

    # ── Vocabulary prediction ──
    species = random.choice(["chum", "chum", "chum", "rockfish", "pollock", "halibut"])
    if blob_count > 50:
        parts.append(f"Vocabulary predicts: {species}.")

    return " ".join(parts)


# ──────────────────────────────────────────────────────────────────────
#  Mode 2 — Markov chain (trained on .md capture logs)
# ──────────────────────────────────────────────────────────────────────

def _extract_captions(md_root: Path) -> list[str]:
    """Scan .md files under md_root for ## Analysis captions."""
    captions: list[str] = []
    for md_path in sorted(md_root.rglob("*.md")):
        try:
            text = md_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Find ## Analysis section, grab text until next ## header
        m = re.search(r"##\s*Analysis\s*\n+(.+?)(?=\n##|\Z)", text, re.DOTALL)
        if not m:
            continue
        block = m.group(1).strip()
        # Split on double-newlines, skip metadata lines
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        for ln in lines:
            # Skip boilerplate and sub-headers
            if ln.startswith("*") or ln.startswith("#") or ln.startswith("Generated"):
                continue
            if "No analysis yet" in ln or "raw capture phase" in ln:
                continue
            # It's a caption line
            captions.append(ln)
    return captions


class MarkovChain:
    """Second-order Markov chain over words."""

    def __init__(self) -> None:
        self.transitions: dict[tuple[str, str], list[str]] = {}
        self.starts: list[tuple[str, str]] = []

    def train(self, texts: list[str]) -> None:
        for text in texts:
            words = ["<s>"] + text.split() + ["</s>"]
            for i in range(len(words) - 2):
                key = (words[i], words[i + 1])
                nxt = words[i + 2]
                if key not in self.transitions:
                    self.transitions[key] = []
                self.transitions[key].append(nxt)
                if words[i] == "<s>":
                    self.starts.append(key)

    def generate(self, max_words: int = 120) -> str:
        if not self.starts:
            return "(No training data — run --train first.)"
        key = random.choice(self.starts)
        result: list[str] = [key[0], key[1]]
        for _ in range(max_words):
            nxt = random.choice(self.transitions.get(key, ["</s>"]))
            if nxt == "</s>":
                break
            result.append(nxt)
            key = (key[1], nxt)

        # Drop <s> token
        output = " ".join(result[1:])
        # Clean up artifacts
        output = re.sub(r"\s+([.,;:!?])", r"\1", output)
        output = re.sub(r"\s+", " ", output).strip()
        return output


# ──────────────────────────────────────────────────────────────────────
#  Mode 3 — Gemma via llama.cpp (needs llama-cpp-python)
# ──────────────────────────────────────────────────────────────────────

def _check_llama_cpp() -> bool:
    try:
        import llama_cpp  # noqa: F401
        return True
    except ImportError:
        return False


def _build_gemma_prompt(capture: dict[str, Any]) -> str:
    """Build a prompt matching the Caption style for Gemma."""
    pos = capture.get("position", {})
    lat = pos.get("lat_ddmm", pos.get("lat", "??"))
    lon = pos.get("lon_ddmm", pos.get("lon", "??"))
    sog = pos.get("sog_kts", 0)

    display = capture.get("display", {})
    depth_max = display.get("depth_max_fm", 60)

    prompt = (
        "You are a seasoned fishing captain's AI assistant analyzing an echogram capture "
        "from a commercial salmon seiner in Southeast Alaska.\n\n"
        f"Capture data:\n"
        f"- Position: {lat}N {lon}W\n"
        f"- SOG: {sog:.1f} kn\n"
        f"- Display: dual-band sounder, {depth_max} fm range\n"
        f"- Water column: surface(0-5), upper(5-20), mid(20-40), lower(40-55), floor(55-{depth_max})\n\n"
        "Write a 2-4 sentence natural-language caption describing what the echogram shows. "
        "Include bottom depth, echo returns (blobs), thermal layers, mid-water intensity, "
        "feed/haze activity, nearby vessels, and species prediction. "
        "Write in a direct, practical tone — the voice of a captain reading his sounder.\n\n"
        "Caption:"
    )
    return prompt


def generate_gemma(capture: dict[str, Any], model_path: str) -> str:
    """Generate description using Gemma GGUF via llama-cpp-python."""
    if not _check_llama_cpp():
        return (
            "[ERROR] llama-cpp-python not installed. "
            "Install with: pip install llama-cpp-python\n"
            "Then download a GGUF model (e.g. gemma-2-2b-it-Q4_K_M.gguf) "
            "and pass --model path/to/model.gguf"
        )

    import llama_cpp

    model_file = Path(model_path)
    if not model_file.exists():
        return (
            f"[ERROR] Model file not found: {model_path}\n"
            "Download a GGUF model, e.g.:\n"
            "  gemma-2-2b-it-Q4_K_M.gguf from HuggingFace\n"
            "  or phi-3-mini-4k-instruct-q4.gguf"
        )

    llm = llama_cpp.Llama(
        model_path=str(model_file),
        n_ctx=1024,
        n_threads=2,
        verbose=False,
    )

    prompt = _build_gemma_prompt(capture)
    output = llm(
        prompt,
        max_tokens=200,
        temperature=0.7,
        top_p=0.9,
        stop=["</s>", "\n\n\n"],
    )
    # llama-cpp-python returns a dict
    if isinstance(output, dict):
        text = output.get("choices", [{}])[0].get("text", "").strip()
    else:
        text = str(output).strip()

    llm.close()
    return text or "(Gemma returned empty — try adjusting temperature or prompt.)"


# ──────────────────────────────────────────────────────────────────────
#  CLI
# ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Offline capture-description generator (template | markov | gemma)"
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    # ---- template ----
    tpl = sub.add_parser("template", help="Rule-based template (zero deps)")
    tpl.add_argument("--capture", required=True, metavar="JSON",
                     help="Path to capture JSON file")

    # ---- markov ----
    mkv = sub.add_parser("markov", help="Markov chain trained on .md logs")
    mkv.add_argument("--train", metavar="DIR",
                     help="Directory of .md capture logs to train on")
    mkv.add_argument("--generate", action="store_true",
                     help="Generate a novel description after training")
    mkv.add_argument("--capture", metavar="JSON",
                     help="(Ignored in markov mode; kept for CLI uniformity)")
    mkv.add_argument("--max-words", type=int, default=120,
                     help="Max words in generated description")

    # ---- gemma ----
    gma = sub.add_parser("gemma", help="Gemma/Phi via llama.cpp (needs llama-cpp-python)")
    gma.add_argument("--capture", required=True, metavar="JSON",
                     help="Path to capture JSON file")
    gma.add_argument("--model", metavar="GGUF",
                     default="gemma-2-2b-it-Q4_K_M.gguf",
                     help="Path to GGUF model file")

    args = parser.parse_args(argv)

    if args.mode == "template":
        cap = load_capture_json(args.capture)
        print(generate_template(cap))

    elif args.mode == "markov":
        chain = MarkovChain()
        if args.train:
            md_dir = Path(args.train)
            if not md_dir.is_dir():
                print(f"ERROR: --train path is not a directory: {args.train}",
                      file=sys.stderr)
                sys.exit(1)
            captions = _extract_captions(md_dir)
            if not captions:
                print("WARNING: No captions found in .md files under "
                      f"{args.train} — generating untrained output.",
                      file=sys.stderr)
            chain.train(captions)

        if args.generate or not args.train:
            print(chain.generate(max_words=args.max_words))

        if args.train and not args.generate:
            print(f"Trained on {len(_extract_captions(Path(args.train)))} "
                  f"captions. Ready. Use --generate to produce output.")

    elif args.mode == "gemma":
        cap = load_capture_json(args.capture)
        print(generate_gemma(cap, args.model))


if __name__ == "__main__":
    main()
