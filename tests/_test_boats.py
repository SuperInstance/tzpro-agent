"""Test vertical line detection, temporal context loading, and new caption generation."""
import cv2, json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

from analyzer import (
    detect_vertical_lines, load_recent_context, crop_bands, 
    generate_caption, analyze_single
)

# Test on today's capture
capture = Path("captures/v3/2026-07-18_5546.779N_13141.210W/0610_5546.779N_13141.210W.png")

if not capture.exists():
    # Fallback to oldest available
    alt = list(Path("captures/v3/2026-07-17_5545.464N_13141.226W").glob("*.png"))
    if alt:
        capture = alt[0]

if not capture.exists():
    # Try any v3 capture
    all_pngs = list(Path("captures/v3").rglob("*.png"))
    if all_pngs:
        capture = all_pngs[0]

print(f"Using: {capture}")
img = cv2.imread(str(capture))
lf, hf = crop_bands(img)

# Test vertical line detection
boats_lf = detect_vertical_lines(lf)
print(f"\nLF Band vertical lines: {boats_lf['vertical_line_count']} ({boats_lf['severity']})")
if boats_lf['lines']:
    top = boats_lf['lines'][0]
    print(f"  Tallest: {top['span_fm']} fm span, intensity {top['mean_intensity']}")
print(f"  Per zone: {boats_lf['lines_per_zone']}")

boats_hf = detect_vertical_lines(hf)
print(f"HF Band vertical lines: {boats_hf['vertical_line_count']} ({boats_hf['severity']})")

# Test temporal context
json_path = capture.with_suffix(".json")
ctx = load_recent_context(json_path, n_frames=5)
print(f"\nRecent context frames: {len(ctx)}")
for c in ctx:
    cid = c["capture_id"][:10]
    print(f"  {cid}... boats={c['vertical_line_count']} ({c['boat_severity']})")

# Test full analysis
al = analyze_single(lf)
ah = analyze_single(hf)
caption = generate_caption(al, ah, ctx)
print(f"\n=== NEW CAPTION ===")
print(f"{capture.name}")
print(caption)

# Also show what the old caption would have been
old_caption = generate_caption(al, ah, None)
print(f"\n=== OLD STYLE (no context) ===")
print(old_caption)

print("\n[DONE]")
