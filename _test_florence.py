"""Test Florence-2 on RTX 4050."""
import sys, json
sys.path.insert(0, r'C:\Users\casey\.openclaw\workspace\tzpro-agent')

from vision import load_model, analyze_sounder_vl

# Load Florence-2 on GPU
ok = load_model()
print(f"Model loaded: {ok}")

if ok:
    # Analyze a sounder crop
    from pathlib import Path
    captures = Path(r'C:\Users\casey\.openclaw\workspace\tzpro-agent\captures')
    sounders = sorted(captures.glob('*sounder*.png'))
    if sounders:
        result = analyze_sounder_vl(sounders[-1])
        print(json.dumps(result, indent=2))
    else:
        print("No sounder images found")
