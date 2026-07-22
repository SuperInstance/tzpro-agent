"""start_stack.py — detached launcher for the tzpro-agent stack.

Used because PowerShell Start-Process on this box hangs the calling
shell even with -PassThru. Python's Popen with DETACHED_PROCESS and
CREATE_NEW_PROCESS_GROUP returns control immediately.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent
os.environ["TZPRO_WORKSPACE"] = str(WORKSPACE)
os.environ["PYTHONPATH"] = str(WORKSPACE)
LOGS = WORKSPACE / "logs"
LOGS.mkdir(exist_ok=True)

DETACHED = 0x00000008
NEW_GROUP = 0x00000200

PROCS = [
    ("capture_v3", [sys.executable, "capture_v3.py"]),
    ("cascade",    [sys.executable, "-m", "cascade.daemon"]),
    ("panel",      [sys.executable, "-m", "panel.serve", "--port", "8081"]),
]

for name, argv in PROCS:
    out = LOGS / f"{name}.out.log"
    err = LOGS / f"{name}.err.log"
    print(f"launching {name}: {' '.join(argv)}")
    p = subprocess.Popen(
        argv,
        cwd=str(WORKSPACE),
        stdout=out.open("wb"),
        stderr=err.open("wb"),
        creationflags=DETACHED | NEW_GROUP,
        close_fds=True,
    )
    print(f"  PID {p.pid}  logs: {out.name}, {err.name}")
    time.sleep(2)

print()
print("=== stack launched ===")
print("verify:  Get-Process python  (look for capture_v3, cascade, panel)")
print("panel:   http://127.0.0.1:8081/")
print("logs:    .\\logs\\")
