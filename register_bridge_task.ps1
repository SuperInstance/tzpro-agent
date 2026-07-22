$Action = New-ScheduledTaskAction `
    -Execute "C:\Python314\pythonw.exe" `
    -Argument "C:\Users\casey\tzpro-agent\nmea_bridge.py --port COM6 --baud 4800" `
    -WorkingDirectory "C:\Users\casey\tzpro-agent"

$Trigger = New-ScheduledTaskTrigger -AtStartup
$Trigger.Delay = "PT30S"

$Principal = New-ScheduledTaskPrincipal `
    -UserId "casey" `
    -LogonType S4U `
    -RunLevel Highest

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -DontStopOnIdleEnd `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -MultipleInstances IgnoreNew `
    -Priority 5

Register-ScheduledTask `
    -TaskName "TZPro NMEA Bridge" `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Settings $Settings `
    -Description "NMEA0183 bridge for TimeZero Professional. Reads COM6 and serves raw TCP on 127.0.0.1:6006 plus HTTP/SSE JSON on 127.0.0.1:8654. Starts at boot (30s delay), restarts on failure every 60s. TZ Pro connects to 127.0.0.1:6006." `
    -Force `
    -ErrorAction Stop

Write-Host "Task registered successfully."
Get-ScheduledTask -TaskName "TZPro NMEA Bridge" | Format-List TaskName, State, Principal, Author