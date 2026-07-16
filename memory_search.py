#!/usr/bin/env python3
"""
memory_search.py — Semantic memory search for the boat's internal monologue.

Uses nomic-embed-text via Ollama to embed observations and find semantically
similar past observations. Enables the monologue to connect current conditions
with historical patterns.

Key improvements:
  - batch_index(days=7): multi-day batch indexing saved as a named index
  - find_similar_to_current(sensor_readings): find historical monologue entries
    similar to current sensor conditions
  - find_similar_observations(sensor_readings): direct numeric comparison of
    observation data for precise condition matching

Usage:
    from memory_search import MemorySearch

    ms = MemorySearch()
    ms.index_recent()                    # Index last 24h of observations
    results = ms.query("gear depth contour crossing at 48 fm")

    ms.batch_index(7)                    # Index last 7 days, save to disk

    similar = ms.find_similar_to_current({
        "depth_fm": 48.0,
        "bottom_type": "hard",
        "sog": 3.5,
    })

    # The monologue can now say: "This feels like the conditions last Tuesday
    # when we saw the same bottom transition pattern."
"""

from __future__ import annotations

import json
import logging
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import urllib.request

from config import WORKSPACE

log = logging.getLogger("tzpro.memory_search")

# ── Paths ──────────────────────────────────────────────────────────
MONOLOGUE_DIR = WORKSPACE / "memory" / "monologue"
OBSERVATIONS_DIR = WORKSPACE / "memory" / "observations"
INDEX_DIR = WORKSPACE / "memory" / "index"
INDEX_DIR.mkdir(parents=True, exist_ok=True)

# ── Ollama Config ──────────────────────────────────────────────────
OLLAMA_EMBED_URL = "http://127.0.0.1:11434/api/embed"
EMBED_MODEL = "nomic-embed-text"

# ── Similarity Config ──────────────────────────────────────────────
# Feature weights for numeric condition comparison in find_similar_observations
FEATURE_WEIGHTS = {
    "depth_fm": 1.0,
    "sog": 0.5,
    "fish_density": 0.4,
    "fish_intensity": 0.3,
}


def embed(text: str) -> Optional[list[float]]:
    """Embed a text string using nomic-embed-text via Ollama."""
    payload = json.dumps({
        "model": EMBED_MODEL,
        "input": text,
    }).encode()

    req = urllib.request.Request(
        OLLAMA_EMBED_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            result = json.loads(r.read())
            embeddings = result.get("embeddings", [])
            if embeddings:
                return embeddings[0]
    except Exception as e:
        log.debug("Embed: %s", e)

    return None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    a_arr = np.array(a, dtype=np.float64)
    b_arr = np.array(b, dtype=np.float64)
    norm = np.linalg.norm(a_arr) * np.linalg.norm(b_arr)
    if norm == 0:
        return 0.0
    return float(np.dot(a_arr, b_arr) / norm)


def _load_jsonl_entries(directory: Path, hours: float) -> list[dict]:
    """Load all JSONL entries from `directory` within the last `hours`."""
    entries = []
    now = time.time()

    for f in sorted(directory.glob("*.jsonl"), reverse=True):
        with open(f) as fh:
            for line in fh:
                try:
                    entry = json.loads(line)
                    ts = datetime.fromisoformat(entry["ts"])
                    if (now - ts.timestamp()) < hours * 3600:
                        entries.append(entry)
                except (json.JSONDecodeError, ValueError, KeyError):
                    continue

    return entries


# ───────────────────────────────────────────────────────────────────
#  Sensor-text helpers
# ───────────────────────────────────────────────────────────────────

def _get(d: dict, *keys, default=None):
    """Safely traverse nested dicts."""
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k)
        else:
            return default
    return d if d is not None else default


def _sensors_to_text(sensor_readings: dict) -> str:
    """Convert sensor readings dict to a searchable text description.

    Accepts both flat dicts (depth_fm=48.0) and nested structures
    matching the observation format (sounder.depth_fm).
    """
    parts = []

    # --- Position ---
    lat = _get(sensor_readings, "location", "lat") or _get(sensor_readings, "lat")
    lon = _get(sensor_readings, "location", "lon") or _get(sensor_readings, "lon")
    if lat is not None:
        parts.append(f"position {lat:.5f}, {lon:.5f}" if lon else f"latitude {lat:.5f}")

    # --- Vessel speed ---
    sog = _get(sensor_readings, "vessel", "sog") or _get(sensor_readings, "sog")
    if sog is not None:
        parts.append(f"speed {sog:.1f} knots")

    # --- Depth ---
    depth = _get(sensor_readings, "sounder", "depth_fm") or _get(sensor_readings, "depth_fm")
    if depth is not None:
        parts.append(f"depth {depth} fathoms")

    # --- Bottom type ---
    bottom = _get(sensor_readings, "sounder", "bottom_type") or _get(sensor_readings, "bottom_type")
    if bottom:
        parts.append(f"bottom type {bottom}")

    # --- Confidence ---
    conf = _get(sensor_readings, "sounder", "confidence") or _get(sensor_readings, "confidence")
    if conf:
        parts.append(f"confidence {conf}")

    # --- Fish returns ---
    fish = _get(sensor_readings, "sounder", "fish_returns") or _get(sensor_readings, "fish_returns")
    if isinstance(fish, dict):
        density = fish.get("density_per_100kpx")
        if density is not None:
            parts.append(f"fish density {density:.0f} per 100kpx")
        intensity = fish.get("avg_intensity")
        if intensity is not None:
            parts.append(f"fish return intensity {intensity:.0f}")
        dist = fish.get("distribution")
        if dist:
            parts.append(f"fish distribution {dist}")

    # --- Thermoclines ---
    thermos = _get(sensor_readings, "sounder", "thermoclines") or _get(sensor_readings, "thermoclines")
    if thermos and len(thermos) > 0:
        parts.append(f"{len(thermos)} thermocline(s)")

    # --- Gear clearance ---
    gear = _get(sensor_readings, "clearance") or _get(sensor_readings, "gear_clearance")
    if gear is not None:
        parts.append(f"gear clearance {gear} fathoms")

    # --- Observation summary (monologue envelop) ---
    obs_summary = sensor_readings.get("observation_summary")
    if isinstance(obs_summary, dict):
        d = obs_summary.get("depth_fm")
        if d is not None:
            parts.append(f"depth {d} fathoms")
        g = obs_summary.get("gear_clearance")
        if g is not None:
            parts.append(f"gear clearance {g} fathoms")

    return "; ".join(parts)


def _sensor_distance(a: dict, b: dict) -> float:
    """Weighted Euclidean distance between two sensor readings.

    Lower = more similar. Returns inf if key features are missing.
    """
    total_weight = 0.0
    weighted_sum = 0.0

    def _get_val(d, *keys, default=None):
        v = _get(d, *keys)
        return v if v is not None else default

    for feature, weight in FEATURE_WEIGHTS.items():
        if feature == "depth_fm":
            va = _get_val(a, "sounder", "depth_fm") or _get_val(a, "depth_fm") or _get_val(a, "observation_summary", "depth_fm")
            vb = _get_val(b, "sounder", "depth_fm") or _get_val(b, "depth_fm") or _get_val(b, "observation_summary", "depth_fm")
        elif feature == "sog":
            va = _get_val(a, "vessel", "sog") or _get_val(a, "sog")
            vb = _get_val(b, "vessel", "sog") or _get_val(b, "sog")
        elif feature == "fish_density":
            va = _get_val(a, "sounder", "fish_returns", "density_per_100kpx") or _get_val(a, "fish_returns", "density_per_100kpx")
            vb = _get_val(b, "sounder", "fish_returns", "density_per_100kpx") or _get_val(b, "fish_returns", "density_per_100kpx")
        elif feature == "fish_intensity":
            va = _get_val(a, "sounder", "fish_returns", "avg_intensity") or _get_val(a, "fish_returns", "avg_intensity")
            vb = _get_val(b, "sounder", "fish_returns", "avg_intensity") or _get_val(b, "fish_returns", "avg_intensity")
        else:
            continue

        if va is not None and vb is not None:
            diff = float(va) - float(vb)
            weighted_sum += weight * diff * diff
            total_weight += weight

    if total_weight == 0:
        return float("inf")

    return math.sqrt(weighted_sum / total_weight)


# ───────────────────────────────────────────────────────────────────
#  MemorySearch class
# ───────────────────────────────────────────────────────────────────

class MemorySearch:
    """Semantic search over monologue observations.

    Supports:
      - Loading & indexing monologue entries by recency window
      - Batch indexing (multi-day) with named, persistent index files
      - Semantic search via cosine similarity on text embeddings
      - Direct numeric comparison of sensor observations
      - Finding similar conditions from current sensor readings
    """

    def __init__(self):
        self.entries: list[dict] = []
        self.embeddings: list[list[float]] = []

    # ── Load helpers ───────────────────────────────────────────────

    def load_entries(self, hours: int = 24) -> int:
        """Load monologue entries from the last N hours."""
        self.entries = _load_jsonl_entries(MONOLOGUE_DIR, hours)
        log.debug("Loaded %d monologue entries from last %dh", len(self.entries), hours)
        return len(self.entries)

    def load_observations(self, hours: int = 24) -> int:
        """Load observation entries from the last N hours."""
        obs = _load_jsonl_entries(OBSERVATIONS_DIR, hours)
        # Store separately for numeric comparison
        self._observations = obs
        log.debug("Loaded %d observation entries from last %dh", len(obs), hours)
        return len(obs)

    # ── Indexing ───────────────────────────────────────────────────

    def index(self, entries: Optional[list[dict]] = None) -> int:
        """Embed all loaded entries for search."""
        if entries is not None:
            self.entries = entries

        self.embeddings = []
        for i, entry in enumerate(self.entries):
            text = f"{entry.get('category', '')}: {entry.get('text', '')}"
            vec = embed(text)
            if vec:
                self.embeddings.append(vec)
            if (i + 1) % 10 == 0:
                log.debug("Indexed %d/%d", i + 1, len(self.entries))

        return len(self.embeddings)

    def index_recent(self, hours: int = 24) -> int:
        """Load and index recent entries in one step."""
        self.load_entries(hours)
        return self.index()

    def batch_index(self, days: int = 7, name: Optional[str] = None) -> int:
        """Load and index monologue entries from the last *days*, then save.

        This is the primary way to build a persistent, searchable index
        for condition matching across multiple days.

        Args:
            days: Number of days of history to index.
            name:  Optional index name.  Defaults to ``batch_{days}d_{YYYYMMDD}``.

        Returns:
            Number of entries indexed.
        """
        self.load_entries(hours=days * 24)
        n = self.index()

        if n > 0:
            index_name = name or f"batch_{days}d_{datetime.now().strftime('%Y%m%d')}"
            self.save_index(index_name)
            log.info("Batch index saved: %s (%d entries)", index_name, n)
        else:
            log.warning("No entries found for batch_index(days=%d)", days)

        return n

    # ── Save / Load indexes ────────────────────────────────────────

    def save_index(self, name: str = "default") -> None:
        """Cache index to disk for fast reload."""
        path = INDEX_DIR / f"{name}.npz"
        np.savez_compressed(
            path,
            embeddings=np.array(self.embeddings, dtype=np.float32),
            entries=np.array([json.dumps(e) for e in self.entries]),
        )
        log.debug("Saved index: %s (%d entries)", path, len(self.entries))

    def load_index(self, name: str = "default") -> bool:
        """Load a cached index from disk."""
        path = INDEX_DIR / f"{name}.npz"
        if not path.exists():
            return False

        data = np.load(path, allow_pickle=True)
        self.embeddings = data["embeddings"].tolist()
        self.entries = [json.loads(e) for e in data["entries"]]
        log.debug("Loaded index: %s (%d entries)", path, len(self.entries))
        return True

    def load_latest_batch_index(self) -> bool:
        """Load the most recently saved batch index (by filename sort)."""
        candidates = sorted(INDEX_DIR.glob("batch_*.npz"), reverse=True)
        if candidates:
            return self.load_index(candidates[0].stem)
        log.debug("No batch indexes found in %s", INDEX_DIR)
        return False

    # ── Semantic search ────────────────────────────────────────────

    def query(self, query_text: str, top_k: int = 5) -> list[dict]:
        """Search for entries similar to query_text.

        Args:
            query_text: Natural-language query string.
            top_k: Number of results to return.

        Returns:
            List of dicts, each with keys ``similarity``, ``entry``,
            sorted descending by similarity.
        """
        query_vec = embed(query_text)
        if query_vec is None:
            return []

        if not self.embeddings:
            return []

        # Compute similarities
        scores = []
        for i, entry_vec in enumerate(self.embeddings):
            sim = cosine_similarity(query_vec, entry_vec)
            scores.append((sim, i))

        # Sort by similarity, descending
        scores.sort(key=lambda x: -x[0])

        results = []
        for sim, idx in scores[:top_k]:
            results.append({
                "similarity": round(sim, 3),
                "entry": self.entries[idx],
            })

        return results

    # ── Condition matching ─────────────────────────────────────────

    def find_similar_to_current(self, sensor_readings: dict,
                                top_k: int = 5,
                                auto_load: bool = True) -> list[dict]:
        """Find historical monologue entries semantically similar to current
        sensor conditions.

        Converts the sensor readings to a text description and queries the
        monologue embedding index.  If no index is loaded and *auto_load* is
        True, the most recent batch index is loaded automatically.

        Args:
            sensor_readings: Dict of current sensor values (flat or nested
                             in the standard observation schema).  See
                             ``_sensors_to_text`` for supported fields.
            top_k: Number of results to return.
            auto_load: Whether to auto-load the latest batch index when
                       no embeddings are cached.

        Returns:
            List of result dicts (same format as ``query``).
        """
        if auto_load and not self.embeddings:
            self.load_latest_batch_index()

        query = _sensors_to_text(sensor_readings)

        if not query:
            log.debug("find_similar_to_current: no query text could be built "
                      "from %s", sensor_readings)
            return []

        log.debug("Condition search query: %s", query)
        return self.query(query, top_k=top_k)

    def find_similar_observations(self, sensor_readings: dict,
                                  top_k: int = 5,
                                  hours: int = 72,
                                  auto_load: bool = True) -> list[dict]:
        """Find the most numerically similar *observations* to current
        sensor readings.

        This compares weighted numeric features (depth, speed, fish density,
        etc.) rather than using text embeddings.  Observations are loaded
        from the observations JSONL files.

        Args:
            sensor_readings: Current sensor reading dict.
            top_k: Number of nearest neighbours to return.
            hours: How far back to search (default 72h).
            auto_load: Reload non-indexed observations on each call.

        Returns:
            List of dicts, each with keys ``similarity`` (inverted distance,
            higher = more similar), ``distance``, and ``entry``.
        """
        if auto_load or not hasattr(self, "_observations"):
            self.load_observations(hours)

        if not self._observations:
            return []

        scored = []
        for obs in self._observations:
            d = _sensor_distance(sensor_readings, obs)
            if d == float("inf"):
                continue
            # Invert distance so higher = better, capped at 1.0
            sim = round(1.0 / (1.0 + d), 3)
            scored.append((sim, d, obs))

        scored.sort(key=lambda x: -x[0])

        return [
            {"similarity": sim, "distance": round(d, 3), "entry": obs}
            for sim, d, obs in scored[:top_k]
        ]


# ───────────────────────────────────────────────────────────────────
#  CLI entry-point
# ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    ms = MemorySearch()

    if "--rebuild" in sys.argv:
        n = ms.index_recent(24)
        ms.save_index()
        print(f"Indexed {n} entries from the last 24h")

    elif "--batch" in sys.argv:
        days = 7
        for i, a in enumerate(sys.argv):
            if a == "--batch" and i + 1 < len(sys.argv):
                try:
                    days = int(sys.argv[i + 1])
                except ValueError:
                    pass
        n = ms.batch_index(days)
        print(f"Batch indexed {n} entries from the last {days}d")

    elif "--query" in sys.argv:
        idx = sys.argv.index("--query")
        if idx + 1 < len(sys.argv):
            query = " ".join(sys.argv[idx + 1:])

            if not ms.load_index():
                print("No cached index found, rebuilding...")
                ms.index_recent(24)
                ms.save_index()

            results = ms.query(query)
            print(f"Search: \"{query}\"")
            print()
            for r in results:
                entry = r["entry"]
                print(f"  [{r['similarity']:.2f}] {entry.get('ts', '?')[:19]} | {entry.get('text', '')[:120]}")

    elif "--similar" in sys.argv:
        idx = sys.argv.index("--similar")
        payload = " ".join(sys.argv[idx + 1:])
        try:
            sensors = json.loads(payload)
        except json.JSONDecodeError:
            print("--similar requires a JSON object string")
            sys.exit(1)

        results = ms.find_similar_to_current(sensors, auto_load=True)
        print(f"Conditions: {_sensors_to_text(sensors)}")
        print()
        if not results:
            print("No similar entries found.")
        else:
            for r in results:
                entry = r["entry"]
                print(f"  [{r['similarity']:.2f}] {entry.get('ts', '?')[:19]} | {entry.get('category', '')} | {entry.get('text', '')[:120]}")

    else:
        print("Usage:")
        print("  python memory_search.py --rebuild                  # Build/update index (24h)")
        print("  python memory_search.py --batch [days]            # Batch index last N days")
        print("  python memory_search.py --query 'text'            # Semantic search")
        print("  python memory_search.py --similar '{json}'        # Find conditions similar to sensor JSON")
