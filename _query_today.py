import sqlite3
c = sqlite3.connect('captures.db')
c.row_factory = sqlite3.Row
rows = c.execute("SELECT capture_id, ts_utc, blob_count, mid_zone_mean FROM captures WHERE date(ts_utc) = '2026-07-18' ORDER BY ts_utc").fetchall()
for r in rows:
    print(f"{r['capture_id']:40s} blobs={r['blob_count']:4d} mid={r['mid_zone_mean']:.1f}")
print(f"Total: {len(rows)}")
c.close()
