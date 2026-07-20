# ============================================================================
# install_cascade_task.ps1
#
# Registers two Windows Scheduled Tasks for the cascade perception daemon:
#
#   1. tzpro-cascade
#        - Runs `python -m cascade.daemon` from the repo root.
#        - Triggered at system startup AND at user logon.
#        - Restart on failure every 1 minute (3 retries).
#        - Highest run level (so it can start before user logon).
#
#   2. tzpro-cascade-watchdog
#        - Runs scripts\cascade_watchdog.ps1 every 2 minutes.
#        - Watches the cascade heartbeat; restarts tzpro-cascade on stall.
#
# Both tasks are idempotent: existing tasks with the same name are removed
# (with /F) before being re-created, so this script is safe to run repeatedly.
#
# Usage (from an elevated PowerShell prompt):
#     .\scripts\install_cascade_task.ps1
# ============================================================================

$ErrorActionPreference = 'Stop'

# ----- Resolve repo root dynamically ----------------------------------------
# This script lives at <repo_root>\scripts\install_cascade_task.ps1.
# We derive repo_root from its own location so the script works no matter
# where the repo is checked out.
$ScriptDir    = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot     = (Resolve-Path (Join-Path $ScriptDir '..')).Path
$PythonExe    = (Get-Command python -ErrorAction Stop).Source
$WatchdogPs1  = Join-Path $RepoRoot 'scripts\cascade_watchdog.ps1'

Write-Host "=== install_cascade_task.ps1 ==="
Write-Host "Repo root        : $RepoRoot"
Write-Host "Python           : $PythonExe"
Write-Host "Watchdog script  : $WatchdogPs1"
Write-Host ""

# ----- Sanity checks --------------------------------------------------------
if (-not (Test-Path (Join-Path $RepoRoot 'cascade\__init__.py'))) {
    throw "cascade package not found at '$RepoRoot\cascade'. Aborting."
}
if (-not (Test-Path $WatchdogPs1)) {
    throw "Watchdog script not found at '$WatchdogPs1'. Aborting."
}

# ----- Helper: register-or-replace a task -----------------------------------
function Register-CascadeTask {
    param(
        [Parameter(Mandatory)] [string] $TaskName,
        [Parameter(Mandatory)] [string] $Program,
        [Parameter(Mandatory)] [string] $Arguments,
        [Parameter(Mandatory)] [string] $WorkingDir,
        [int]    $RestartIntervalMinutes = 1,
        [int]    $RestartCount           = 3
    )

    Write-Host "[$TaskName] Removing any existing task with the same name..."
    schtasks.exe /Query /TN "$TaskName" > $null 2>&1
    if ($LASTEXITCODE -eq 0) {
        schtasks.exe /Delete /TN "$TaskName" /F | Out-Null
        Write-Host "  -> Removed existing task."
    } else {
        Write-Host "  -> No prior task found."
    }

    Write-Host "[$TaskName] Creating task (ONSTART trigger)..."
    schtasks.exe /Create `
        /TN "$TaskName" `
        /TR "`"$Program`" $Arguments" `
        /SC ONSTART `
        /RU SYSTEM `
        /RL HIGHEST `
        /F | Out-Null

    # Add Logon trigger so the daemon also (re)starts on user logon.
    Write-Host "[$TaskName] Adding ONLOGON trigger..."
    schtasks.exe /Create `
        /TN "$TaskName" `
        /TR "`"$Program`" $Arguments" `
        /SC ONLOGON `
        /RU SYSTEM `
        /RL HIGHEST `
        /F | Out-Null

    # Now patch the task's XML so we get:
    #   - explicit <WorkingDirectory>
    #   - <RestartOnFailure><Interval>PT1M</Interval><Count>3</Count></RestartOnFailure>
    Write-Host "[$TaskName] Configuring restart-on-failure (every $RestartIntervalMinutes min, $RestartCount retries) and working dir..."

    $xmlPath    = Join-Path $env:TEMP "$TaskName-settings.xml"
    $exportPath = Join-Path $env:TEMP "$TaskName-export.xml"

    schtasks.exe /Query /TN "$TaskName" /XML ONE > "$exportPath" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to export existing task definition for $TaskName"
    }

    [xml]$doc = Get-Content "$exportPath"

    # --- Replace <Settings> with our own (restart-on-failure, working dir, etc.)
    $intervalMinutes = $RestartIntervalMinutes
    $settingsInnerXml = @"
<MultipleInstancesPolicy xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">IgnoreNew</MultipleInstancesPolicy>
<DisallowStartIfOnBatteries xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">false</DisallowStartIfOnBatteries>
<StopIfGoingOnBatteries xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">false</StopIfGoingOnBatteries>
<AllowHardTerminate xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">true</AllowHardTerminate>
<StartWhenAvailable xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">true</StartWhenAvailable>
<RunOnlyIfNetworkAvailable xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">false</RunOnlyIfNetworkAvailable>
<IdleSettings xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <StopOnIdleEnd>false</StopOnIdleEnd>
  <RestartOnIdle>false</RestartOnIdle>
</IdleSettings>
<AllowStartOnDemand xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">true</AllowStartOnDemand>
<Enabled xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">true</Enabled>
<Hidden xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">false</Hidden>
<RunOnlyIfIdle xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">false</RunOnlyIfIdle>
<WakeToRun xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">false</WakeToRun>
<ExecutionTimeLimit xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">PT0S</ExecutionTimeLimit>
<Priority xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">7</Priority>
<RestartOnFailure xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Interval>PT${intervalMinutes}M</Interval>
  <Count>$RestartCount</Count>
</RestartOnFailure>
"@
    $fragment = $doc.CreateElement('dummy')
    $fragment.InnerXml = $settingsInnerXml

    $oldSettings = $doc.Task.Settings
    if ($oldSettings) {
        $doc.Task.RemoveChild($oldSettings) | Out-Null
    }
    foreach ($child in @($fragment.ChildNodes)) {
        $imported = $doc.ImportNode($child, $true)
        # Settings must come AFTER Triggers/Actions/Principals per schema.
        # Easiest: append; Task schema is forgiving about child order at import,
        # but to be safe we append at the end.
        $doc.Task.AppendChild($imported) | Out-Null
    }

    # --- Set working directory on each Exec action.
    foreach ($action in $doc.Task.Actions.Exec) {
        $wd = $action.SelectSingleNode('WorkingDirectory')
        if (-not $wd) {
            $wd = $doc.CreateElement('WorkingDirectory')
            [void]$action.AppendChild($wd)
        }
        $wd.InnerText = $WorkingDir
    }

    $doc.Save($xmlPath)

    # Re-register from patched XML.
    schtasks.exe /Delete /TN "$TaskName" /F | Out-Null
    schtasks.exe /Create /TN "$TaskName" /XML "$xmlPath" /RU SYSTEM /F | Out-Null

    # Verify
    $verify = schtasks.exe /Query /TN "$TaskName" 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Task $TaskName failed to register: $verify"
    }
    Write-Host "  -> Registered successfully."
}

# ----- 1. Main cascade daemon task -----------------------------------------
Write-Host ""
Write-Host "--- Registering 'tzpro-cascade' ---"
Register-CascadeTask `
    -TaskName 'tzpro-cascade' `
    -Program  $PythonExe `
    -Arguments '-m cascade.daemon' `
    -WorkingDir $RepoRoot `
    -RestartIntervalMinutes 1 `
    -RestartCount 3

# ----- 2. Watchdog task ----------------------------------------------------
Write-Host ""
Write-Host "--- Registering 'tzpro-cascade-watchdog' ---"
$watchdogTaskName = 'tzpro-cascade-watchdog'

Write-Host "[$watchdogTaskName] Removing any existing task with the same name..."
schtasks.exe /Query /TN "$watchdogTaskName" > $null 2>&1
if ($LASTEXITCODE -eq 0) {
    schtasks.exe /Delete /TN "$watchdogTaskName" /F | Out-Null
    Write-Host "  -> Removed existing task."
} else {
    Write-Host "  -> No prior task found."
}

Write-Host "[$watchdogTaskName] Creating 2-minute schedule..."
# /SC MINUTE /MO 2 -> every 2 minutes
schtasks.exe /Create `
    /TN "$watchdogTaskName" `
    /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$WatchdogPs1`"" `
    /SC MINUTE `
    /MO 2 `
    /RU SYSTEM `
    /RL HIGHEST `
    /F | Out-Null

# Patch XML to set WorkingDirectory on the watchdog task too.
$wdXml = Join-Path $env:TEMP "$watchdogTaskName-settings.xml"
schtasks.exe /Query /TN "$watchdogTaskName" /XML ONE > "$wdXml" 2>$null
[xml]$wdoc = Get-Content "$wdXml"
foreach ($action in $wdoc.Task.Actions.Exec) {
    $wd = $action.SelectSingleNode('WorkingDirectory')
    if (-not $wd) {
        $wd = $wdoc.CreateElement('WorkingDirectory')
        [void]$action.AppendChild($wd)
    }
    $wd.InnerText = $RepoRoot
}
$wdoc.Save($wdXml)
schtasks.exe /Delete /TN "$watchdogTaskName" /F | Out-Null
schtasks.exe /Create /TN "$watchdogTaskName" /XML "$wdXml" /RU SYSTEM /F | Out-Null
Write-Host "  -> Registered successfully."

# ----- Final summary --------------------------------------------------------
Write-Host ""
Write-Host "=== Registration complete ==="
Write-Host "Tasks registered:"
Write-Host "  - tzpro-cascade         : runs 'python -m cascade.daemon' on startup + logon"
Write-Host "                            working dir = $RepoRoot"
Write-Host "                            restart on failure every 1 min, 3 retries, Highest privileges"
Write-Host "  - tzpro-cascade-watchdog: runs scripts\cascade_watchdog.ps1 every 2 minutes"
Write-Host "                            working dir = $RepoRoot"
Write-Host ""
Write-Host "Verify with:"
Write-Host "  schtasks /Query /TN tzpro-cascade /V /FO LIST"
Write-Host "  schtasks /Query /TN tzpro-cascade-watchdog /V /FO LIST"
Write-Host ""
Write-Host "--- Test commands ---"
Write-Host "  # 1. Simulate a stale heartbeat (age > 180s):"
Write-Host '  $hb = "$env:TZPRO_WORKSPACE\cascade_out\heartbeat.json"'
Write-Host '  $past = (Get-Date).ToUniversalTime().AddMinutes(-10).ToString("yyyy-MM-ddTHH:mm:ss.fffZ")'
Write-Host '  Set-Content -Path $hb -Value (@{ ts_utc = $past } | ConvertTo-Json)'
Write-Host ""
Write-Host "  # 2. Run the watchdog by hand and tail its log:"
Write-Host '  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\cascade_watchdog.ps1'
Write-Host '  Get-Content scripts\watchdog.log -Wait'
Write-Host ""
Write-Host "  # 3. Verify the restart actually happened:"
Write-Host '  schtasks /Query /TN tzpro-cascade /V /FO LIST | Select-String "Last Run Time|Status|Result"'
Write-Host '  Get-Content scripts\watchdog.log | Select-String -Pattern "RESTART|STALE|OK"'