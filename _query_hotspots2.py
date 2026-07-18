import json
from pathlib import Path
from collections import defaultdict

d = Path(r'C:\Users\casey\.openclaw\workspace\tzpro-agent\captures\v3')
grid = defaultdict(lambda: {'blobs': 0, 'total_intensity': 0, 'lats': [], 'lons': [], 'caps': set(), 'depths': []})

for jf in sorted(d.rglob('*.json')):
    try:
        meta = json.loads(jf.read_text())
    except:
        continue
    pos = meta.get('position', {})
    lat, lon = pos.get('lat_dd'), pos.get('lon_dd')
    if lat is None:
        continue
    anal_data = meta.get('analysis')
    if not isinstance(anal_data, dict):
        continue
    heuristic = anal_data.get('heuristic')
    if not isinstance(heuristic, dict):
        continue
    all_blobs = heuristic.get('lf', {}).get('blobs', [])
    all_blobs += heuristic.get('hf', {}).get('blobs', [])

    for b in all_blobs:
        p = b.get('prediction')
        if p and isinstance(p, dict) and p.get('species') == 'chum' and (p.get('confidence') or 0) >= 0.7:
            key = (round(lat*100), round(lon*100))
            grid[key]['blobs'] += 1
            grid[key]['total_intensity'] += b.get('mean_intensity', 0)
            grid[key]['lats'].append(lat)
            grid[key]['lons'].append(lon)
            grid[key]['caps'].add(jf.stem)
            grid[key]['depths'].append(b.get('centroid_depth_fm', 0))

ranked = sorted(grid.items(), key=lambda x: -x[1]['blobs'])
total = sum(g['blobs'] for g in grid.values())
print(f'Total chum-predicted blobs (P>=0.7): {total}')
print(f'Unique grid cells: {len(grid)}')
print()
print('=== TOP CHUM HOTSPOTS ===')
for i, ((clat, clon), g) in enumerate(ranked, 1):
    al = round(sum(g['lats'])/len(g['lats']), 6)
    ao = round(sum(g['lons'])/len(g['lons']), 6)
    lat_deg = int(abs(al))
    lat_min = round((abs(al) - lat_deg) * 60, 3)
    lon_deg = int(abs(ao))
    lon_min = round((abs(ao) - lon_deg) * 60, 3)
    avg_d = round(sum(g['depths'])/len(g['depths']), 1)
    avg_i = round(g['total_intensity']/g['blobs'], 1)
    print(f' #{i}  {lat_deg:02d}{lat_min:06.3f}N  {lon_deg:03d}{lon_min:06.3f}W')
    print(f'     {g["blobs"]} blobs, {len(g["caps"])} captures, {avg_d} fm avg depth, {avg_i}/255 avg intensity')
