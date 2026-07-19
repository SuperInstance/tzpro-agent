# TZ Pro Agent — Query Examples

**Copy-paste these into PowerShell. Replace coordinates/dates with yours.**

---

## Position Queries

### Charted Depth at a Position
```powershell
python contour_query.py 55.78853 -131.69630
# → 67.3 fm
```

### Gear Clearance (Will 48 fm gear hit bottom?)
```powershell
python -c "from contour_query import get_gear_clearance; print(get_gear_clearance(55.78853, -131.69630, 48))"
# → {'charted_fm': 67.3, 'gear_fm': 48.0, 'clearance_fm': 19.3, 'status': 'clear'}
```

### All Contour Bands Near a Position
```powershell
python -c "from contour_query import get_contour_bands; print(get_contour_bands(55.78853, -131.69630))"
# → {5: {...}, 10: {...}, 20: {...}, 30: {...}, 48: {...}, 60: {...}, 80: {...}, 100: {...}, 150: {...}}
```

### Depth Profile Along a Line (Steam Path)
```powershell
python -c "
from contour_query import get_depth_fm
import numpy as np
lats = np.linspace(55.78, 55.80, 20)
lons = np.linspace(-131.70, -131.68, 20)
for lat, lon in zip(lats, lons):
    d = get_depth_fm(lat, lon)
    print(f'{lat:.5f}, {lon:.5f} → {d:.1f} fm')
"
```

---

## Anomaly Queries (Reality vs Chart)

### All Anomalies > 1 fm (CSV for QGIS/Excel)
```powershell
python anomaly_logger.py --export-csv --min-delta 1.0
# → bathymetry/qgis_corrections.csv
```

### All Anomalies > 5 fm (Major Chart Errors)
```powershell
python anomaly_logger.py --export-csv --min-delta 5.0
```

### Anomalies in a Date Range
```powershell
python anomaly_logger.py --export-csv --min-delta 1.0 --since 2026-07-15 --until 2026-07-21
```

### GeoJSON for QGIS (Map Visualization)
```powershell
python anomaly_logger.py --export-geojson --min-delta 1.0
# → bathymetry/anomalies.geojson
```

### Statistics Summary
```powershell
python anomaly_logger.py --stats
# Total: 1,247
# Mean |delta|: 3.2 fm
# Max delta: +14.1 fm (chart deeper)
# Min delta: -12.8 fm (chart shallower)
# By region: Ketchikan harbor -8.2 avg, Clarence Strait +2.1 avg...
```

### Anomalies Near a Specific Position
```powershell
python -c "
import sqlite3
conn = sqlite3.connect('bathymetry/anomalies.db')
c = conn.cursor()
c.execute('''
    SELECT ts, lat, lon, sounder_fm, contour_fm, delta_fm, sog
    FROM bathymetry_anomalies
    WHERE lat BETWEEN 55.77 AND 55.80 AND lon BETWEEN -131.71 AND -131.68
    ORDER BY abs(delta_fm) DESC
    LIMIT 20
''')
for row in c.fetchall():
    print(f'{row[0]} | {row[1]:.5f}, {row[2]:.5f} | Sounder: {row[3]:.1f} | Chart: {row[4]:.1f} | Delta: {row[5]:+.1f} | SOG: {row[6]}')
"
```

---

## Sounder Observation Queries

### Today's Observations (Raw JSONL)
```powershell
# Windows PowerShell
Get-Content memory\observations\2026-07-19.jsonl | Select-Object -First 5
```

### All Chum Detections Today
```powershell
python -c "
import json
with open('memory/observations/2026-07-19.jsonl') as f:
    for line in f:
        d = json.loads(line)
        if 'chum' in str(d.get('sounder_analysis', {}).get('vocabulary', '')).lower():
            print(f\"{d['ts']} | {d['position']['lat']:.5f}, {d['position']['lon']:.5f} | {d['sounder_analysis']['depth_fm']:.1f} fm | fish: {d['sounder_analysis']['fish_returns']['count']}\")
"
```

### Chum Detections This Week
```powershell
python -c "
import json, glob, os
for file in sorted(glob.glob('memory/observations/2026-07-*.jsonl')):
    with open(file) as f:
        for line in f:
            d = json.loads(line)
            vocab = d.get('sounder_analysis', {}).get('vocabulary', '')
            if 'chum' in str(vocab).lower():
                print(f\"{d['ts'][:10]} | {d['position']['lat']:.5f}, {d['position']['lon']:.5f} | {d['sounder_analysis']['depth_fm']:.1f} fm | {d['sounder_analysis']['fish_returns']['count']} fish | vocab: {vocab}\")
"
```

### All Observations at a Specific Position (±0.001° ≈ 100m)
```powershell
python -c "
import json, glob
target_lat, target_lon = 55.78853, -131.69630
radius = 0.001
for file in sorted(glob.glob('memory/observations/*.jsonl')):
    with open(file) as f:
        for line in f:
            d = json.loads(line)
            lat, lon = d['position']['lat'], d['position']['lon']
            if abs(lat - target_lat) < radius and abs(lon - target_lon) < radius:
                print(f\"{d['ts']} | {lat:.5f}, {lon:.5f} | depth: {d['sounder_analysis']['depth_fm']:.1f} fm | fish: {d['sounder_analysis']['fish_returns']['count']} | bottom: {d['sounder_analysis']['bottom_type']}\")
"
```

### Thermocline Depths This Week
```powershell
python -c "
import json, glob
for file in sorted(glob.glob('memory/observations/2026-07-*.jsonl')):
    with open(file) as f:
        for line in f:
            d = json.loads(line)
            thermos = d.get('sounder_analysis', {}).get('thermoclines_fm', [])
            if thermos:
                print(f\"{d['ts'][:16]} | {d['position']['lat']:.5f}, {d['position']['lon']:.5f} | thermos: {[f'{t:.1f}' for t in thermos]} fm\")
"
```

### Bottom Type Changes (Hard → Soft etc.)
```powershell
python -c "
import json, glob
prev = None
for file in sorted(glob.glob('memory/observations/2026-07-*.jsonl')):
    with open(file) as f:
        for line in f:
            d = json.loads(line)
            bt = d['sounder_analysis']['bottom_type']
            if prev and bt != prev:
                print(f\"CHANGE: {prev} → {bt} at {d['ts'][:16]} | {d['position']['lat']:.5f}, {d['position']['lon']:.5f}\")
            prev = bt
"
```

---

## Catch Correlation Queries

### Link Catches to Sounder Data (Requires catch_log.csv)
```powershell
# First, create a catch log (CSV with columns: ts, lat, lon, hook, species, size_cm)
# Then:
python catch_link.py --catch-log catch_log.csv --window-sec 60 --export-csv
# Output: catches_with_sounder.csv — each catch row enriched with sounder analysis at that moment
```

### Chum Catches This Season with Sounder Signatures
```powershell
python catch_link.py --species chum --season 2026 --export-csv > chum_2026.csv
```

### Halibut Catches — Bottom Type at Capture
```powershell
python catch_link.py --species halibut --season 2026 --export-csv > halibut_2026.csv
# Check bottom_type column — are they on hard/soft/mud?
```

### By Hook Position (Hook 18 = ~48 fm + 17×1.5 = ~73 fm?)
```powershell
python catch_link.py --hook 18 --season 2026 --export-csv
```

---

## Natural Language Queries (via agent.py)

### "Where were chum holding yesterday?"
```powershell
python agent.py "where were chum holding yesterday"
```

### "Show me all spots where bottom differed > 3 fm from chart"
```powershell
python agent.py "show me all spots where bottom differed more than 3 fathoms from chart"
```

### "What did position X look like at time Y?"
```powershell
python agent.py "what did 55.78853 -131.69630 look like at 0800 today"
```

### "Compare today's chum depths to last week"
```powershell
python agent.py "compare today's chum depths to last week"
```

### "Best chum spot this season"
```powershell
python agent.py "best chum spot this season"
```

### "Anomalies near the hump at 55°47.3N"
```powershell
python agent.py "anomalies near 55.788 -131.696"
```

### "Thermocline patterns on flood vs ebb"
```powershell
python agent.py "thermocline patterns on flood vs ebb tide"
```

### "Species signature for rockfish"
```powershell
python agent.py "rockfish sounder signature"
```

---

## Batch Exports for Analysis (Python/Pandas/R)

### All Observations → Single CSV
```powershell
python -c "
import json, glob, csv
with open('all_observations.csv', 'w', newline='') as out:
    writer = csv.writer(out)
    writer.writerow(['ts','lat','lon','sog','cog','depth_fm','bottom_type','fish_count','fish_density','avg_intensity','max_intensity','depth_range_min','depth_range_max','largest_blob_depth','largest_blob_area','largest_blob_intensity','thermoclines','vocabulary','charted_fm','delta_fm','anomaly'])
    for file in sorted(glob.glob('memory/observations/*.jsonl')):
        with open(file) as f:
            for line in f:
                d = json.loads(line)
                sa = d['sounder_analysis']
                fr = sa['fish_returns']
                lb = fr.get('largest_blob', {})
                cc = d.get('chart_comparison', {})
                writer.writerow([
                    d['ts'], d['position']['lat'], d['position']['lon'],
                    d['vessel'].get('sog'), d['vessel'].get('cog'),
                    sa['depth_fm'], sa['bottom_type'],
                    fr['count'], fr['density_per_100kpx'], fr['avg_intensity'], fr.get('max_intensity'),
                    fr['depth_range_fm'][0], fr['depth_range_fm'][1],
                    lb.get('depth_fm'), lb.get('area_px'), lb.get('intensity'),
                    ';'.join(f'{t:.1f}' for t in sa.get('thermoclines_fm', [])),
                    sa.get('vocabulary', ''),
                    cc.get('charted_fm'), cc.get('delta_fm'), cc.get('anomaly_logged', False)
                ])
print('Done: all_observations.csv')
"
```

### Load in Pandas (for Analysis)
```python
import pandas as pd
df = pd.read_csv('all_observations.csv', parse_dates=['ts'])
df['hour'] = df['ts'].dt.hour
df['date'] = df['ts'].dt.date

# Chum by hour
chum = df[df['vocabulary'].str.contains('chum', case=False, na=False)]
print(chum.groupby('hour')['fish_count'].mean())

# Anomalies by region
anom = df[df['anomaly'] == True]
print(anom.groupby(pd.cut(anom['lat'], bins=10))['delta_fm'].mean())

# Thermocline depth by month
df['thermo_shallow'] = df['thermoclines'].str.split(';').str[0].astype(float)
print(df.groupby(df['ts'].dt.month)['thermo_shallow'].mean())
```

---

## Quick One-Liners (Alias These)

Add to your PowerShell profile (`notepad $PROFILE`):
```powershell
function tz-depth { param($lat, $lon) python contour_query.py $lat $lon }
function tz-clearance { param($lat, $lon, $gear=48) python -c "from contour_query import get_gear_clearance; print(get_gear_clearance($lat, $lon, $gear))" }
function tz-anomalies { python anomaly_logger.py --export-csv --min-delta 1.0 }
function tz-health { python agent.py --brief }
function tz-ask { python agent.py $args }
function tz-capture { python capture.py --oneshot }
```

Then use:
```powershell
tz-depth 55.78853 -131.69630
tz-clearance 55.78853 -131.69630 48
tz-anomalies
tz-health
tz-ask "where were chum holding yesterday"
tz-capture
```

---

## SQL Queries (Direct Database Access)

### Top 20 Anomalies by Magnitude
```sql
SELECT ts, lat, lon, sounder_fm, contour_fm, delta_fm, sog
FROM bathymetry_anomalies
ORDER BY abs(delta_fm) DESC
LIMIT 20;
```

### Anomalies by Month
```sql
SELECT strftime('%Y-%m', ts) as month,
       COUNT(*) as count,
       AVG(delta_fm) as avg_delta,
       MAX(delta_fm) as max_deeper,
       MIN(delta_fm) as max_shallower
FROM bathymetry_anomalies
GROUP BY month
ORDER BY month;
```

### Anomalies in a Box (Lat/Lon Bounds)
```sql
SELECT * FROM bathymetry_anomalies
WHERE lat BETWEEN 55.77 AND 55.80
  AND lon BETWEEN -131.71 AND -131.68
  AND abs(delta_fm) > 2.0
ORDER BY abs(delta_fm) DESC;
```

### Drift Track (Position Over Time)
```sql
SELECT ts, lat, lon, sog, cog, sounder_fm, contour_fm, delta_fm
FROM bathymetry_anomalies
WHERE lat BETWEEN 55.78 AND 55.80
  AND lon BETWEEN -131.70 AND -131.68
ORDER BY ts;
```

---

*Every query is a question. Every answer writes the chart.*
*F/V EILEEN • CoCapn*