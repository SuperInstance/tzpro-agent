# start_stack.ps1 — launches the full tzpro-agent stack with the right env.
# Usage: powershell -ExecutionPolicy Bypass -File start_stack.ps1

$env:TZPRO_WORKSPACE = $PSScriptRoot
$env:PYTHONPATH = $PSScriptRoot

Write-Host "=== tzpro-agent stack starting ==="
Write-Host ("WORKSPACE: " + $env:TZPRO_WORKSPACE)

# 1. capture_v3 — screenshots DISPLAY6 every 10 min on the hour boundary
Write-Host "[1/3] launch capture_v3"
Start-Process -FilePath "python.exe" `
  -ArgumentList "capture_v3.py" `
  -WorkingDirectory $PSScriptRoot `
  -RedirectStandardOutput "logs\capture_v3.out.log" `
  -RedirectStandardError  "logs\capture_v3.err.log" `
  -WindowStyle Hidden

Start-Sleep 2

# 2. cascade daemon — M1/M10/H1/D1 + GC + heartbeat
Write-Host "[2/3] launch cascade daemon"
New-Item -ItemType Directory -Force -Path "logs" | Out-Null
Start-Process -FilePath "python.exe" `
  -ArgumentList "-m","cascade.daemon" `
  -WorkingDirectory $PSScriptRoot `
  -RedirectStandardOutput "logs\cascade.out.log" `
  -RedirectStandardError  "logs\cascade.err.log" `
  -WindowStyle Hidden

Start-Sleep 2

# 3. panel server — 3-panel localhost web console on :8081
Write-Host "[3/3] launch panel server"
Start-Process -FilePath "python.exe" `
  -ArgumentList "-m","panel.serve","--port","8081" `
  -WorkingDirectory $PSScriptRoot `
  -RedirectStandardOutput "logs\panel.out.log" `
  -RedirectStandardError  "logs\panel.err.log" `
  -WindowStyle Hidden

Start-Sleep 3

Write-Host ""
Write-Host "=== stack launched — verify with: Get-Process python ==="
Write-Host "    open http://127.0.0.1:8081/ for the day console"
Write-Host "    logs in .\logs\"
