@echo off
REM install_bridge_task.bat - one-shot installer for the NMEA bridge boot task.
REM Requires Administrator (right-click -> "Run as administrator" the first time).
REM
REM What it does:
REM   Creates "TZPro NMEA Bridge" in Task Scheduler:
REM     - Trigger: At Startup, 30s delay
REM     - Run as:  SYSTEM, Highest privileges
REM     - Action:  C:\Python314\pythonw.exe C:\Users\casey\tzpro-agent\nmea_bridge.py --port COM6 --baud 4800
REM     - Working dir: C:\Users\casey\tzpro-agent
REM     - Restart: every 60s on failure (up to 999 times)
REM
REM Re-running this with /F overwrites the existing task. Safe.

schtasks /Create /TN "TZPro NMEA Bridge" /F /SC ONSTART /DELAY 0000:30 /RU SYSTEM /RL HIGHEST ^
  /TR "\"C:\Python314\pythonw.exe\" \"C:\Users\casey\tzpro-agent\nmea_bridge.py\" --port COM6 --baud 4800" ^
  /WD "C:\Users\casey\tzpro-agent"

if errorlevel 1 (
  echo.
  echo ## FAILED. This batch must be run as Administrator.
  echo ## Right-click install_bridge_task.bat -^> Run as administrator.
  pause
  exit /b 1
)

echo.
echo ## Done. Verifying task...
schtasks /Query /TN "TZPro NMEA Bridge" /V /FO LIST
echo.
echo ## To test without rebooting, run:
echo ##   schtasks /Run /TN "TZPro NMEA Bridge"
echo ##   curl http://127.0.0.1:8654/health
echo.
pause