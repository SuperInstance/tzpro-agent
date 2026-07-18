#!/usr/bin/env python3
"""
_rescue_tools.py — Self-healing script for MCP tool failures.

The problem: DesktopCommander MCP connection gets corrupted by large output
(ANSI escapes, image data, OpenCV windows). Simple commands work but anything
producing real output returns "(see attached image)."

This script clean up the zombie processes that cause corruption:
  - OpenCV highgui windows that got stuck
  - Orphaned pythonw.exe instances
  - Python processes with OpenCV that have been running too long

Usage:
  python _rescue_tools.py             # Full rescue: scan + kill zombies
  python _rescue_tools.py --scan      # Report only, don't kill
  python _rescue_tools.py --kill      # Kill identified zombies
  python _rescue_tools.py --restart   # Restart the OpenClaw gateway
"""
import sys
import os
import subprocess
import time
import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).parent.resolve()
MAX_PYTHON_AGE_MINUTES = 5


def run_ps(output_format="csv"):
    """Run PowerShell to list processes. Returns list of dicts."""
    script = """
    Get-Process | Select-Object Id, ProcessName, StartTime, MainWindowTitle |
    Where-Object { $_.ProcessName -like '*python*' -or $_.ProcessName -like '*pythonw*' } |
    ConvertTo-Json
    """
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=30
        )
        return result.stdout.strip()
    except Exception as e:
        print(f"ERROR running ps: {e}", file=sys.stderr)
        return ""


def check_opencv_windows():
    """Check for processes that might have OpenCV highgui windows open."""
    # Windows: enumerate top-level windows looking for OpenCV class names
    script = """
    Add-Type @"
    using System;
    using System.Runtime.InteropServices;
    using System.Text;
    public class WinAPI {
        [DllImport("user32.dll")]
        public static extern bool EnumWindows(IntPtr lpEnumFunc, IntPtr lParam);
        [DllImport("user32.dll")]
        public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
        [DllImport("user32.dll")]
        public static extern int GetClassName(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
        [DllImport("user32.dll")]
        public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);
    }
"@

    $windows = @()
    $sb = [System.Text.StringBuilder]::new(256)
    $cb = [System.Text.StringBuilder]::new(256)

    $callback = {
        param($hwnd, $lparam)
        $sb.Clear(); $cb.Clear()
        [WinAPI]::GetWindowText($hwnd, $sb, 256)
        [WinAPI]::GetClassName($hwnd, $cb, 256)
        $title = $sb.ToString()
        $class = $cb.ToString()
        $pid = 0
        [WinAPI]::GetWindowThreadProcessId($hwnd, [ref]$pid) | Out-Null
        if ($title -or $class -like "*OpenCV*" -or $class -like "*HighGUI*" -or $class -like "*Imshow*") {
            $script:windows += [PSCustomObject]@{
                PID = $pid
                Title = $title
                Class = $class
                HWnd = $hwnd
            }
        }
    }

    $delegate = [WinAPI+EnumWindowsDelegate]$callback
    [WinAPI]::EnumWindows($delegate, [IntPtr]::Zero)
    $windows | ConvertTo-Json -Compress
    """
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=30
        )
        output = result.stdout.strip()
        if output:
            return json.loads(output)
    except Exception as e:
        print(f"ERROR enumerating windows: {e}", file=sys.stderr)
    return []


def kill_process(pid, name="unknown"):
    """Kill a process by PID."""
    try:
        subprocess.run(
            ["taskkill", "/f", "/pid", str(pid)],
            capture_output=True, timeout=10
        )
        print(f"  ✓ Killed {name} (PID {pid})")
        return True
    except Exception as e:
        print(f"  ✗ Failed to kill {name} (PID {pid}): {e}")
        return False


def kill_by_name(name):
    """Kill all processes matching a name."""
    try:
        subprocess.run(
            ["taskkill", "/f", "/im", name],
            capture_output=True, timeout=10
        )
        print(f"  ✓ Killed all {name}")
        return True
    except Exception as e:
        print(f"  ✗ Failed to kill {name}: {e}")
        return False


def find_zombie_python_processes():
    """
    Find Python processes that:
    1. Have been running >5 minutes AND have OpenCV/highgui in loaded modules
    2. Are pythonw.exe without a parent console window
    """
    zombies = []

    # Check pythonw.exe
    script = """
    Get-Process -Name pythonw -ErrorAction SilentlyContinue | ForEach-Object {
        $parent = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").ParentProcessId
        $parentProc = Get-Process -Id $parent -ErrorAction SilentlyContinue
        $startTime = $_.StartTime
        $elapsed = if ($startTime) { [math]::Round(((Get-Date) - $startTime).TotalMinutes, 1) } else { -1 }
        [PSCustomObject]@{
            PID = $_.Id
            Name = $_.ProcessName
            ParentPid = $parent
            ParentName = if ($parentProc) { $parentProc.ProcessName } else { "none" }
            ElapsedMinutes = $elapsed
            HasWindow = ($_.MainWindowTitle -ne "")
            IsOrphaned = ($parentProc -eq $null -or $parentProc.ProcessName -notlike '*cmd*' -and $parentProc.ProcessName -notlike '*conhost*')
        }
    } | ConvertTo-Json -Compress
    """
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=30
        )
        output = result.stdout.strip()
        if output:
            procs = json.loads(output) if isinstance(json.loads(output), list) else [json.loads(output)]
            for p in procs:
                if p.get("IsOrphaned", False):
                    zombies.append({
                        "pid": p["PID"],
                        "name": p["Name"],
                        "reason": f"orphaned pythonw (parent: {p['ParentName']}, running {p['ElapsedMinutes']}min)",
                        "source": "pythonw_check"
                    })
    except Exception:
        pass

    # Check python.exe with OpenCV
    script = """
    Get-Process -Name python -ErrorAction SilentlyContinue | ForEach-Object {
        $pid = $_.Id
        $startTime = $_.StartTime
        $elapsed = if ($startTime) { [math]::Round(((Get-Date) - $startTime).TotalMinutes, 1) } else { -1 }
        $modules = @()
        try {
            $modules = $_.Modules | Where-Object { $_.ModuleName -like '*opencv*' -or $_.ModuleName -like '*cv2*' -or $_.ModuleName -like '*highgui*' } | Select-Object -ExpandProperty ModuleName
        } catch {}
        [PSCustomObject]@{
            PID = $pid
            Name = $_.ProcessName
            ElapsedMinutes = $elapsed
            HasOpencv = ($modules.Count -gt 0)
            MainWindow = $_.MainWindowTitle
        }
    } | ConvertTo-Json -Compress
    """
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=30
        )
        output = result.stdout.strip()
        if output:
            procs = json.loads(output) if isinstance(json.loads(output), list) else [json.loads(output)]
            for p in procs:
                if p.get("HasOpencv", False) and p.get("ElapsedMinutes", 0) > MAX_PYTHON_AGE_MINUTES:
                    zombies.append({
                        "pid": p["PID"],
                        "name": p["Name"],
                        "reason": f"python + OpenCV running {p['ElapsedMinutes']}min (>{MAX_PYTHON_AGE_MINUTES}min)",
                        "source": "opencv_check"
                    })
    except Exception:
        pass

    return zombies


def find_opencv_windows():
    """Find windows that look like OpenCV imshow debris."""
    windows = check_opencv_windows()
    opencv_windows = []
    for w in (windows if isinstance(windows, list) else []):
        if ("OpenCV" in str(w.get("Class", "")) or
            "HighGUI" in str(w.get("Class", "")) or
            "Imshow" in str(w.get("Class", "")) or
            "cv::" in str(w.get("Title", ""))):
            opencv_windows.append(w)
    return opencv_windows


def restart_gateway():
    """Restart the OpenClaw gateway."""
    print("\n  Restarting OpenClaw gateway...")
    try:
        result = subprocess.run(
            ["openclaw", "gateway", "restart"],
            capture_output=True, text=True, timeout=30
        )
        print(f"  Gateway restart: {result.stdout.strip()}")
        if result.returncode != 0:
            print(f"  stderr: {result.stderr.strip()}")
        return result.returncode == 0
    except FileNotFoundError:
        print("  ✗ openclaw CLI not found on PATH")
        return False
    except Exception as e:
        print(f"  ✗ Failed to restart gateway: {e}")
        return False


def scan():
    """Scan for zombies, report only."""
    print("=" * 60)
    print(" ZOMBIE PROCESS SCAN")
    print(f" {datetime.now().isoformat()}")
    print("=" * 60)

    # 1. Check for OpenCV windows
    print("\n[1] OpenCV/highgui windows:")
    cv_windows = find_opencv_windows()
    if cv_windows:
        for w in cv_windows:
            print(f"  ⚠ PID {w.get('PID')}: \"{w.get('Title')}\" class={w.get('Class')}")
    else:
        print("  ✓ No OpenCV windows found")

    # 2. Check for zombie Python processes
    print(f"\n[2] Python processes ({MAX_PYTHON_AGE_MINUTES}min+ OpenCV / orphaned pythonw):")
    zombies = find_zombie_python_processes()
    if zombies:
        for z in zombies:
            print(f"  ⚠ PID {z['pid']}: {z['reason']}")
    else:
        print("  ✓ No zombie Python processes found")

    # 3. Quick pythonw check
    print("\n[3] All pythonw.exe processes:")
    try:
        result = subprocess.run(
            ["tasklist", "/fi", "imagename eq pythonw.exe", "/fo", "csv", "/nh"],
            capture_output=True, text=True, timeout=10
        )
        lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
        if lines:
            for line in lines:
                print(f"  {line}")
        else:
            print("  ✓ No pythonw processes")
    except Exception as e:
        print(f"  Error: {e}")

    return {
        "opencv_windows": len(cv_windows),
        "zombie_pythons": len(zombies),
        "details": {
            "windows": cv_windows,
            "zombies": zombies
        }
    }


def kill():
    """Kill identified zombies."""
    print("=" * 60)
    print(" KILLING ZOMBIE PROCESSES")
    print(f" {datetime.now().isoformat()}")
    print("=" * 60)

    killed = 0

    # 1. Kill pythonw.exe
    print("\n[1] Killing all pythonw.exe:")
    result = subprocess.run(
        ["taskkill", "/f", "/im", "pythonw.exe"],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode == 0:
        print(f"  ✓ pythonw.exe terminated")
        killed += 1
    else:
        if "not found" in result.stderr.lower() or "no tasks" in result.stderr.lower():
            print("  ✓ No pythonw.exe running")
        else:
            print(f"  ⚠ {result.stderr.strip()}")

    # 2. Kill zombie Python processes
    print("\n[2] Killing zombie Python processes:")
    zombies = find_zombie_python_processes()
    for z in zombies:
        if kill_process(z["pid"], f"{z['name']} ({z['reason']})"):
            killed += 1

    time.sleep(2)
    print(f"\n Done. Killed {killed} process(es).")

    return killed


def main():
    parser = argparse.ArgumentParser(description="Self-healing tools for MCP tool failures")
    parser.add_argument("--scan", action="store_true", help="Scan for zombies only, don't kill")
    parser.add_argument("--kill", action="store_true", help="Kill identified zombie processes")
    parser.add_argument("--restart", action="store_true", help="Restart OpenClaw gateway")
    args = parser.parse_args()

    # Default: scan + kill
    if not any([args.scan, args.kill, args.restart]):
        scan()
        print("\n" + "-" * 60)
        print(" Proceeding to kill...")
        print("-" * 60)
        kill()
        return

    if args.scan:
        scan()

    if args.kill:
        kill()

    if args.restart:
        restart_gateway()


if __name__ == "__main__":
    main()
