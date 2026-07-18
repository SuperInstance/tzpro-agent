#!/usr/bin/env python3
"""Find highest concentration of chum-predicted blobs, output in DDMM.mmm format."""
import json, os, glob
from pathlib import Path
from collections import defaultdict

d = Path(r'C:\Users\casey\.openclaw\workspace\tzpro-agent\captures\v3')
grid = defaultdict(lambda: {'blobs': 0, 'lats': [], 'lons': [], 'depths': [], 'caps': set()})

for day in sorted(d.iterdir()):
    if not day.is_dir(): continue
    for jf in sorted(day.glob('*.json')):
        try:
            meta = json.loads(jf.read_text())
        except: continue
        pos = meta.get('position', {})
        lat = pos.get('lat_dd')
        lon = pos.get('lon_dd')
        if lat is None: continue
        anal = meta.get('analysis', {}).get('heuristic', {})
        for b in anal.get('lf', {}).get('blobs', []):
            p = b.get('prediction')
            if p and p.get('species') == 'chum' and (p.get('confidence') or 0) >= 0.7:
                key = (round(lat*100), round(lon*100))
                g = grid[key]
                g['blobs'] += 1
                g['lats'].append(lat)
                g['lons'].append(lon)
                g['depths'].append(b['centroid_depth_fm'])
                g['caps'].add(meta.get('capture_id',''))

ranked = sorted(grid.items(), key=lambda x: -x[1]['blobs'])
print(f'Total chum-predicted blobs: {sum(g["blobs"] for _,g in grid.items())}')
print(f'Unique grid cells: {len(grid)}')
print()
for i, ((clat, clon), g) in enumerate(ranked[:5], 1):
    avg_lat = round(sum(g['lats'])/len(g['lats']), 6)
    avg_lon = round(sum(g['lons'])/len(g['lons']), 6)
    avg_depth = round(sum(g['depths'])/len(g['depths']), 1)
    # Convert to DDMM.mmm
    lat_deg = int(abs(avg_lat))
    lat_min = round((abs(avg_lat) - lat_deg) * 60, 3)
    lon_deg = int(abs(avg_lon))
    lon_min = round((abs(avg_lon) - lon_deg) * 60, 3)
    ns = 'N' if avg_lat >= 0 else 'S'
    ew = 'W' if avg_lon < 0 else 'E'
    print(f'#{i} — {lat_deg:02d}{lat_min:06.3f}{ns}  {lon_deg:03d}{lon_min:06.3f}{ew}')
    print(f'   {g["blobs"]} blobs, {len(g["caps"])} captures, avg depth {avg_depth} fm')
    print(f'   DD: {avg_lat:.4f}  {avg_lon:.4f}')
    print()
