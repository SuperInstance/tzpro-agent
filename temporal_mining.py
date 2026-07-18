#!/usr/bin/env python3
"""temporal_mining.py — PCA anomaly detection on multivariate capture time series.

Reads capture JSONs, extracts 22 structured metrics per capture, builds a
rolling baseline via PCA, and flags anomalous captures (reconstruction error
beyond baseline). Supports one-shot scan and daemon modes.

CLI:
    python temporal_mining.py scan          # one-shot over all captures
    python temporal_mining.py daemon        # poll loop, incrementally mine

Output:
    Writes results to captures.db → anomalies table.

Dependencies: pure Python (numpy optional, degrades gracefully).
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
import time
import sqlite3
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── NumPy optional ──────────────────────────────────────────────────
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

# ── Config ─────────────────────────────────────────────────────────
WORKSPACE = Path(__file__).parent.resolve()
CAPTURES_DIR = WORKSPACE / "captures" / "v3"
DB_PATH = WORKSPACE / "captures.db"

# How many recent captures to use for rolling baseline
BASELINE_WINDOW = 60
# PCA components to retain (explain ~85-90% of variance typically)
N_COMPONENTS = 8
# Z-score threshold for anomaly flagging
ANOMALY_Z_THRESHOLD = 2.5
# Daemon poll interval in seconds
POLL_INTERVAL_S = 120  # 2 min — captures arrive every 10 min

# ── 22 metrics — ordered, documented ────────────────────────────────
# Each metric maps to a named key in the feature vector.
METRIC_NAMES = [
    # LF zone intensities (5)
    "lf_surface_mean",      #  0  surface clutter intensity
    "lf_upper_mean",        #  1  bait / pelagic zone
    "lf_mid_mean",          #  2  target chum zone (20-40 fm)
    "lf_lower_mean",        #  3  near-deep
    "lf_floor_mean",        #  4  bottom zone
    # LF zone variance (5) — how "textured" each zone is
    "lf_surface_var",       #  5
    "lf_upper_var",         #  6
    "lf_mid_var",           #  7
    "lf_lower_var",         #  8
    "lf_floor_var",         #  9
    # LF aggregate
    "lf_pixels_above_thresh", # 10  total signal mass across all zones
    "lf_column_delta_mid",    # 11  left→right gradient in mid zone
    "lf_blob_count",          # 12  discrete echo returns
    "lf_thermocline_count",   # 13  thermal layers
    "lf_bottom_depth_fm",     # 14  detected bottom depth
    "lf_bottom_confidence",   # 15  numeric: low=0, med=0.5, high=1
    # LF boat proximity (2)
    "lf_boat_line_count",     # 16  vertical line artifacts (0 = none)
    "lf_boat_severity",       # 17  numeric: none=0, few=1, several=2, many=3, dense=4
    # HF band (4) — complementary high-frequency band
    "hf_surface_mean",        # 18  HF surface zone
    "hf_mid_mean",            # 19  HF mid zone
    "hf_blob_count",          # 20  HF echo returns
    "hf_haze_count",          # 21  plankton/feed speckle in surface
]

# Convenience accessors
N_METRICS = len(METRIC_NAMES)


# ══════════════════════════════════════════════════════════════════════
#  Numeric helpers (pure Python)
# ══════════════════════════════════════════════════════════════════════

def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _std(values: list[float], mean: Optional[float] = None) -> float:
    if not values or len(values) < 2:
        return 0.0
    m = mean if mean is not None else _mean(values)
    return math.sqrt(sum((x - m) ** 2 for x in values) / (len(values) - 1))


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _subtract(a: list[float], b: list[float]) -> list[float]:
    return [x - y for x, y in zip(a, b)]


def _add(a: list[float], b: list[float]) -> list[float]:
    return [x + y for x, y in zip(a, b)]


def _scale(v: list[float], s: float) -> list[float]:
    return [x * s for x in v]


def _norm(v: list[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def _matmul_vec(mat: list[list[float]], vec: list[float]) -> list[float]:
    """Matrix-vector multiply: mat (m × n), vec (n). Returns (m)."""
    return [_dot(row, vec) for row in mat]


def _transpose(mat: list[list[float]]) -> list[list[float]]:
    """Transpose a 2D matrix."""
    if not mat:
        return []
    m, n = len(mat), len(mat[0])
    result = [[mat[i][j] for i in range(m)] for j in range(n)]
    return result


def _centered_covariance(data: list[list[float]], means: list[float]) -> list[list[float]]:
    """Compute covariance matrix of centered (n_samples × n_features) data.

    data: rows = samples, cols = features
    means: per-feature mean
    """
    n_samples = len(data)
    if n_samples < 2:
        # Return identity-ish
        return [[1.0 if i == j else 0.0 for j in range(N_METRICS)] for i in range(N_METRICS)]

    n_features = len(data[0])
    cov = [[0.0] * n_features for _ in range(n_features)]
    for row in data:
        centered = [row[j] - means[j] for j in range(n_features)]
        for i in range(n_features):
            for j in range(n_features):
                cov[i][j] += centered[i] * centered[j]

    denom = n_samples - 1
    for i in range(n_features):
        for j in range(n_features):
            cov[i][j] /= denom
    return cov


def _power_iteration(a: list[list[float]], max_iter: int = 100, tol: float = 1e-9) -> tuple[list[float], float]:
    """Compute dominant eigenvalue/vector via power iteration."""
    n = len(a)
    v = [1.0 / math.sqrt(n)] * n
    eigenval = 0.0

    for _ in range(max_iter):
        av = _matmul_vec(a, v)
        eigenval_new = _norm(av)
        if eigenval_new < 1e-12:
            v = [0.0] * n
            eigenval = 0.0
            break
        v_new = _scale(av, 1.0 / eigenval_new)

        diff = _norm(_subtract(v_new, _scale(v, 1.0)))
        v = v_new
        if abs(eigenval_new - eigenval) < tol and diff < tol:
            eigenval = eigenval_new
            break
        eigenval = eigenval_new

    return v, eigenval


def _deflate(a: list[list[float]], v: list[float], eigenval: float) -> list[list[float]]:
    """Remove the component along eigenvector v from matrix A."""
    n = len(a)
    result = [row[:] for row in a]
    for i in range(n):
        for j in range(n):
            result[i][j] -= eigenval * v[i] * v[j]
    return result


def _pca_python(data: list[list[float]], n_components: int) -> tuple[list[list[float]], list[float], list[float]]:
    """Pure-Python PCA via power iteration + deflation.

    Args:
        data: (n_samples, n_features)
        n_components: number of principal components to extract

    Returns:
        components: (n_components, n_features) — each row is a PC
        explained_variance: (n_components,) eigenvalues
        mean: (n_features,) per-feature mean
    """
    n_features = len(data[0])
    mean = [_mean([row[j] for row in data]) for j in range(n_features)]

    # Center data and compute covariance
    centered = [[row[j] - mean[j] for j in range(n_features)] for row in data]
    cov = _centered_covariance(data, mean)

    components: list[list[float]] = []
    explained_variance: list[float] = []

    a = [row[:] for row in cov]  # work on a copy
    for _ in range(n_components):
        vec, eigenval = _power_iteration(a)
        if eigenval < 1e-10:
            break
        components.append(vec)
        explained_variance.append(eigenval)
        a = _deflate(a, vec, eigenval)

    if not components:
        # Degenerate: return a single dummy PC
        components = [[1.0 / math.sqrt(n_features)] * n_features]
        explained_variance = [1.0]

    return components, explained_variance, mean


def _pca_numpy(data: np.ndarray, n_components: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """NumPy PCA via SVD."""
    # Center
    mean = data.mean(axis=0)
    centered = data - mean

    # SVD
    u, s, vt = np.linalg.svd(centered, full_matrices=False)

    components = vt[:n_components]
    # Eigenvalues = s^2 / (n - 1)
    explained_variance = (s[:n_components] ** 2) / (max(data.shape[0] - 1, 1))

    return components, explained_variance, mean


# ══════════════════════════════════════════════════════════════════════
#  Feature Extraction
# ══════════════════════════════════════════════════════════════════════

CONFIDENCE_MAP = {"low": 0.0, "medium": 0.5, "high": 1.0}
SEVERITY_MAP = {"none": 0, "few": 1, "several": 2, "many": 3, "dense": 4}


def extract_features(meta: dict) -> Optional[list[float]]:
    """Extract a 22-element feature vector from a capture metadata dict.

    Returns None if the capture lacks analysis data.
    """
    analysis = meta.get("analysis") or {}
    heuristic = analysis.get("heuristic") or {}
    if not heuristic:
        return None

    lf = heuristic.get("lf") or {}
    hf = heuristic.get("hf") or {}

    lf_zones = lf.get("zone_profiles") or {}
    hf_zones = hf.get("zone_profiles") or {}

    features: list[float] = []

    # ── LF zone intensities (0-4) ──
    for z in ("surface", "upper", "mid", "lower", "floor"):
        zp = lf_zones.get(z) or {}
        features.append(float(zp.get("mean_intensity", 0.0)))

    # ── LF zone variance (5-9) ──
    for z in ("surface", "upper", "mid", "lower", "floor"):
        zp = lf_zones.get(z) or {}
        features.append(float(zp.get("variance", 0.0)))

    # ── LF aggregate (10-11) ──
    total_px = sum(
        lf_zones.get(z, {}).get("pixel_count_above_threshold", 0) or 0
        for z in ("surface", "upper", "mid", "lower", "floor")
    )
    features.append(float(total_px))

    col_delta = lf.get("column_delta", {})
    mid_delta = col_delta.get("mid") or {}
    features.append(float(mid_delta.get("delta", 0.0)))

    # ── LF blobs, thermoclines, bottom (12-15) ──
    features.append(float(lf.get("blob_count", 0) or 0))

    features.append(float(lf.get("thermocline_count", 0) or 0))

    lf_bottom = lf.get("bottom") or {}
    features.append(float(lf_bottom.get("bottom_depth_fm", 0.0) or 0.0))

    features.append(CONFIDENCE_MAP.get(lf_bottom.get("confidence", ""), 0.5))

    # ── LF boat proximity (16-17) ──
    boats = lf.get("boat_proximity") or {}
    features.append(float(boats.get("vertical_line_count", 0) or 0))
    features.append(float(SEVERITY_MAP.get(boats.get("severity", "none"), 0)))

    # ── HF band (18-21) ──
    hf_surf = hf_zones.get("surface") or {}
    features.append(float(hf_surf.get("mean_intensity", 0.0)))

    hf_mid = hf_zones.get("mid") or {}
    features.append(float(hf_mid.get("mean_intensity", 0.0)))

    features.append(float(hf.get("blob_count", 0) or 0))

    haze = hf.get("haze") or {}
    features.append(float(haze.get("haze_blob_count", 0) or 0))

    assert len(features) == N_METRICS, f"Expected {N_METRICS} features, got {len(features)}"
    return features


# ══════════════════════════════════════════════════════════════════════
#  PCA Anomaly Detection
# ══════════════════════════════════════════════════════════════════════

def standardize(features: list[list[float]],
                mean: Optional[list[float]] = None,
                std: Optional[list[float]] = None) -> tuple[list[list[float]], list[float], list[float]]:
    """Z-score standardize feature matrix. Computes mean/std if not provided.

    Returns (standardized, mean, std).
    """
    n = len(features)
    if n == 0:
        return [], mean or [], std or []

    if mean is None:
        mean = [_mean([row[j] for row in features]) for j in range(N_METRICS)]
    if std is None:
        std = [_std([row[j] for row in features], mean[j]) for j in range(N_METRICS)]

    # Guard against zero/near-zero std (constant or near-constant features).
    # A relative floor protects against degenerate PCA when features like
    # bottom_depth_fm or bottom_confidence are identical across the baseline.
    _abs_floor = 1e-3
    std_safe = [max(s, _abs_floor, 1e-3 * abs(mean[j]) if abs(mean[j]) > _abs_floor else _abs_floor)
                for j, s in enumerate(std)]

    standardized = [[(row[j] - mean[j]) / std_safe[j] for j in range(N_METRICS)] for row in features]

    return standardized, mean, std


def reconstruction_error(x: list[float],
                         components: list[list[float]],
                         feat_mean: list[float],
                         feat_std: list[float]) -> float:
    """Compute PCA reconstruction error for a single sample.

    Standardizes x, projects onto PC space and back, returns L2 norm of
    the standardized residual. Operates entirely in z-score space so
    reconstruction errors are comparable across metric types.
    """
    # Standardize to z-scores (same std floor as standardize())
    _abs_floor = 1e-3
    std_safe = [max(feat_std[j], _abs_floor,
                    1e-3 * abs(feat_mean[j]) if abs(feat_mean[j]) > _abs_floor else _abs_floor)
                for j in range(N_METRICS)]
    z = [(x[j] - feat_mean[j]) / std_safe[j] for j in range(N_METRICS)]

    # Project onto PCs → scores
    scores = [_dot(z, pc) for pc in components]

    # Reconstruct in z-space: sum scores[i] * pc[i]
    recon_z = [0.0] * N_METRICS
    for score, pc in zip(scores, components):
        for j in range(N_METRICS):
            recon_z[j] += score * pc[j]

    # Residual L2 norm (in standardized space)
    residual = [z[j] - recon_z[j] for j in range(N_METRICS)]
    return _norm(residual)


def top_contributing_metrics(x: list[float],
                             components: list[list[float]],
                             feat_mean: list[float],
                             feat_std: list[float],
                             top_k: int = 5) -> list[int]:
    """Return indices of metrics contributing most to reconstruction error."""
    _abs_floor = 1e-3
    std_safe = [max(feat_std[j], _abs_floor,
                    1e-3 * abs(feat_mean[j]) if abs(feat_mean[j]) > _abs_floor else _abs_floor)
                for j in range(N_METRICS)]
    z = [(x[j] - feat_mean[j]) / std_safe[j] for j in range(N_METRICS)]

    scores = [_dot(z, pc) for pc in components]

    recon_z = [0.0] * N_METRICS
    for score, pc in zip(scores, components):
        for j in range(N_METRICS):
            recon_z[j] += score * pc[j]

    residuals = [abs(z[j] - recon_z[j]) for j in range(N_METRICS)]
    indexed = list(enumerate(residuals))
    indexed.sort(key=lambda t: t[1], reverse=True)
    return [idx for idx, _ in indexed[:top_k]]


# ══════════════════════════════════════════════════════════════════════
#  Database
# ══════════════════════════════════════════════════════════════════════

ANOMALY_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS anomalies (
    capture_id TEXT PRIMARY KEY,
    ts_utc TEXT NOT NULL,
    reconstruction_error REAL NOT NULL,
    anomaly_z REAL NOT NULL,
    is_anomaly INTEGER NOT NULL DEFAULT 0,
    top_contributing_metrics TEXT,
    baseline_n INTEGER,
    baseline_mean_error REAL,
    baseline_std_error REAL,
    analysis_ts TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_anomalies_ts ON anomalies(ts_utc);
CREATE INDEX IF NOT EXISTS idx_anomalies_flag ON anomalies(is_anomaly);
"""


def get_db(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = str(db_path or DB_PATH)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_anomaly_table(conn: sqlite3.Connection) -> None:
    conn.executescript(ANOMALY_TABLE_SQL)
    conn.commit()


def write_anomaly_result(conn: sqlite3.Connection,
                         capture_id: str,
                         ts_utc: str,
                         recon_error: float,
                         anomaly_z: float,
                         is_anomaly: bool,
                         top_metric_indices: list[int],
                         baseline_n: int,
                         baseline_mean_err: float,
                         baseline_std_err: float) -> None:
    metric_names = [METRIC_NAMES[i] for i in top_metric_indices]
    analysis_ts = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """INSERT OR REPLACE INTO anomalies (
            capture_id, ts_utc, reconstruction_error, anomaly_z, is_anomaly,
            top_contributing_metrics, baseline_n, baseline_mean_error,
            baseline_std_error, analysis_ts
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            capture_id, ts_utc, round(recon_error, 4), round(anomaly_z, 4),
            1 if is_anomaly else 0,
            json.dumps(metric_names),
            baseline_n, round(baseline_mean_err, 4), round(baseline_std_err, 4),
            analysis_ts,
        ),
    )


# ══════════════════════════════════════════════════════════════════════
#  Core Pipeline
# ══════════════════════════════════════════════════════════════════════

class TemporalMiner:
    """Tracks rolling baseline for multivariate temporal anomaly detection."""

    def __init__(self, window: int = BASELINE_WINDOW,
                 n_components: int = N_COMPONENTS,
                 z_threshold: float = ANOMALY_Z_THRESHOLD):
        self.window = window
        self.n_components = n_components
        self.z_threshold = z_threshold

        # Rolling feature window (most recent N samples)
        self.recent_features: deque[tuple[str, str, list[float]]] = deque(maxlen=window)
        # (capture_id, ts_utc, feature_vector)

        # PCA state (recomputed periodically)
        self.components: list[list[float]] = []
        self.explained_variance: list[float] = []
        self.feature_mean: list[float] = []
        self.feature_std: list[float] = []

        # Reconstruction error baseline stats
        self.baseline_errors: deque[float] = deque(maxlen=window)
        self._pca_stale = True

    # ── ingest ──────────────────────────────────────────────────

    def ingest(self, capture_id: str, ts_utc: str, features: list[float]) -> None:
        """Add a capture to the rolling window."""
        self.recent_features.append((capture_id, ts_utc, features))
        self._pca_stale = True

    # ── baseline update ─────────────────────────────────────────

    def _update_pca(self) -> None:
        """Recompute PCA from the current rolling window."""
        if not self._pca_stale:
            return

        n = len(self.recent_features)
        if n < max(self.n_components + 1, 10):
            return  # Not enough data yet

        # Build feature matrix and standardize
        feature_matrix = [f for _, _, f in self.recent_features]
        standardized, self.feature_mean, self.feature_std = standardize(feature_matrix)

        # PCA on standardized data
        if HAS_NUMPY:
            comp_np, ev_np, _mean_np = _pca_numpy(
                np.array(standardized, dtype=np.float64), self.n_components,
            )
            self.components = [list(row) for row in comp_np]
            self.explained_variance = [float(v) for v in ev_np]
        else:
            self.components, self.explained_variance, _ = _pca_python(
                standardized, self.n_components,
            )

        # Recompute reconstruction errors on standardized samples
        self.baseline_errors.clear()
        for _, _, fvec in self.recent_features:
            err = reconstruction_error(fvec, self.components,
                                       self.feature_mean, self.feature_std)
            self.baseline_errors.append(err)

        self._pca_stale = False

    # ── score ───────────────────────────────────────────────────

    # Floor for baseline std to avoid pathological z-scores
    # when the initial baseline errors are near-zero. 0.01 is
    # roughly 1% of a typical reconstruction error (~0.1-5.0).
    _MIN_BASELINE_STD = 0.01

    # Cap z-score to prevent floating-point blowup from extremely
    # uniform baselines (e.g. sounder-off captures vs. zeros).
    _MAX_Z = 100.0

    def score(self, features: list[float]) -> dict:
        """Score a single feature vector. Returns anomaly assessment dict."""
        self._update_pca()

        n_samples = len(self.recent_features)
        min_samples = max(self.n_components + 1, 10)

        if n_samples < min_samples or not self.components:
            return {
                "reconstruction_error": 0.0,
                "anomaly_z": 0.0,
                "is_anomaly": False,
                "top_contributing_metrics": [],
                "baseline_n": n_samples,
                "baseline_mean_error": 0.0,
                "baseline_std_error": 0.0,
                "insufficient_data": True,
            }

        err = reconstruction_error(features, self.components,
                                    self.feature_mean, self.feature_std)
        top_idx = top_contributing_metrics(features, self.components,
                                           self.feature_mean, self.feature_std)

        errors_list = list(self.baseline_errors)
        mean_err = _mean(errors_list) if errors_list else 0.0
        raw_std = _std(errors_list, mean_err) if len(errors_list) >= 2 else 1.0
        std_err = max(raw_std, self._MIN_BASELINE_STD)

        z = min((err - mean_err) / std_err, self._MAX_Z)
        is_anom = z > self.z_threshold

        return {
            "reconstruction_error": round(err, 4),
            "anomaly_z": round(z, 4),
            "is_anomaly": is_anom,
            "top_contributing_metrics": top_idx,
            "baseline_n": n_samples,
            "baseline_mean_error": round(mean_err, 4),
            "baseline_std_error": round(raw_std, 4),
            "insufficient_data": False,
        }


# ══════════════════════════════════════════════════════════════════════
#  JSON → Feature Loop
# ══════════════════════════════════════════════════════════════════════

def find_all_capture_jsons() -> list[Path]:
    if not CAPTURES_DIR.exists():
        return []
    files: list[Path] = []
    for day_dir in sorted(CAPTURES_DIR.iterdir()):
        if not day_dir.is_dir():
            continue
        for js in sorted(day_dir.glob("*.json")):
            files.append(js)
    return files


def load_reference_data() -> list[dict]:
    """Load all capture metadata from JSON files, sorted by ts_utc."""
    records: list[dict] = []
    for js_path in find_all_capture_jsons():
        try:
            meta = json.loads(js_path.read_text(encoding="utf-8"))
            features = extract_features(meta)
            if features is None:
                continue
            capture_id = meta.get("capture_id", js_path.stem)
            ts_utc = meta.get("ts_utc", "")
            records.append({
                "capture_id": capture_id,
                "ts_utc": ts_utc,
                "features": features,
                "path": js_path,
            })
        except (json.JSONDecodeError, OSError, KeyError) as e:
            logging.warning("Skipping %s: %s", js_path.name, e)
    records.sort(key=lambda r: r["ts_utc"])
    return records


# ══════════════════════════════════════════════════════════════════════
#  CLI: scan
# ══════════════════════════════════════════════════════════════════════

def cmd_scan() -> int:
    """One-shot scan: load all captures, run PCA, write anomalies to DB."""
    logger = logging.getLogger("temporal_mining.scan")
    logger.info("Scanning captures for temporal anomalies...")

    records = load_reference_data()
    if not records:
        logger.warning("No captures with analysis data found.")
        return 0

    logger.info("Loaded %d captures with analysis data.", len(records))

    conn = get_db()
    init_anomaly_table(conn)

    miner = TemporalMiner()
    anomaly_count = 0
    insufficient_until = max(miner.n_components + 1, 10)

    for i, rec in enumerate(records):
        cid = rec["capture_id"]
        ts = rec["ts_utc"]
        fvec = rec["features"]

        result = miner.score(fvec)

        if result.get("insufficient_data"):
            logger.debug("  [%d/%d] %s — insufficient baseline (%d samples)",
                         i + 1, len(records), cid, result["baseline_n"])
        else:
            if result["is_anomaly"]:
                anomaly_count += 1
                metric_str = ", ".join(
                    METRIC_NAMES[idx] for idx in result["top_contributing_metrics"]
                )
                logger.warning(
                    "  ANOMALY [%d/%d] %s  z=%.2f  err=%.3f  metrics=[%s]",
                    i + 1, len(records), cid, result["anomaly_z"],
                    result["reconstruction_error"], metric_str,
                )
            else:
                logger.debug("  [%d/%d] %s  z=%.2f", i + 1, len(records), cid, result["anomaly_z"])

        miner.ingest(cid, ts, fvec)

        # Write to DB
        try:
            write_anomaly_result(
                conn, cid, ts,
                result["reconstruction_error"],
                result["anomaly_z"],
                result["is_anomaly"],
                result["top_contributing_metrics"],
                result["baseline_n"],
                result["baseline_mean_error"],
                result["baseline_std_error"],
            )
        except sqlite3.Error as e:
            logger.error("DB write failed for %s: %s", cid, e)

        # Commit periodically
        if (i + 1) % 50 == 0:
            conn.commit()

    conn.commit()

    # Summary
    logger.info("──────────────────────────────────────────")
    logger.info("Scan complete: %d captures, %d anomalies flagged (z > %.1f)",
                len(records), anomaly_count, ANOMALY_Z_THRESHOLD)

    # Top anomalies by z-score
    cur = conn.execute(
        "SELECT capture_id, anomaly_z, reconstruction_error, top_contributing_metrics "
        "FROM anomalies WHERE is_anomaly = 1 ORDER BY anomaly_z DESC LIMIT 10"
    )
    rows = cur.fetchall()
    if rows:
        logger.info("Top anomalies:")
        for r in rows:
            logger.info("  %s  z=%.2f  err=%.3f  [%s]",
                        r["capture_id"], r["anomaly_z"],
                        r["reconstruction_error"], r["top_contributing_metrics"])

    conn.close()
    return anomaly_count


# ══════════════════════════════════════════════════════════════════════
#  CLI: daemon
# ══════════════════════════════════════════════════════════════════════

def cmd_daemon() -> None:
    """Poll loop: watch for new captures, update baseline incrementally."""
    logger = logging.getLogger("temporal_mining.daemon")
    logger.info("Temporal mining daemon starting (poll every %ds)", POLL_INTERVAL_S)
    logger.info("Window: %d captures | PCs: %d | Z threshold: %.1f",
                BASELINE_WINDOW, N_COMPONENTS, ANOMALY_Z_THRESHOLD)

    conn = get_db()
    init_anomaly_table(conn)

    miner = TemporalMiner()

    # Warm-start: load all existing captures as baseline
    records = load_reference_data()
    logger.info("Warm-start: ingesting %d existing captures as baseline.", len(records))

    known_ids: set[str] = set()
    for rec in records:
        cid = rec["capture_id"]
        ts = rec["ts_utc"]
        fvec = rec["features"]

        known_ids.add(cid)
        miner.ingest(cid, ts, fvec)

        # Score and write each one for historical completeness
        result = miner.score(fvec)
        try:
            write_anomaly_result(
                conn, cid, ts,
                result["reconstruction_error"],
                result["anomaly_z"],
                result["is_anomaly"],
                result["top_contributing_metrics"],
                result["baseline_n"],
                result["baseline_mean_error"],
                result["baseline_std_error"],
            )
        except sqlite3.Error:
            pass
    conn.commit()
    logger.info("Warm-start complete: %d captures baselined.", len(known_ids))

    # Main loop
    try:
        while True:
            new_records = load_reference_data()
            new_count = 0

            for rec in new_records:
                if rec["capture_id"] in known_ids:
                    continue

                cid = rec["capture_id"]
                ts = rec["ts_utc"]
                fvec = rec["features"]

                known_ids.add(cid)
                new_count += 1

                result = miner.score(fvec)

                if not result.get("insufficient_data") and result["is_anomaly"]:
                    metric_str = ", ".join(
                        METRIC_NAMES[idx] for idx in result["top_contributing_metrics"]
                    )
                    logger.warning(
                        "⚠ ANOMALY: %s  z=%.2f  err=%.3f  metrics=[%s]",
                        cid, result["anomaly_z"],
                        result["reconstruction_error"], metric_str,
                    )
                else:
                    logger.info("  %s  z=%.2f  err=%.3f", cid, result["anomaly_z"], result["reconstruction_error"])

                miner.ingest(cid, ts, fvec)

                try:
                    write_anomaly_result(
                        conn, cid, ts,
                        result["reconstruction_error"],
                        result["anomaly_z"],
                        result["is_anomaly"],
                        result["top_contributing_metrics"],
                        result["baseline_n"],
                        result["baseline_mean_error"],
                        result["baseline_std_error"],
                    )
                except sqlite3.Error as e:
                    logger.error("DB write failed: %s", e)

            if new_count:
                conn.commit()
                logger.info("Processed %d new capture(s). Baseline: %d samples.",
                            new_count, len(miner.recent_features))
            else:
                logger.debug("No new captures.")

            time.sleep(POLL_INTERVAL_S)

    except KeyboardInterrupt:
        logger.info("Daemon shutting down.")
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"

    if cmd == "scan":
        n_anomalies = cmd_scan()
        sys.exit(0 if n_anomalies == 0 else 1)
    elif cmd == "daemon":
        cmd_daemon()
    else:
        print(f"Usage: python temporal_mining.py [scan|daemon]", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
