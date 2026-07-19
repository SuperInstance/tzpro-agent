"""cascade/ollama_client.py — local vision inference, stdlib only.

Model-degraded mode (constraint 5): Ollama down returns None — the caller
queues quietly. Never raise on inference failure; never invent analysis.
"""
from __future__ import annotations

import base64
import json
import logging
import urllib.request
import urllib.error
from pathlib import Path

from . import config

log = logging.getLogger("cascade.ollama")


def vision_available() -> bool:
    try:
        with urllib.request.urlopen(f"{config.OLLAMA_URL}/api/tags", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def model_present(model: str) -> bool:
    try:
        with urllib.request.urlopen(f"{config.OLLAMA_URL}/api/tags", timeout=3) as r:
            tags = json.loads(r.read().decode())
        names = {m.get("name", "") for m in tags.get("models", [])}
        return model in names or model.split(":")[0] in {n.split(":")[0] for n in names}
    except Exception:
        return False


def vision_prompt(image_path: Path, prompt: str, model: str,
                  max_tokens: int, fallback_model: str | None = None) -> str | None:
    """One vision inference. Returns model text, or None on any failure.

    Uses /api/chat (not /api/generate): gemma4 returns empty completions on
    /api/generate with images — verified against the live instance 2026-07-19.
    `think: False` keeps racehorses fast (no chain-of-thought burn)."""
    chosen = model if model_present(model) else (fallback_model or model)
    if not model_present(chosen):
        log.warning("no usable vision model (%s, fallback %s) — skipping", model, fallback_model)
        return None
    try:
        b64 = base64.b64encode(image_path.read_bytes()).decode()
        body = json.dumps({
            "model": chosen,
            "messages": [{"role": "user", "content": prompt, "images": [b64]}],
            "stream": False,
            "think": False,
            "options": {"num_predict": max_tokens, "temperature": 0.2},
        }).encode()
        req = urllib.request.Request(
            f"{config.OLLAMA_URL}/api/chat", data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=config.INFER_TIMEOUT_S) as r:
            resp = json.loads(r.read().decode())
        return ((resp.get("message") or {}).get("content") or "").strip() or None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        log.warning("inference failed for %s: %s", image_path.name, e)
        return None


def extract_json(text: str) -> dict | None:
    """Defensive JSON extraction from model prose."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
