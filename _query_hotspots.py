import json, sqlite3
from pathlib import Path
from collections import defaultdict

# Check SQLite DB
db_path = Path(r'C:\Users\casey\.openclaw\workspace\tzpro-agent\captures.db')
if db_path.exists():
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()
    tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    print('Tables:', tables)
    for t in tables:
        count = c.execute(f'SELECT COUNT(*) FROM [{t}]').fetchone()[0]
        print(f'  {t}: {count} rows')
    # Check catch labels
    rows = c.execute('SELECT * FROM catch_labels').fetchall()
    print(f'\nCatch labels:')
    for r in rows:
        print(f'  {r}')
    # Check vocabulary
    for t in tables:
        if 'vocab' in t.lower():
            rows = c.execute(f'SELECT * FROM [{t}]').fetchall()
            print(f'\n{t}:')
            for r in rows[:10]:
                print(f'  {r}')
    conn.close()

# Analyze chum hotspots from JSON captures
d = Path(r'C:\Users\casey\.openclaw\workspace\tzpro-agent\captures\v3')
grid = defaultdict(lambda: {'blobs': 0, 'total_intensity': 0, 'lats': [], 'lons': [], 'caps': set(), 'depths': []})

json_files = sorted(d.rglob('*.json'))
print(f'\nFound {len(json_files)} JSON files to analyze')

analyzed = 0
for jf in json_files:
    try:
        meta = json.loads(jf.read_text())
    except:
        continue
    pos = meta.get('position', {})
    lat, lon = pos.get('lat_dd'), pos.get('lon_dd')
    if lat is None:
        continue
    # Handle None analysis or None heuristic
    anal_data = meta.get('analysis')
    if anal_data is None:
        continue
    if isinstance(anal_data, dict):
        heuristic = anal_data.get('heuristic')
    else:
        continue
    if heuristic is None:
        continue
    all_blobs = heuristic.get('lf', {}).get('blobs', [])
    all_blobs += heuristic.get('hf', {}).get('blobs', [])
    analyzed += 1
    
    for b in all_blobs:
        p = b.get('prediction')
        if p and p.get('species') == 'chum' and (p.get('confidence') or 0) >= 0.7:
            key = (round(lat*100), round(lon*100))
            grid[key]['blobs'] += 1
            grid[key]['total_intensity'] += b.get('mean_intensity', 0)
            grid[key]['lats'].append(lat)
            grid[key]['lons'].append(lon)
            grid[key]['caps'].add(jf.stem)
            grid[key]['depths'].append(b.get('depth_fm', 0))

print(f'Analyzed {analyzed} JSON files with valid analysis data')

if not grid:
    print('\nNo chum-predicted blobs found.')
    # Show structure of one analyzed file
    for jf in json_files:
        meta = json.loads(jf.read_text())
        pos = meta.get('position', {})
        if pos.get('lat_dd') is None:
            continue
        print(f'\nSample structure ({jf.name}):')
        print(json.dumps({k: list(meta.keys()) for k in ['position', 'analysis']}, indent=2))
        break
else:
    ranked = sorted(grid.items(), key=lambda x: -x[1]['blobs'])
    total = sum(g['blobs'] for g in grid.values())
    print(f'\n=== CHUM HOTSPOTS (P>=0.7) ===')
    print(f'Total chum-predicted blobs: {total}')
    print(f'Unique grid cells (~1km): {len(grid)}')
    print()
    for i, ((clat, clon), g) in enumerate(ranked, 1):
        al = round(sum(g['lats'])/len(g['lats']), 6)
        ao = round(sum(g['lons'])/len(g['lons']), 6)
        lat_deg = int(abs(al))
        lat_min = round((abs(al) - lat_deg) * 60, 3)
        lon_deg = int(abs(ao))
        lon_min = round((abs(ao) - lon_deg) * 60, 3)
        avg_d = round(sum(g['depths'])/len(g['depths']), 1) if g['depths'] else 0
        avg_i = round(g['total_intensity']/g['blobs'], 1)
        print(f'#{i} {lat_deg:02d}{lat_min:06.3f}N  {lon_deg:03d}{lon_min:06.3f}W')
        print(f'   {g["blobs"]} blobs, {len(g["caps"])} captures, avg depth {avg_d} fm, avg intensity {avg_i}/255')
