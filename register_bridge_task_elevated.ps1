# register_bridge_task_elevated.ps1
# Self-elevates, then registers the scheduled task as SYSTEM.
# Re-running overwrites the existing task.

$script = @'
$ErrorActionPreference = "Stop"
$Action = New-ScheduledTaskAction `
    -Execute "C:\Python314\pythonw.exe" `
    -Argument "C:\Users\casey\tzpro-agent\nmea_bridge.py --port COM6 --baud 4800" `
    -WorkingDirectory "C:\Users\casey\tzpro-agent"

$Trigger = New-ScheduledTaskTaskTrigger -AtStartup
$Trigger.Delay = "PT30S"

$Principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName "TZPro NMEA Bridge" `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Settings $Settings `
    -Description "NMEA0183 bridge for TZ Pro: COM6 -> 127.0.0.1:6006 (raw TCP) + 127.0.0.1:8654 (HTTP/SSE). Restarts on failure." `
    -Force

Write-Host "REGISTERED OK"
Get-ScheduledTask -TaskName "TZPro NMEA Bridge" | Format-List TaskName, State
'@

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Not elevated. Relaunching as Administrator..."
    Start-Process PowerShell -Verb RunAs -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $script
} else {
    Invoke-Expression $script
}