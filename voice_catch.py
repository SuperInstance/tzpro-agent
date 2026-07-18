#!/usr/bin/env python3
"""
Voice Catch Report System
==========================
"chum at 35 on green flasher, 15 fish" → structured catch report.

Usage:
    python voice_catch.py record          # listen via mic, transcribe, parse
    python voice_catch.py "chum at 35 fm 15 fish"  # parse text directly
    python -c "from voice_catch import parse_catch; r=parse_catch('chum at 35 fm 15 fish'); print(r)"
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

# ── Species fuzzy-match roster ──────────────────────────────────────────────
# Keys are canonical short names. Values are lists of aliases.
SPECIES_ALIASES: dict[str, list[str]] = {
    "chum":       ["chum", "chum salmon", "dog salmon", "dog", "calico"],
    "coho":       ["coho", "silver", "silver salmon", "coho salmon"],
    "king":       ["king", "chinook", "spring", "spring salmon",
                   "king salmon", "chinook salmon", "tyee"],
    "pink":       ["pink", "humpy", "humpback", "pink salmon"],
    "sockeye":    ["sockeye", "red", "red salmon", "blueback"],
    "halibut":    ["halibut", "butt", "flatty"],
    "lingcod":    ["lingcod", "ling", "ling cod"],
    "rockfish":   ["rockfish", "rock fish", "black bass", "black rockfish"],
    "yelloweye":  ["yelloweye", "yellow eye", "red snapper"],
    "dolly":      ["dolly", "dolly varden", "dolly varden trout"],
    "steelhead":  ["steelhead", "steelhead trout"],
    "rainbow":    ["rainbow", "rainbow trout", "bow"],
    "grayling":   ["grayling", "arctic grayling"],
    "pollock":    ["pollock", "walleye pollock"],
    "sablefish":  ["sablefish", "black cod", "sable"],
}

# Build lookup: every alias → canonical species
ALIAS_TO_SPECIES: dict[str, str] = {}
for canonical, aliases in SPECIES_ALIASES.items():
    for a in aliases:
        ALIAS_TO_SPECIES[a.lower()] = canonical


# ── Gear keywords ───────────────────────────────────────────────────────────
GEAR_KEYWORDS: list[str] = [
    "flasher", "green flasher", "red flasher", "purple flasher",
    "hoochie", "spoon", "herring", "cut plug", "plug cut",
    "jig", "buzz bomb", "dart", "kingfisher", "apex", "coyote spoon",
    "tommy gun", "crippled herring", "point wilson dart",
    "mooching", "trolling", "fly", "fly rod", "spinner",
    "kwikfish", "flatfish", "tomic", "tubby", "mega bait",
]


# ── Regex patterns (case-insensitive) ───────────────────────────────────────
_RE_DEPTH = re.compile(
    r"""(?ix)
    (?:at|down|depth|fishing\s+at|in)\s+(\d+)\s*(?:fathoms?|fm|ft|feet|')?
    |
    (\d+)\s*(?:fathoms?|fm)\b
    """
)

_RE_WEIGHT = re.compile(
    r"""(?ix)
    (\d+(?:\.\d+)?)\s*(?:
        pound|pounds|lb|lbs|\#
    )
    """
)

_RE_COUNT = re.compile(
    r"""(?ix)
    (?:
        (\d+)\s*(?:fish|caught|on\s+board|in\s+the\s+box|landed)
        |
        (?:a|one)\s+(?:nice\s+|big\s+|small\s+)?\b(?!of\b)
    )
    """
)

# Simpler fallback counts: bare numbers near "fish" or standalone small numbers
_RE_COUNT_LOOSE = re.compile(
    r"""(?ix)
    (\d+)\s*(?:fish|salmon|butt|ling|rockfish|pcs|pieces?)
    |
    (?:got|caught|landed|have)\s+(\d+)
    """
)


def fuzzy_match_species(text: str) -> tuple[str | None, float]:
    """Return (canonical_species, confidence_0_to_1) for best match in text.

    Confidence:
    - 1.0  = exact alias match
    - 0.9  = substring alias found
    - 0.7  = partial word overlap (e.g. user said "king" but said "chin" too)
    - 0.0  = no match
    """
    text_lower = text.lower()

    # 1) Exact alias match
    for alias, canonical in sorted(ALIAS_TO_SPECIES.items(),
                                   key=lambda x: -len(x[0])):
        if alias in text_lower:
            return canonical, 1.0

    # 2) Sub-word fuzzy (e.g. "chums" → "chum", "silvers" → "silver")
    # Check every token against alias stems
    tokens = set(re.findall(r"[a-z]+", text_lower))
    for alias, canonical in ALIAS_TO_SPECIES.items():
        alias_tokens = set(alias.split())
        # If any token from the alias appears as a prefix of any text token
        for at in alias_tokens:
            for t in tokens:
                if t.startswith(at) or at.startswith(t):
                    if len(at) >= 3 and len(t) >= 3:
                        return canonical, 0.85

    return None, 0.0


def extract_depth(text: str) -> int | None:
    """Extract depth in fathoms from catch-phrase text."""
    for m in _RE_DEPTH.finditer(text):
        val = m.group(1) or m.group(2)
        if val:
            return int(val)
    return None


def extract_weight(text: str) -> float | None:
    """Extract weight in pounds from catch-phrase text."""
    m = _RE_WEIGHT.search(text)
    if m:
        return float(m.group(1))
    return None


def extract_count(text: str) -> int | None:
    """Extract fish count from catch-phrase text.

    Tries strict pattern first, then loose pattern.
    """
    # Strict: "15 fish", "one chum"
    strict = _RE_COUNT.search(text)
    if strict:
        if strict.group(1):
            return int(strict.group(1))
        # "a" or "one" → 1
        return 1

    # Loose: "15 fish" variant, "got 6"
    loose = _RE_COUNT_LOOSE.search(text)
    if loose:
        return int(loose.group(1) or loose.group(2))

    return None


def extract_gear(text: str) -> str | None:
    """Extract gear/fishing-method from catch-phrase text."""
    text_lower = text.lower()
    for gear in sorted(GEAR_KEYWORDS, key=lambda g: -len(g)):
        if gear in text_lower:
            return gear
    return None


def parse_catch(text: str) -> dict:
    """Parse a natural-language catch report into a structured dict.

    Returns::
        {
            "species": "chum" | None,
            "count": 15,
            "weight_lb": 12.0 | None,
            "depth_fm": 35,
            "gear": "green flasher" | None,
            "confidence": 0.0 – 1.0,
            "raw": "<original text>",
            "timestamp_utc": "2026-07-18T..."
        }
    """
    report: dict = {
        "species": None,
        "count": None,
        "weight_lb": None,
        "depth_fm": None,
        "gear": None,
        "confidence": 0.0,
        "raw": text.strip(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }

    # Species (with fuzzy)
    species, species_conf = fuzzy_match_species(text)
    report["species"] = species
    report["confidence"] = species_conf

    # Depth
    depth = extract_depth(text)
    if depth is not None:
        report["depth_fm"] = depth
        report["confidence"] = max(report["confidence"], 0.9)

    # Weight
    weight = extract_weight(text)
    if weight is not None:
        report["weight_lb"] = weight
        report["confidence"] = max(report["confidence"], 0.9)

    # Count
    count = extract_count(text)
    if count is not None:
        report["count"] = count
        report["confidence"] = max(report["confidence"], 0.9)
    elif species is not None:
        # If species identified but no count given, default to 1
        report["count"] = 1
        report["confidence"] = max(report["confidence"], 0.6)

    # Gear
    gear = extract_gear(text)
    if gear is not None:
        report["gear"] = gear
        report["confidence"] = max(report["confidence"], 0.85)

    return report


# ── Speech recognition support ──────────────────────────────────────────────

def _get_recognizer():
    """Return a speech_recognition Recognizer (lazy import)."""
    try:
        import speech_recognition as sr  # type: ignore
    except ImportError:
        sys.exit(
            "speech_recognition not installed.\n"
            "  pip install SpeechRecognition\n"
            "  pip install pocketsphinx  # for offline mode"
        )
    return sr.Recognizer()


def record_and_parse(mic_timeout: int | None = None,
                     phrase_time_limit: int | None = 10,
                     prefer_offline: bool = True) -> dict:
    """Wake mic, transcribe, and parse a catch report.

    Args:
        mic_timeout: Seconds to wait for speech before giving up.
        phrase_time_limit: Max seconds to record after speech begins.
        prefer_offline: Try Sphinx first, fall back to Google.

    Returns:
        Parsed report dict (from parse_catch). If transcription fails,
        returns a dict with ``transcription_failed`` set.
    """
    import speech_recognition as sr  # type: ignore

    r = _get_recognizer()
    mic = sr.Microphone()

    with mic as source:
        # Quick ambient-noise calibration
        r.adjust_for_ambient_noise(source, duration=0.8)
        try:
            audio = r.listen(
                source,
                timeout=mic_timeout,
                phrase_time_limit=phrase_time_limit,
            )
        except sr.WaitTimeoutError:
            return {
                "species": None,
                "count": None,
                "weight_lb": None,
                "depth_fm": None,
                "gear": None,
                "confidence": 0.0,
                "raw": "",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "transcription_failed": True,
                "error": "No speech detected (timeout)",
            }

    # Try offline (Sphinx) first, then Google
    text: str | None = None
    engine_used: str = ""

    if prefer_offline:
        try:
            text = r.recognize_sphinx(audio)
            engine_used = "sphinx"
        except (sr.UnknownValueError, sr.RequestError):
            pass

    if text is None:
        try:
            text = r.recognize_google(audio)
            engine_used = "google"
        except sr.UnknownValueError:
            return {
                "species": None,
                "count": None,
                "weight_lb": None,
                "depth_fm": None,
                "gear": None,
                "confidence": 0.0,
                "raw": "",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "transcription_failed": True,
                "error": "Could not understand audio",
            }
        except sr.RequestError as e:
            return {
                "species": None,
                "count": None,
                "weight_lb": None,
                "depth_fm": None,
                "gear": None,
                "confidence": 0.0,
                "raw": "",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "transcription_failed": True,
                "error": f"STT service error: {e}",
            }

    report = parse_catch(text)
    report["engine"] = engine_used
    report["transcribed"] = text
    return report


# ── Log persistence ─────────────────────────────────────────────────────────

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        ".voice_catch_log.jsonl")


def append_report(report: dict, path: str | None = None) -> str:
    """Append a report dict as a JSON line to the log file.

    Returns the absolute path written to.
    """
    target = path or LOG_PATH
    with open(target, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(report, ensure_ascii=False) + "\n")
    return os.path.abspath(target)


# ── CLI ─────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Voice Catch Report System – "
                    "parse spoken or typed catch reports.",
    )
    sub = parser.add_subparsers(dest="command")

    # ── record ──
    rec = sub.add_parser("record", help="Listen via microphone and parse.")
    rec.add_argument("--timeout", type=int, default=None,
                     help="Seconds to wait for speech (default: no limit)")
    rec.add_argument("--phrase-limit", type=int, default=10,
                     help="Max recording seconds (default: 10)")
    rec.add_argument("--online", action="store_true",
                     help="Prefer Google STT over offline Sphinx")

    # ── positional text ──
    sub.add_parser("text", help="Parse a text catch report (positional arg).")
    parser.add_argument("text_input", nargs="?", default=None,
                        help="Catch report text to parse (quoted)")

    args = parser.parse_args(argv)

    if args.command == "record":
        print("🎤 Listening for catch report...")
        report = record_and_parse(
            mic_timeout=args.timeout,
            phrase_time_limit=args.phrase_limit,
            prefer_offline=not args.online,
        )
        if report.get("transcription_failed"):
            print(f"❌ {report.get('error', 'Transcription failed')}")
            return
        trans = report.get("transcribed", report["raw"])
        print(f"🗣  Heard: \"{trans}\"")
        print(f"   Engine: {report.get('engine', '?')}")

    elif args.text_input:
        report = parse_catch(args.text_input)
        print(f"📝 Parsed: \"{args.text_input}\"")
    else:
        parser.print_help()
        return

    # Display
    print(f"   Species : {report.get('species') or '(unknown)'}")
    print(f"   Count   : {report.get('count', '?')}")
    if report.get("weight_lb"):
        print(f"   Weight  : {report['weight_lb']} lb")
    if report.get("depth_fm"):
        print(f"   Depth   : {report['depth_fm']} fm")
    if report.get("gear"):
        print(f"   Gear    : {report['gear']}")
    print(f"   Conf    : {report['confidence']:.0%}")

    # Persist
    log_path = append_report(report)
    print(f"💾 Appended to {log_path}")


if __name__ == "__main__":
    main()
