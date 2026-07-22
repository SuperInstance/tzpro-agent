@echo off
REM restart_bridge.bat - Single-command restart of the NMEA bridge.
REM Use this any time the bridge dies, TZ Pro can't see GPS on TCP:6006,
REM or after you reboot the computer.

setlocal
set BRIDGE_DIR=C:\Users\casey\tzpro-agent
set BRIDGE_SCRIPT=nmea_bridge.py
set BRIDGE_PORT=COM6
set BRIDGE_BAUD=4800

echo ## Killing any stale nmea_bridge processes...
taskkill /f /im pythonw.exe /fi "WINDOWTITLE eq NMEA Bridge*" 2>nul
REM Also kill anything bound to 6006 / 8654 (last-resort safety net).
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":6006.*LISTENING"') do (
  echo ## Killing stale listener on :6006 PID %%P
  taskkill /f /pid %%P 2>nul
)
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8654.*LISTENING"') do (
  echo ## Killing stale listener on :8654 PID %%P
  taskkill /f /pid %%P 2>nul
)
timeout /t 2 /nobreak >nul

echo ## Starting nmea_bridge on %BRIDGE_PORT% @ %BRIDGE_BAUD% baud...
cd /d "%BRIDGE_DIR%"
start "" pythonw "%BRIDGE_SCRIPT%" --port %BRIDGE_PORT% --baud %BRIDGE_BAUD%

timeout /t 3 /nobreak >nul

REM Quick readiness probe.
echo ## Probing HTTP /ready ...
curl -s --max-time 3 http://127.0.0.1:8654/ready
echo.
echo ## Done. Bridge should be live. TZ Pro connects to 127.0.0.1:6006.
endlocal