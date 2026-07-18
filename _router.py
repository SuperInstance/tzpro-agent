"""
Agent Task Router — maps task types to agent models with baton handshake locks.

Lock files live in .handshake/ relative to this module's directory.
Each lock is a JSON blob with agent identity, timestamp, task type, and duration estimate.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
HANDSHAKE_DIR = _HERE / ".handshake"

# ── Router mapping ──────────────────────────────────────────────────────────

ROUTER: dict[str, str] = {
    "creative_vision": "seed2",
    "synthesis":       "hermes3",
    "deduction":       "nemotron",
    "premium":         "v4pro",
    "review":          "v4pro",
    "system":          "flash",
}

# Estimated token budgets per model (conservative defaults)
_MODEL_BUDGETS: dict[str, int] = {
    "seed2":   4096,
    "hermes3": 8192,
    "nemotron": 8192,
    "v4pro":   16384,
    "flash":   2048,
}

# Confidence levels for exact matches, fallback, and unknown
_CONFIDENCE_EXACT    = 0.95
_CONFIDENCE_FALLBACK = 0.50
_CONFIDENCE_UNKNOWN  = 0.15


def route_task(task_type: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve a task type to a model, confidence, and budget.

    Returns a dict with keys:
        model            – agent model name
        confidence       – 0.0–1.0
        estimated_budget – token budget suggestion
        task_type        – echo of input
        fallback         – True when the exact task_type was not in ROUTER
    """
    ctx = context or {}
    model = ROUTER.get(task_type)

    if model is not None:
        confidence = _CONFIDENCE_EXACT
        fallback = False
    else:
        # Best-effort fallback — try fuzzy substring match
        for key, val in ROUTER.items():
            if task_type in key or key in task_type:
                model = val
                confidence = _CONFIDENCE_FALLBACK
                fallback = True
                break
        else:
            model = "flash"
            confidence = _CONFIDENCE_UNKNOWN
            fallback = True

    # Honour explicit hint from context
    if "preferred_model" in ctx and ctx["preferred_model"] in _MODEL_BUDGETS:
        model = ctx["preferred_model"]
        confidence = 0.80
        fallback = True

    budget = _MODEL_BUDGETS.get(model, 2048)
    if "budget_hint" in ctx:
        try:
            budget = int(ctx["budget_hint"])
        except (ValueError, TypeError):
            pass

    return {
        "model": model,
        "confidence": round(confidence, 3),
        "estimated_budget": budget,
        "task_type": task_type,
        "fallback": fallback,
    }


# ── Baton handshake (filesystem locks) ─────────────────────────────────────

def _ensure_handshake_dir() -> None:
    HANDSHAKE_DIR.mkdir(parents=True, exist_ok=True)


def _lock_path(task_name: str) -> Path:
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in task_name).strip("_")
    if not safe_name:
        safe_name = "unnamed"
    return HANDSHAKE_DIR / f"{safe_name}.lock"


def acquire_lock(task_name: str, timeout_s: float = 30) -> bool:
    """Attempt to acquire a baton lock for *task_name*.

    Returns True within *timeout_s* seconds, or False if another agent holds the lock.
    """
    _ensure_handshake_dir()
    lockfile = _lock_path(task_name)
    deadline = time.monotonic() + timeout_s

    while True:
        try:
            # Create lock exclusively — atomic on POSIX + Windows via os.open
            fd = os.open(str(lockfile), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            # Lock exists — check whether it's stale
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            _stale_check(lockfile)
            time.sleep(min(0.25, remaining))
            continue

        # Write lock payload
        payload = {
            "agent_id":  str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task_type": task_name,
            "expected_duration_s": timeout_s,
        }
        try:
            os.write(fd, json.dumps(payload, indent=2).encode())
        finally:
            os.close(fd)
        return True


def release_lock(task_name: str) -> None:
    """Release a previously acquired baton lock."""
    lockfile = _lock_path(task_name)
    try:
        lockfile.unlink(missing_ok=True)
    except OSError:
        pass


def wait_for_release(task_name: str, timeout_s: float = 120) -> bool:
    """Block until another agent releases the lock on *task_name*.

    Returns True when the lock was released, False on timeout.
    """
    lockfile = _lock_path(task_name)
    deadline = time.monotonic() + timeout_s

    while time.monotonic() < deadline:
        if not lockfile.exists():
            return True
        _stale_check(lockfile)
        time.sleep(0.25)

    return not lockfile.exists()


def list_active_locks() -> list[dict[str, Any]]:
    """Return metadata for every active lock in the handshake directory."""
    _ensure_handshake_dir()
    locks: list[dict[str, Any]] = []
    for entry in sorted(HANDSHAKE_DIR.glob("*.lock")):
        try:
            data = json.loads(entry.read_text(encoding="utf-8"))
            data["lock_file"] = str(entry)
            locks.append(data)
        except (json.JSONDecodeError, OSError):
            # Corrupt lock — still report it
            locks.append({"lock_file": str(entry), "error": "unreadable"})
    return locks


def _stale_check(lockfile: Path, max_age_s: float = 300) -> None:
    """Remove a lock file if it is older than *max_age_s*."""
    try:
        age = time.time() - lockfile.stat().st_mtime
        if age > max_age_s:
            lockfile.unlink(missing_ok=True)
    except OSError:
        pass


# ── CLI (optional) ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python _router.py <task_type>  or  --locks / --acquire=<name> / --release=<name>")
        sys.exit(0)

    arg = sys.argv[1]
    if arg == "--locks":
        for lock in list_active_locks():
            print(json.dumps(lock, indent=2))
    elif arg.startswith("--acquire="):
        name = arg.split("=", 1)[1]
        ok = acquire_lock(name)
        print("ACQUIRED" if ok else "BUSY")
    elif arg.startswith("--release="):
        name = arg.split("=", 1)[1]
        release_lock(name)
        print("RELEASED")
    else:
        result = route_task(arg)
        print(json.dumps(result, indent=2))
