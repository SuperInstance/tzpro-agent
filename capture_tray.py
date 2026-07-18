#!/usr/bin/env python3
"""capture_tray.py — System tray toggle for tzpro-agent capture daemon.

Sits in the notification area (bottom right). Green = capturing, gray = stopped.
Right-click menu to Start/Stop/Quit.

Run with:  pythonw.exe capture_tray.py
(or it will auto-restart capture_v3.py on boot if launched via startup)
"""

import os
import sys
import signal
import subprocess
import threading
import time
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw

import pystray

# ── Config ─────────────────────────────────────────────────────────
WORKSPACE = Path(__file__).parent.resolve()
CAPTURE_SCRIPT = WORKSPACE / "capture_v3.py"
PID_FILE = WORKSPACE / ".capture_tray_pid"

PYTHON = sys.executable  # e.g. C:\Python314\python.exe
PYTHONW = PYTHON.replace("python.exe", "pythonw.exe")

# ── State ──────────────────────────────────────────────────────────
_process: subprocess.Popen | None = None
_lock = threading.Lock()
_icon: pystray.Icon | None = None


# ── Icon Generation ────────────────────────────────────────────────
def _make_icon(green: bool) -> Image.Image:
    """32x32 RGBA icon — camera lens dot (green=on, gray=off)."""
    size = 32
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Outer ring (dark)
    draw.ellipse([2, 2, 29, 29], fill=(60, 60, 60, 255))
    # Inner
    color = (0, 200, 80, 255) if green else (140, 140, 140, 255)
    draw.ellipse([6, 6, 25, 25], fill=color)
    # Center dot
    if green:
        draw.ellipse([12, 12, 19, 19], fill=(180, 255, 200, 255))
    return img


# ── Capture Process Management ─────────────────────────────────────
def _start_capture() -> str:
    global _process
    with _lock:
        if _process and _process.poll() is None:
            return "already running"

        log_path = WORKSPACE / "capture_tray.log"
        try:
            fd = open(log_path, "a")
        except Exception:
            fd = subprocess.DEVNULL

        _process = subprocess.Popen(
            [PYTHON, str(CAPTURE_SCRIPT)],
            cwd=str(WORKSPACE),
            stdout=fd,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        # Write PID
        try:
            PID_FILE.write_text(str(_process.pid))
        except Exception:
            pass
        return "started"


def _stop_capture() -> str:
    global _process
    with _lock:
        if _process is None or _process.poll() is not None:
            if _process and _process.poll() is not None:
                _process = None
            return "not running"

        pid = _process.pid
        try:
            _process.terminate()
            try:
                _process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _process.kill()
                _process.wait(timeout=3)
        except Exception:
            pass
        _process = None
        # Clean PID file
        try:
            os.remove(str(PID_FILE))
        except Exception:
            pass
        return "stopped"


def _is_running() -> bool:
    global _process
    if _process is None:
        return False
    ret = _process.poll()
    if ret is not None:
        with _lock:
            _process = None
        return False
    return True


def _toggle():
    if _is_running():
        msg = _stop_capture()
    else:
        msg = _start_capture()
    _refresh_menu()
    if _icon:
        _icon.icon = _make_icon(_is_running())


def _refresh_menu():
    global _icon
    if _icon is None:
        return
    running = _is_running()
    status_text = "● Running" if running else "○ Stopped"
    _icon.menu = pystray.Menu(
        pystray.MenuItem(f"Capture: {status_text}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Stop" if running else "Start", _toggle),
        pystray.MenuItem("Run Once (oneshot)", _run_oneshot),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", _quit),
    )


def _run_oneshot():
    subprocess.Popen(
        [PYTHON, str(CAPTURE_SCRIPT), "--oneshot"],
        cwd=str(WORKSPACE),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _quit(icon: pystray.Icon):
    _stop_capture()
    icon.stop()


# ── Main ────────────────────────────────────────────────────────────
def main():
    global _icon

    # Start capture immediately on launch
    _start_capture()

    icon_img = _make_icon(True)
    _icon = pystray.Icon(
        "capture_tray",
        icon_img,
        title="tzpro-agent Capture",
        menu=pystray.Menu(
            pystray.MenuItem("Capture: ● Running", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Stop", _toggle),
            pystray.MenuItem("Run Once (oneshot)", _run_oneshot),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", _quit),
        ),
    )

    # If PID file exists from previous crash, capture already started above
    # Clean stale PID if capture actually failed
    try:
        old_pid = int(PID_FILE.read_text().strip()) if PID_FILE.exists() else 0
        if old_pid:
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x0400, False, old_pid)
            if not h:
                PID_FILE.unlink(missing_ok=True)
            else:
                ctypes.windll.kernel32.CloseHandle(h)
    except Exception:
        pass

    _icon.run()


if __name__ == "__main__":
    main()
