@echo off
REM restart_services.bat — Restart tzpro-agent background services
REM Kills stuck pythonw processes, restarts analyzer and capture

echo ## Killing stuck pythonw.exe...
taskkill /f /im pythonw.exe 2>nul
timeout /t 2 /nobreak >nul

echo ## Starting analyzer.py...
cd /d C:\Users\casey\.openclaw\workspace\tzpro-agent
start "" pythonw analyzer.py

echo ## Starting capture_v3.py...
start "" pythonw capture_v3.py

echo ## Done.
