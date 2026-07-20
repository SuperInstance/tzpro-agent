# ============================================================================
# cascade_watchdog.ps1
#
# Watchdog for the tzpro-cascade scheduled task.
#
#   - Reads $env:TZPRO_WORKSPACE\cascade_out\heartbeat.json
#     (defaults to C:\Users\casey\.openclaw\workspace\tzpro-agent)
#   - Parses ts_utc from the JSON.
#   - If the heartbeat is older than 180 seconds, restarts the
#     'tzpro-cascade' scheduled task (Stop, then Start).
#   - Logs every action to scripts\watchdog.log with a timestamp.
#
# Intended to be invoked every 2 minutes by the 'tzpro-cascade-watchdog'
# scheduled task (registered by install_cascade_task.ps1), but is also
# safe to run by hand for testing:
#
#     powershell -NoProfile -ExecutionPolicy Bypass -File scripts\cascade_watchdog.ps1
#
# Exit codes:
#     0  = heartbeat fresh, no action needed (or restart succeeded)
#     2  = heartbeat stale and restart attempted
#     3  = heartbeat missing/unreadable
# ============================================================================

$ErrorActionPreference = 'Stop'

# ----- Configuration --------------------------------------------------------
$DefaultWorkspace = 'C:\Users\casey\.openclaw\workspace\tzpro-agent'
$StaleThresholdSeconds = 180
$TaskName = 'tzpro-cascade'

# Resolve workspace
$Workspace = $env:TZPRO_WORKSPACE
if ([string]::IsNullOrWhiteSpace($Workspace)) {
    $Workspace = $DefaultWorkspace
}

# Locate this script (so we can put watchdog.log next to it, regardless of CWD)
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogFile   = Join-Path $ScriptDir 'watchdog.log'

function Write-Log {
    param([string] $Message)
    $stamp = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
    $line  = "[$stamp] $Message"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

Write-Log "watchdog tick | workspace=$Workspace threshold=${StaleThresholdSeconds}s task=$TaskName"

$HeartbeatPath = Join-Path $Workspace 'cascade_out\heartbeat.json'

if (-not (Test-Path $HeartbeatPath)) {
    Write-Log "HEARTBEAT MISSING at $HeartbeatPath"
    exit 3
}

# Parse JSON
try {
    $raw = Get-Content -Path $HeartbeatPath -Raw -Encoding UTF8
    $obj = $raw | ConvertFrom-Json -ErrorAction Stop
} catch {
    Write-Log "HEARTBEAT UNREADABLE: $($_.Exception.Message)"
    exit 3
}

$tsUtc = $obj.ts_utc
if ([string]::IsNullOrWhiteSpace($tsUtc)) {
    Write-Log "HEARTBEAT MALFORMED: missing ts_utc"
    exit 3
}

# Parse timestamp (accepts ISO 8601 with or without trailing Z)
try {
    $clean = $tsUtc
    if ($clean -match '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$') {
        $clean = $clean + 'Z'   # PowerShell's [DateTime] treats no-Z as local; force UTC
    }
    $lastSeen = [DateTime]::Parse(
        $clean,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::AssumeUniversal -bor `
        [System.Globalization.DateTimeStyles]::AdjustToUniversal
    )
} catch {
    Write-Log "HEARTBEAT MALFORMED: cannot parse ts_utc='$tsUtc' ($($_.Exception.Message))"
    exit 3
}

$nowUtc      = (Get-Date).ToUniversalTime()
$ageSeconds  = [int]([math]::Round(($nowUtc - $lastSeen).TotalSeconds))

Write-Log "heartbeat ts_utc=$tsUtc age=${ageSeconds}s"

if ($ageSeconds -le $StaleThresholdSeconds) {
    Write-Log "OK heartbeat fresh"
    exit 0
}

# ----- Heartbeat stale -> restart the task ----------------------------------
Write-Log "STALE heartbeat (age=${ageSeconds}s > ${StaleThresholdSeconds}s) -> restarting $TaskName"

$stopOk  = $false
$startOk = $false

try {
    $stopOut = schtasks.exe /End /TN "$TaskName" 2>&1
    if ($LASTEXITCODE -eq 0) {
        $stopOk = $true
        Write-Log "schtasks /End /TN $TaskName -> OK"
    } else {
        # /End returns non-zero if the task isn't currently running. That's fine.
        Write-Log "schtasks /End /TN $TaskName -> not running or non-fatal ($stopOut)"
        $stopOk = $true
    }
} catch {
    Write-Log "schtasks /End FAILED: $($_.Exception.Message)"
}

try {
    $startOut = schtasks.exe /Run /TN "$TaskName" 2>&1
    if ($LASTEXITCODE -eq 0) {
        $startOk = $true
        Write-Log "schtasks /Run /TN $TaskName -> OK"
    } else {
        Write-Log "schtasks /Run /TN $TaskName -> FAILED: $startOut"
    }
} catch {
    Write-Log "schtasks /Run FAILED: $($_.Exception.Message)"
}

if ($startOk) {
    Write-Log "RESTART COMPLETE for $TaskName"
    exit 2
} else {
    Write-Log "RESTART FAILED for $TaskName"
    exit 4
}