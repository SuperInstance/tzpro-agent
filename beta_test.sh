#!/usr/bin/env python3
"""
beta_test.sh — Run the experiment suite and log results.

This script runs all experiments in sequence, saving results to
_experiment_logs/ for later analysis. Designed to be run by
mini-agent or Claude Code for beta testing.

Usage:
    bash beta_test.sh
"""

# Run GPU check
echo "[1/6] GPU check..."
python3 -c "
import torch
print(f'PyTorch: {torch.__version__}')
print(f'CUDA: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'GPU: {torch.cuda.get_device_name(0)}')
    print(f'VRAM: {torch.cuda.mem_get_info()[0]/1024**3:.1f}GB free')
" > _experiment_logs/01_gpu.txt 2>&1

# Run contour query test
echo "[2/6] Contour query test..."
python3 -c "
from contour_query import get_depth_fm, get_gear_clearance
for name, pos in [('Ketchikan harbor', (55.3422, -131.6433)),
                   ('Test capture', (55.78595, -131.527017)),
                   ('Channel west', (55.78595, -131.55)),
                   ('Channel east', (55.78595, -131.50))]:
    d = get_depth_fm(*pos)
    g = get_gear_clearance(*pos)
    print(f'{name}: {d}fm  gear={g}')
" > _experiment_logs/02_contour.txt 2>&1

# Run forward look test
echo "[3/6] Forward look test..."
python3 -c "
from forward_look import predict_ahead
for hdg in [0, 45, 90, 135, 180, 225, 270, 315]:
    r = predict_ahead(55.78595, -131.527017, hdg, 1.6)
    if 'error' in r: continue
    prof = r.get('profile', [])
    far = prof[-1]['depth_fm'] if prof else '?'
    near = r['current']['depth_fm']
    print(f'{hdg:>3}: {near:.0f}fm -> {far:.0f}fm at 1nm')
" > _experiment_logs/03_forward.txt 2>&1

# Run memory search test
echo "[4/6] Memory search test..."
python3 -c "
from memory_search import embed
for q in ['48 fm gear contour', 'soft muddy bottom', 'fish school near surface', 'depth anomaly 14 fm']:
    v = embed(q)
    print(f'{q}: {len(v)}dims [{v[0]:.3f}, {v[1]:.3f}, {v[2]:.3f}]' if v else f'{q}: failed')
" > _experiment_logs/04_memory.txt 2>&1

# Run anomaly logger test
echo "[5/6] Anomaly logger test..."
python3 -c "
from anomaly_logger import stats, export_qgis
s = stats()
print(f'Total anomalies: {s.get(\"total\", 0)}')
if s.get('total', 0):
    print(f'Avg magnitude: {s[\"avg_magnitude_fm\"]}fm')
    print(f'Largest delta: {s[\"largest_negative_fm\"]}fm')
    n = export_qgis()
    print(f'QGIS export: {n} rows')
" > _experiment_logs/05_anomaly.txt 2>&1

# Run Florence-2 test (CUDA venv)
echo "[6/6] Florence-2 test..."
cd "$(dirname "$0")"
./venv_cuda/Scripts/python -u _test_florence.py > _experiment_logs/06_florence.txt 2>&1

echo ""
echo "=== Results ==="
for f in _experiment_logs/[0-9]*.txt; do
    echo ""
    echo "--- $(basename $f) ---"
    cat "$f"
done
