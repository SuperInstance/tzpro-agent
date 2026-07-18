"""Check today's captures and test vertical line detection on the latest one."""
import cv2, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))
from analyzer import detect_vertical_lines, crop_bands, analyze_single

today = sorted(Path("captures/v3").iterdir())
dirs = [d for d in today if d.is_dir() and not d.name.startswith("__")]
if not dirs:
    print("No day directories found")
    sys.exit(1)

latest_dir = dirs[-1]
print(f"Latest day dir: {latest_dir.name}")

pngs = sorted(latest_dir.glob("*.png"))
print(f"Total captures today: {len(pngs)}")

# Check last few PNGs for analysis status
for p in pngs[-6:]:
    js = p.with_suffix(".json")
    has = "?"
    if js.exists():
        d = json.loads(js.read_text("utf-8"))
        an = d.get("analysis", {})
        he = an.get("heuristic", {})
        lf = he.get("lf", {})
        has = "boat" if lf.get("boat_proximity") else ("analyzed" if he else "no_heuristic")
    print(f"  {p.stem:35s} {has}")

# Run vertical line detection on the latest PNG
latest_png = pngs[-1]
print(f"\n--- Testing vertical lines on: {latest_png.name} ---")
img = cv2.imread(str(latest_png))
if img is None:
    print(f"ERROR: Cannot read {latest_png}")
    sys.exit(1)

lf, hf = crop_bands(img)
analysis = analyze_single(lf)
boats = analysis.get("boat_proximity", {})
n = boats.get("vertical_line_count", 0)
sev = boats.get("severity", "none")
print(f"  LF: {n} vertical lines ({sev})")
if n > 0:
    print(f"  Per zone: {boats['lines_per_zone']}")
    print(f"  Max span: {boats['max_vertical_span_fm']} fm")
    for ln in boats['lines'][:3]:
        print(f"    x={ln['x_start']}-{ln['x_end']} span={ln['span_fm']}fm int={ln['mean_intensity']}")

hf_boats = analyze_single(hf).get("boat_proximity", {})
print(f"  HF: {hf_boats.get('vertical_line_count',0)} vertical lines ({hf_boats.get('severity','none')})")

# Check all captures for boats
print(f"\n--- All today captures with vertical lines >0 ---")
capture = latest_dir
for p in pngs[-20:]:
    js = p.with_suffix(".json")
    if not js.exists():
        continue
    try:
        d = json.loads(js.read_text("utf-8"))
        lf_data = d.get("analysis", {}).get("heuristic", {}).get("lf", {})
        b = lf_data.get("boat_proximity", {})
        n = b.get("vertical_line_count", 0)
        if n > 0:
            print(f"  {p.stem[:25]:25s} {n} lines ({b.get('severity','?')})")
    except:
        pass

# If none have boat data, re-analyze the latest one and show
print(f"\n[DONE]")
