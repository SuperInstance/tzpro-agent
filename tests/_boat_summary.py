"""Summarize boat proximity across all captures after retroactive analysis."""
import json
from pathlib import Path

root = Path("captures/v3")
dirs = sorted([d for d in root.iterdir() if d.is_dir() and not d.name.startswith("__")])

for d in dirs:
    pngs = sorted(d.glob("*.png"))
    boat_count = 0
    prev = None
    transitions = []
    
    for p in pngs:
        js = p.with_suffix(".json")
        if not js.exists():
            continue
        try:
            meta = json.loads(js.read_text("utf-8"))
            lf = meta.get("analysis",{}).get("heuristic",{}).get("lf",{})
            boats = lf.get("boat_proximity",{})
            n = boats.get("vertical_line_count",0)
        except:
            n = 0
        
        state = "B" if n > 0 else "."
        if prev is not None and prev != state:
            transitions.append(f"{p.stem[:15]} {prev}->{state}({n})")
        prev = state
        if n > 0:
            boat_count += 1
            print(f" B {p.stem[:25]} {n:2d}l")
    
    total = len(pngs)
    print(f" [{d.name[:20]} boats={boat_count}/{total} ({boat_count*100//max(total,1)}%)]")
    if transitions:
        for t in transitions:
            print(f"   T {t}")
    print()
