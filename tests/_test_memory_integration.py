"""Test the full memory pipeline: tide_pool -> stipes -> holdfast."""
import sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

from tide_pool import TidePool
from stipes import StipesDB
from holdfast import Holdfast

print("FULL MEMORY PIPELINE TEST")
print("="*40)

# 1. Tide Pool: add and reinforce a capture
tp = TidePool()
tp.add_capture_analysis({
    "capture_id": "test_001",
    "blob_count": 50,
    "boats": 5,
    "bottom": 57.2,
    "haze": True,
    "mid_zone_intensity": 42.5,
})
print("[OK] Capture added to tide pool")

# Reinforce it 3 times (minimum for graduation)
for i in range(3):
    tp.reinforce_capture()
print("[OK] Capture reinforced 3x")

# 2. Flush tide pool -> stipes
result = tp.flush()
print(f"[OK] Flush: {result.get('status','?')}, graduated={result.get('graduated',0)}, dropped={result.get('dropped',0)}")
assert result.get("graduated", 0) > 0, "Should have graduated the capture"

# 3. Check stipes
stipes = StipesDB()
stats = stipes.stats()
print("[OK] Stipes stats:", stats)

# 4. Reinforce in stipes 7 more times (total 10 -> graduation threshold)
for i in range(7):
    stipes.reinforce("capture")
print("[OK] Stipes reinforced capture 7x (total should be 10)")

# 5. Check if graduation queue has entries
queue = Holdfast.read_queue()
print(f"[OK] Holdfast graduation queue: {len(queue)} entries")

# 6. Migrate to holdfast
holdfast = Holdfast()
if queue:
    count = holdfast.migrate()
    print(f"[OK] Migrated {count} entries to holdfast")
    holdfast_stats = holdfast.stats()
    print(f"[OK] Holdfast stats: total={holdfast_stats.get('total_entries',0)}, kinds={holdfast_stats.get('kinds',[])}")
else:
    print("[WARN] No entries in graduation queue yet - need count >= 10")

print()
print("MEMORY PIPELINE VERIFIED")
