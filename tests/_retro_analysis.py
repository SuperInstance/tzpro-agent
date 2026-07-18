"""Run retroactive analysis on all today captures to populate boat proximity data.
Concise capture: just vertical line counts + state changes from prior frame.
"""
import cv2, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))
from analyzer import detect_vertical_lines, crop_bands, analyze_single, generate_caption, load_recent_context

today = sorted(Path("captures/v3").iterdir())
dirs = [d for d in today if d.is_dir() and not d.name.startswith("__")]
latest_dir = dirs[-1]
pngs = sorted(latest_dir.glob("*.png"))
print(f"Analyzing {len(pngs)} captures in {latest_dir.name}")

# Track boat state across frames for delta detection
prev_lines = None
n_clear = 0
n_boats = 0
boat_streak = 0
clear_streak = 0
transitions = []

for idx, png in enumerate(pngs):
    js = png.with_suffix(".json")
    md = png.with_suffix(".md")
    if not js.exists():
        continue
    
    img = cv2.imread(str(png))
    if img is None:
        continue
    
    lf, hf = crop_bands(img)
    al = analyze_single(lf)
    ah = analyze_single(hf)
    
    n = al.get("boat_proximity", {}).get("vertical_line_count", 0)
    sev = al.get("boat_proximity", {}).get("severity", "none")
    
    # Load context for caption
    ctx = load_recent_context(js, n_frames=5)
    
    # Generate brief delta-focused caption
    caption = generate_caption(al, ah, ctx)
    
    # But override with concise boat note
    has_boats_now = n > 0
    
    # Sequence the update
    analysis = {"lf": al, "hf": ah}
    
    # Update JSON with analysis + boat data
    meta = json.loads(js.read_text("utf-8"))
    existing = meta.get("analysis", {})
    existing_vocab = existing.get("vocabulary", None)
    existing_sv = existing.get("schema_version", 0)
    
    meta["analysis"] = {
        "schema_version": max(2, existing_sv),
        "heuristic": {"lf": al, "hf": ah},
        "caption": caption,
        "vocabulary": existing_vocab,
    }
    js.write_text(json.dumps(meta, indent=2, default=str), "utf-8")
    
    # Track state transitions
    if prev_lines is not None:
        if has_boats_now and not prev_lines:
            transitions.append(f"{png.stem[:12]}... BOATS APPEARED ({n} lines)")
        elif not has_boats_now and prev_lines:
            transitions.append(f"{png.stem[:12]}... BOATS GONE (were {prev_lines}) after {boat_streak} captures")
    
    if has_boats_now:
        boat_streak += 1
        clear_streak = 0
    else:
        clear_streak += 1
        boat_streak = 0
    
    prev_lines = has_boats_now
    
    # Brief console log
    if n > 0:
        delta = ""
        if idx > 0:
            delta = f" [was {n_boats}, streak {boat_streak}]"
        print(f"  {png.stem[:30]:30s} 🚤 {n} lines ({sev}){delta}")
    else:
        streak_note = f" [clear streak {clear_streak}]" if clear_streak > 0 else ""
        print(f"  {png.stem[:30]:30s} 📡 no boats{streak_note}")
    
    n_boats = 1 if has_boats_now else 0

print(f"\n--- State transitions ---")
if transitions:
    for t in transitions:
        print(f"  ⚡ {t}")
else:
    print("  (no state changes detected)")

# Summary
has_boat_data = sum(1 for p in pngs if json.loads(p.with_suffix(".json").read_text("utf-8")).get("analysis",{}).get("heuristic",{}).get("lf",{}).get("boat_proximity",{}).get("vertical_line_count",0) > 0)
print(f"\nSummary: {has_boat_data}/{len(pngs)} captures show boats")
print(f"Done.")
