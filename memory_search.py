#!/usr/bin/env python3
"""
memory_search.py — Semantic memory search for the boat's internal monologue.

Uses nomic-embed-text via Ollama to embed observations and find semantically
similar past observations. Enables the monologue to connect current conditions
with historical patterns.

Usage:
    from memory_search import MemorySearch
    
    ms = MemorySearch()
    ms.index_recent()              # Index last 24h of observations
    results = ms.query("gear depth contour crossing at 48 fm")
    
    # The monologue can now say: "This feels like the conditions last Tuesday
    # when we saw the same bottom transition pattern."
"""

from __future__ import annotations

import json
import logging
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
INDEX_DIR = WORKSPACE / "memory" / "index"
INDEX_DIR.mkdir(parents=True, exist_ok=True)

# ── Ollama Config ──────────────────────────────────────────────────
OLLAMA_EMBED_URL = "http://127.0.0.1:11434/api/embed"
EMBED_MODEL = "nomic-embed-text"


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
    a_arr = np.array(a)
    b_arr = np.array(b)
    return float(np.dot(a_arr, b_arr) / (np.linalg.norm(a_arr) * np.linalg.norm(b_arr)))


class MemorySearch:
    """Semantic search over monologue observations."""
    
    def __init__(self):
        self.entries: list[dict] = []
        self.embeddings: list[list[float]] = []
    
    def load_entries(self, hours: int = 24) -> int:
        """Load monologue entries from the last N hours."""
        self.entries = []
        now = time.time()
        
        for f in sorted(MONOLOGUE_DIR.glob("*.jsonl"), reverse=True):
            with open(f) as fh:
                for line in fh:
                    try:
                        entry = json.loads(line)
                        ts = datetime.fromisoformat(entry["ts"])
                        if (now - ts.timestamp()) < hours * 3600:
                            self.entries.append(entry)
                    except (json.JSONDecodeError, ValueError, KeyError):
                        continue
        
        log.debug("Loaded %d entries from last %dh", len(self.entries), hours)
        return len(self.entries)
    
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
    
    def query(self, query_text: str, top_k: int = 5) -> list[dict]:
        """Search for entries similar to query_text.
        
        Returns sorted list of (similarity, entry) dicts.
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


if __name__ == "__main__":
    import sys
    
    ms = MemorySearch()
    
    if "--rebuild" in sys.argv:
        n = ms.index_recent(24)
        ms.save_index()
        print(f"Indexed {n} entries from the last 24h")
    
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
    
    else:
        print("Usage:")
        print("  python memory_search.py --rebuild          # Build/update index")
        print("  python memory_search.py --query 'text'     # Search")
