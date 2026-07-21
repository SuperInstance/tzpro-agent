# Boat Ops Runbook — F/V EILEEN

> The one doc Casey follows. Ops language, numbered steps, expected output, fix for every failure.
> Repo root: `C:\Users\casey\tzpro-agent`

## 1. The pieces running on your boat

1. **Capture tray** — TZ Pro recording window; produces `captures/v3/`.
2. **Cascade daemon** (`python -m cascade.daemon`) — M1/M10/H1 loops, writes to the twin.
3. **Watchdog** (`scripts\cascade_watchdog.ps1`) — every 2 min; restarts the daemon if `heartbeat.json` goes stale (>180s).
4. **Scrubber** (`python -m scrubber.serve`) — local web UI at `http://localhost:8080`.
5. **USB backup** (`scripts\manifest_backup.py`) — signed-bundle copy + post-hash verify.

## 2. First-time setup (in order)

1. Pull the vision model (~1.7 GB):
   ```bash
   ollama pull moondream
   ```
   *Expected:* `success`. *If it fails:* confirm Ollama desktop is running, retry.

2. PowerShell **as Administrator**:
   ```powershell
   cd C:\Users\casey\tzpro-agent
   .\scripts\install_cascade_task.ps1
   ```
   *Expected:* "Registration complete", two tasks listed. *If it throws:* not elevated — right-click → Run as administrator.

3. Set Telegram creds (User env vars):
   ```powershell
   [Environment]::SetEnvironmentVariable("TELEGRAM_BOT_TOKEN","<from @BotFather>","User")
   [Environment]::SetEnvironmentVariable("TELEGRAM_CHAT_ID","<your chat id>","User")
   ```
   Sign out/in. See §6 note re: SYSTEM user.

4. Verify heartbeat ticks:
   ```powershell
   Get-Content $env:TZPRO_WORKSPACE\cascade_out\heartbeat.json
   ```
   *Expected:* `ts_utc` changing every ~60s. *If static:* daemon isn't running — run `python -m cascade.daemon` in a terminal to see the error.

## 3. Every morning (60-second check)

Should already be running: TZ Pro capture, cascade daemon (SYSTEM, auto-started), watchdog.

0. **The roster** (who's alive, one glance):
   ```bash
   python -m cascade.roster
   ```
   *Expected:* every agent `alive`, ages <120s. Anything `stale`/`dead`/`quarantined` → §6.
1. **Capture log tail** — TZ Pro window on top, Record indicator red.
2. **Heartbeat age:**
   ```powershell
   $hb = Get-Content $env:TZPRO_WORKSPACE\cascade_out\heartbeat.json | Convert-From-Json
   "$([int]((Get-Date).ToUniversalTime() - [datetime]$hb.ts_utc).TotalSeconds)s old"
   ```
   *Expected:* <180s. Older → §6.
3. **Yesterday's record count:**
   ```powershell
   (Get-ChildItem "$env:TZPRO_WORKSPACE\cascade_out\records" -Filter *.json |
     Where-Object LastWriteTime -gt (Get-Date).AddDays(-1)).Count
   ```
   *Expected:* ~6–12 per hour fished. Zero = daemon ran but saw no captures — check TZ Pro.
4. Force a briefing in your session:
   ```bash
   python -m cascade.hourly_loop --now
   ```

## 4. The scrubber

1. ```bash
   cd C:\Users\casey\tzpro-agent
   python -m scrubber.serve
   ```
   *Expected:* `serving on http://localhost:8080`.
2. Open `http://localhost:8080`. Keys: `←/→` scrub, `space` play/pause, `[`/`]` loop, `1/2/3` speed, `L` layers.
3. **Desktop shortcut** — New → Shortcut, location:
   ```
   C:\Windows\System32\cmd.exe /k "cd /d C:\Users\casey\tzpro-agent && python -m scrubber.serve && start http://localhost:8080"
   ```
   Name it `Scrubber`.

## 5. Backup (USB habit)

1. Plug USB (e.g. `E:`).
2. ```bash
   python scripts\manifest_backup.py --dest E:\tzpro-backup
   ```
   *Expected:* ends with `VERIFIED: N files, M manifest entries, 0 mismatches`. "VERIFIED" = every file re-hashed after copy and matches — silent-rot caught.
3. **Weekly:** every Sunday. Rotate two USBs; keep one off-boat.
4. **Monthly restore drill** (prove the backup is real, not just present):
   ```bash
   python scripts\restore_drill.py --source E:\tzpro-backup --sandbox %TEMP%\restore-drill
   ```
   *Expected:* `DRILL PASSED` with all files hash-verified. Any `FAILED` line names the corrupted file — that USB is suspect; re-run §5.2 to a fresh drive.

## 6. When something dies

- **Daemon down / stale heartbeat** → `schtasks /Query /TN tzpro-cascade /V /FO LIST`. If "Could not start", re-run §2 step 2. If it ran but no heartbeat, run `python -m cascade.daemon` in a terminal and read the traceback.
- **Capture stopped** → TZ Pro window lost focus/moved. Put it back on top, confirm Record red. Restart capture, recheck §3.
- **No Telegram briefings** → daemon runs as SYSTEM and can't see your User env vars. Either move the two vars to **System** environment variables (`SystemPropertiesAdvanced`), or use `python -m cascade.notify --test` in your shell to confirm creds; then trigger via §3 step 4.
- **Scrubber blank / "no day"** → `Test-Path "$env:TZPRO_WORKSPACE\meta.db"`. If `False`, the cascade never wrote — back to "daemon down".
- **Watchdog spamming restarts** → tail `scripts\watchdog.log`; repeated `STALE` = daemon crashes on boot, run it foreground.

## 7. What to NEVER delete

The value. Touching them loses the season.

1. `memory/` — learned vocab, marks, preferences.
2. `captures/` — raw sounder/screen frames (the original truth).
3. `cascade_out/` — heartbeat, M1 notes, M10 records, H1 briefings.

Also `meta.db` (the twin). To free disk, archive to USB first (§5).

## 8. Upgrading

1. ```bash
   cd C:\Users\casey\tzpro-agent
   git pull
   ```
2. ```powershell
   .\scripts\install_cascade_task.ps1
   ```
   (idempotent — safe to repeat.)
3. ```powershell
   schtasks /Run /TN tzpro-cascade
   ```
4. Re-run §3 steps 1–3 and confirm `http://localhost:8080` still loads a day.

*If anything regresses:* the watchdog restarts within 2 min; if not, §6 "daemon down".