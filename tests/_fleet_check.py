"""Quick fleet check - working path for deployment."""
import json, subprocess
from pathlib import Path

HERE = Path(__file__).parent.resolve()

# Check python processes
ps = subprocess.run(
    ['powershell', '-Command',
     'Get-CimInstance Win32_Process | Where-Object {$_.Name -match "python"} | Select-Object ProcessId,CommandLine | ConvertTo-Csv -NoTypeInformation'],
    capture_output=True, text=True, timeout=10
)

for line in ps.stdout.strip().splitlines():
    if not line or line.startswith('"ProcessId"'):
        continue
    parts = line.split('","')
    if len(parts) >= 2:
        pid = parts[0].strip('"')
        cmd = parts[1].strip('"')[:90]
        for label in ['analyzer', 'capture_v3', 'nmea_bridge', 'hermitd']:
            if label in cmd.lower():
                print(f"  {label:15s} PID {pid:>6s} UP")
                break

# Count today's captures
today = sorted(Path("captures/v3/2026-07-18_5546.779N_13141.210W").glob("*.png"))
print(f"\nToday: {len(today)} captures")
if today:
    js = json.loads(today[-1].with_suffix(".json").read_text("utf-8"))
    lf = js["analysis"]["heuristic"]["lf"]
    b = lf.get("boat_proximity", {})
    n = b.get("vertical_line_count", 0)
    s = b.get("severity", "none")
    print(f"Latest: {today[-1].stem[:15]}... boats={n} ({s})")
