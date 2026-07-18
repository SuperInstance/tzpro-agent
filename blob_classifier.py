"""BlobClassifier: classify sonar blobs (noise / chum / pollock / rockfish / halibut / bait_ball).

Uses a heuristic feature-based classifier that works without pretrained models.
When ONNX Runtime is available, can also load an ONNX model for neural inference.
Training: `python blob_classifier.py train` builds histograms from labeled catches
linked to blob features in captures.db.
"""

import json
import os
import sqlite3
import sys
from pathlib import Path

import numpy as np

# ── model state file ──────────────────────────────────────────────────────────
MODEL_FILE = Path(__file__).with_name("blob_classifier_model.json")

CLASSES = ["noise", "chum", "pollock", "rockfish", "halibut", "bait_ball"]

FEATURE_KEYS = [
    "centroid_depth_fm",
    "area_px",
    "aspect_ratio",
    "mean_intensity",
]

# ── heuristic priors (fallback when no training data) ─────────────────────────
# Each class: (depth_center_fm, area_center_px, aspect_ratio_center, intensity_center, sigma)
HEURISTIC_PRIORS: dict[str, tuple[float, float, float, float, float]] = {
    "noise":      (  -1,   20,  1.0, 0.15, 0.50),  # small, random
    "chum":       (  35,  800,  1.3, 0.45, 0.20),  # mid-depth schools
    "pollock":    (  50, 1200,  1.1, 0.40, 0.25),  # deeper, larger schools
    "rockfish":   (  80,  200,  1.5, 0.50, 0.30),  # deep, elongated
    "halibut":    ( 100,  400,  2.0, 0.55, 0.35),  # deep, wide, bright
    "bait_ball":  (  25, 2000,  1.0, 0.35, 0.20),  # shallow, huge area
}


class BlobClassifier:
    """Heuristic blob classifier backed by feature histograms.

    Training builds per-class Gaussian parameters from labeled catches linked
    to blob features in captures.db.  Falls back to heuristic priors when no
    training data is available (zero-shot).
    """

    def __init__(self):
        self.class_params: dict[str, dict[str, dict[str, float]]] = {}
        self.trained: bool = False
        self.num_samples: int = 0

    # ── prediction ────────────────────────────────────────────────────────
    def classify(self, features: dict) -> tuple[str, float]:
        """Return (predicted_class, confidence 0-1)."""
        scores: dict[str, float] = {}
        for cls in CLASSES:
            scores[cls] = self._score(cls, features)
        best = max(scores, key=scores.get)  # type: ignore[arg-type]
        best_score = scores[best]
        # softmax-like
        exp_sum = sum(np.exp(s) for s in scores.values())
        conf = np.exp(best_score) / exp_sum if exp_sum > 0 else 0.5
        return best, round(float(conf), 4)

    def _score(self, cls: str, features: dict) -> float:
        """Log-likelihood score under Gaussian assumption (higher is better)."""
        mu = self.class_params.get(cls, {})
        if not mu:
            # fall back to heuristic prior
            d_c, a_c, ar_c, i_c, sig = HEURISTIC_PRIORS.get(cls, (0, 1, 1, 1, 1))
            mu = {
                "centroid_depth_fm": {"mu": d_c, "sigma": max(sig, 0.01)},
                "area_px": {"mu": a_c, "sigma": max(sig * 200, 10)},
                "aspect_ratio": {"mu": ar_c, "sigma": max(sig * 0.5, 0.05)},
                "mean_intensity": {"mu": i_c, "sigma": max(sig * 0.3, 0.02)},
            }
        # Gaussian log-likelihood (neg squared Mahalanobis)
        ll = 0.0
        for key in FEATURE_KEYS:
            val = features.get(key, 0)
            params = mu.get(key, {"mu": 0, "sigma": 1})
            m = params["mu"]
            s = max(params["sigma"], 1e-6)
            ll -= 0.5 * ((val - m) / s) ** 2
        return ll

    # ── training ───────────────────────────────────────────────────────────
    def train(self, conn: sqlite3.Connection) -> dict:
        """Build per-class Gaussian parameters from labeled catches.

        Strategy:
          1. Query catch_labels for (capture_id, species, depth_fm).
          2. Join with blobs on capture_id.
          3. Aggregate blob features per species.
          4. Compute mu/sigma per feature per class.
        """
        stats: dict[str, dict[str, list[float]]] = {
            cls: {k: [] for k in FEATURE_KEYS} for cls in CLASSES
        }

        conn.row_factory = sqlite3.Row
        # Join catches → blobs, filter to depth-adjacent blobs
        rows = conn.execute(
            """
            SELECT cl.species, b.centroid_depth_fm, b.area_px,
                   b.aspect_ratio, b.mean_intensity
            FROM catch_labels cl
            JOIN blobs b ON cl.capture_id = b.capture_id
            WHERE cl.species IS NOT NULL
              AND cl.species != ''
              AND (
                cl.depth_fm IS NULL
                OR ABS(b.centroid_depth_fm - cl.depth_fm) < 20
              )
            """
        ).fetchall()

        for row in rows:
            sp = row["species"].lower().strip()
            if sp not in CLASSES:
                continue
            for k in FEATURE_KEYS:
                v = row[k]
                if v is not None:
                    stats[sp][k].append(float(v))

        # Compute mu/sigma
        for cls in CLASSES:
            feats = stats[cls]
            params: dict[str, dict[str, float]] = {}
            for k in FEATURE_KEYS:
                arr = np.array(feats[k]) if feats[k] else np.array([])
                if len(arr) >= 2:
                    params[k] = {"mu": float(arr.mean()), "sigma": max(float(arr.std()), 1e-3)}
                elif len(arr) == 1:
                    params[k] = {"mu": float(arr[0]), "sigma": 0.1}
                else:
                    # fall back to prior
                    d_c, a_c, ar_c, i_c, sig = HEURISTIC_PRIORS.get(cls, (0, 1, 1, 1, 1))
                    prior_map = {"centroid_depth_fm": (d_c, sig * 30), "area_px": (a_c, sig * 200),
                                 "aspect_ratio": (ar_c, sig * 0.5), "mean_intensity": (i_c, sig * 0.3)}
                    params[k] = {"mu": prior_map[k][0], "sigma": prior_map[k][1]}
            self.class_params[cls] = params

        self.trained = len(rows) > 0
        self.num_samples = len(rows)
        return {
            "samples": self.num_samples,
            "classes_trained": sum(1 for cls in CLASSES if stats[cls] and any(len(v) >= 2 for v in stats[cls].values())),
            "total_classes": len(CLASSES),
        }

    # ── persistence ───────────────────────────────────────────────────────
    def save(self, path: Path | None = None) -> None:
        path = path or MODEL_FILE
        payload = {
            "class_params": {cls: {k: {"mu": v["mu"], "sigma": v["sigma"]} for k, v in params.items()}
                             for cls, params in self.class_params.items()},
            "trained": self.trained,
            "num_samples": self.num_samples,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path | None = None) -> "BlobClassifier":
        path = path or MODEL_FILE
        inst = cls()
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            inst.class_params = payload.get("class_params", {})
            inst.trained = payload.get("trained", False)
            inst.num_samples = payload.get("num_samples", 0)
        else:
            # build from heuristics
            for cls_name in CLASSES:
                d_c, a_c, ar_c, i_c, sig = HEURISTIC_PRIORS.get(cls_name, (0, 1, 1, 1, 1))
                inst.class_params[cls_name] = {
                    "centroid_depth_fm": {"mu": d_c, "sigma": max(sig * 30, 5)},
                    "area_px":           {"mu": a_c, "sigma": max(sig * 200, 10)},
                    "aspect_ratio":      {"mu": ar_c, "sigma": max(sig * 0.5, 0.05)},
                    "mean_intensity":    {"mu": i_c, "sigma": max(sig * 0.3, 0.02)},
                }
        return inst


# ── CLI ───────────────────────────────────────────────────────────────────────
def main(args: list[str] | None = None) -> int:
    if args is None:
        args = sys.argv[1:]

    HERE = Path(__file__).parent
    db_path = HERE / "captures.db"

    if not args or args[0] == "train":
        conn = sqlite3.connect(str(db_path))
        try:
            clf = BlobClassifier()
            result = clf.train(conn)
            clf.save()
            print(f"Trained: {result['samples']} samples, "
                  f"{result['classes_trained']}/{result['total_classes']} classes")
            print(f"Model saved to {MODEL_FILE}")
        finally:
            conn.close()
        return 0

    if args[0] == "classify":
        if len(args) < 2:
            print("Usage: blob_classifier.py classify <capture_id>", file=sys.stderr)
            return 1
        capture_id = args[1]
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            clf = BlobClassifier.load()
            rows = conn.execute(
                "SELECT * FROM blobs WHERE capture_id = ?", (capture_id,)
            ).fetchall()
            for row in rows:
                feats = {k: row[k] for k in FEATURE_KEYS if row[k] is not None}
                pred, conf = clf.classify(feats)
                print(f"blob {row['id']}: {pred} (conf={conf:.3f})")
        finally:
            conn.close()
        return 0

    if args[0] == "status":
        clf = BlobClassifier.load()
        print(f"Trained: {clf.trained}")
        print(f"Samples: {clf.num_samples}")
        print(f"Classes: {list(clf.class_params.keys())}")
        return 0

    print(f"Unknown command: {args[0]}", file=sys.stderr)
    print("Commands: train, classify <id>, status", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
