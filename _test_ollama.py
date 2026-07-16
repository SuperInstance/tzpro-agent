"""Test: terse prompt to avoid deep thinking."""
import json
import urllib.request

prompt = (
    "F/V EILEEN at 55.79N 131.53W, depth 67fm, gear clearance 19fm, "
    "forward profile shallowing 65->60fm, alert: will cross 48fm contour "
    "in 0.54nm, 2 anomaly events logged.\n"
    "One-sentence monologue note:"
)

payload = json.dumps({
    "model": "qwen3:4b",
    "prompt": prompt,
    "stream": False,
    "options": {"temperature": 0.5, "max_tokens": 200, "num_predict": 200},
}).encode()

req = urllib.request.Request(
    "http://127.0.0.1:11434/api/generate",
    data=payload,
    headers={"Content-Type": "application/json"},
)
import time
t0 = time.time()
with urllib.request.urlopen(req, timeout=60) as resp:
    result = json.loads(resp.read().decode())
    elapsed = time.time() - t0
    print(f"Time: {elapsed:.1f}s")
    print("Response:", repr(result.get("response", "")))
    print("Has thinking:", "thinking" in result)
