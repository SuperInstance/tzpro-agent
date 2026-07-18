#!/usr/bin/env python3
"""fleet_monitor.py — Service health monitor for the tzpro-agent ecosystem.

Monitors running processes and ports, auto-restarts down services,
and emits fleet status reports.

Services monitored:
  - NMEA bridge    : port 6006, process_name=nmea_bridge
  - Hermitd        : port 8654, process_name=hermitd
  - capture_v3     : process_name=capture_v3
  - analyzer       : process_name=analyzer

Usage:
  python fleet_monitor.py status    — one-shot health check
  python fleet_monitor.py daemon    — monitor loop (every 60s)
  python fleet_monitor.py restart <name>  — restart a specific service
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

__all__ = ["Service", "FleetMonitor", "main"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] fleet_monitor: %(message)s",
)
log = logging.getLogger("fleet_monitor")

HERE = Path(__file__).resolve().parent
HERMIT_CRAB = HERE.parent / "hermit-crab"

# ── Platform helpers ─────────────────────────────────────────────────


def _find_python_pids() -> dict[int, str]:
    """Return {pid: command_line} for all running pythonw/python processes."""
    pids: dict[int, str] = {}
    try:
        # Windows: PowerShell Get-CimInstance (more reliable than wmic)
        ps_cmd = (
            'Get-CimInstance Win32_Process | '
            'Where-Object {$_.Name -match "python"} | '
            'Select-Object ProcessId,CommandLine | '
            'ConvertTo-Csv -NoTypeInformation'
        )
        result = subprocess.run(
            ["powershell", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.strip().splitlines():
            if not line or line.startswith('"ProcessId"'):
                continue
            # CSV: "pid","command line"
            # PowerShell wraps in quotes; comma is inside quoted field
            parts = line.split('","')
            if len(parts) >= 2:
                try:
                    pid = int(parts[0].strip().strip('"'))
                    cmd = parts[1].strip().strip('"')
                    if cmd:
                        pids[pid] = cmd
                except ValueError:
                    continue
    except Exception as exc:
        log.warning("process detection failed: %s", exc)
    return pids


def _find_process_by_name(name: str) -> list[int]:
    """Return PIDs of processes whose command line contains *name*."""
    pids: list[int] = []
    pids_by_cmd = _find_python_pids()
    for pid, cmd in pids_by_cmd.items():
        if name.lower() in cmd.lower():
            pids.append(pid)
    return pids


def _port_listening(port: int) -> bool:
    """Check if TCP port is in LISTEN state."""
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        for line in result.stdout.splitlines():
            if "LISTENING" in line and f":{port}" in line:
                return True
    except Exception:
        pass
    return False


def _process_age_s(pid: int) -> float:
    """Return process age in seconds."""
    try:
        result = subprocess.run(
            [
                "wmic",
                "path",
                "win32_process",
                "where",
                f"ProcessId={pid}",
                "get",
                "CreationDate",
                "/format:csv",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        for line in result.stdout.strip().splitlines():
            if "." in line:
                # Format: YYYYMMDDHHMMSS.mmmmmmsUTC
                parts = line.split(",")
                for p in parts:
                    p = p.strip()
                    if "." in p and len(p) > 14:
                        created = datetime.strptime(p.split(".")[0], "%Y%m%d%H%M%S")
                        delta = datetime.now() - created
                        return max(0.0, delta.total_seconds())
    except Exception:
        pass
    return 0.0


# ── Service definition ───────────────────────────────────────────────


@dataclass
class Service:
    """A monitored service in the fleet.

    Attributes:
        name:          Human-readable name.
        port:          Optional TCP port to check for LISTEN state.
        process_name:  Substring to match in pythonw command line.
        command:       Shell command to restart the service.
        cwd:           Working directory for the command.
    """

    name: str
    port: Optional[int] = None
    process_name: str = ""
    command: str = ""
    cwd: Path = HERE


# ── Pre-configured services ──────────────────────────────────────────

SERVICES: list[Service] = [
    Service(
        name="nmea_bridge",
        port=6006,
        process_name="nmea_bridge",
        command=(
            'pythonw nmea-bridge\\nmea_bridge.py --ports COM6 --num-ports 2'
        ),
        cwd=HERMIT_CRAB if HERMIT_CRAB.exists() else HERE.parent,
    ),
    Service(
        name="hermitd",
        port=8654,
        process_name="hermitd",
        command="pythonw hermitd.py",
        cwd=HERMIT_CRAB if HERMIT_CRAB.exists() else HERE.parent,
    ),
    Service(
        name="capture_v3",
        process_name="capture_v3",
        command="pythonw capture_v3.py",
        cwd=HERE,
    ),
    Service(
        name="analyzer",
        process_name="analyzer",
        command="pythonw analyzer.py",
        cwd=HERE,
    ),
]


# ── FleetMonitor ─────────────────────────────────────────────────────


@dataclass
class FleetMonitor:
    """Monitors all configured services.

    Does NOT run as a daemon itself — call check() from your loop.
    """

    services: list[Service] = field(default_factory=lambda: SERVICES)

    def check(self) -> dict[str, dict[str, Any]]:
        """Poll all services and return health dict.

        Returns:
            {service_name: {
                "status": "UP" | "DOWN",
                "pid": int or None,
                "age_s": float,
                "port_listening": bool,
            }}
        """
        health: dict[str, dict[str, Any]] = {}
        for svc in self.services:
            pids = _find_process_by_name(svc.process_name)
            up = len(pids) > 0
            pid = pids[0] if pids else None
            age = _process_age_s(pid) if pid else 0.0
            port_up = _port_listening(svc.port) if svc.port else up

            health[svc.name] = {
                "status": "UP" if up else "DOWN",
                "pid": pid,
                "age_s": round(age, 1),
                "port_listening": port_up,
            }

            log.debug(
                "check %s: %s (pid=%s, age=%.0fs, port=%s)",
                svc.name,
                "UP" if up else "DOWN",
                pid,
                age,
                port_up,
            )
        return health

    def restart(self, name: str) -> bool:
        """Restart a down service by name.

        Returns True if the service was restarted, False if not found.
        """
        svc = next((s for s in self.services if s.name == name), None)
        if svc is None:
            log.error("restart: unknown service %r", name)
            return False

        log.info("restart: launching %s → %s", name, svc.command)
        try:
            subprocess.Popen(
                svc.command,
                cwd=str(svc.cwd),
                shell=True,
                creationflags=subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NO_WINDOW,
            )
            log.info("restart: %s launched", name)
            return True
        except Exception as e:
            log.error("restart: %s failed: %s", name, e)
            return False

    def report(self) -> str:
        """Return a markdown-formatted fleet status table."""
        health = self.check()
        lines = [
            "### 🚢 Fleet Status",
            "",
            f"**Checked:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "",
            "| Service | Status | PID | Age | Port |",
            "|---------|--------|-----|-----|------|",
        ]
        for svc in self.services:
            h = health.get(svc.name, {})
            status = h.get("status", "?")
            icon = "🟢" if status == "UP" else "🔴" if status == "DOWN" else "⚪"
            pid = str(h.get("pid", "")) if h.get("pid") else "—"
            age = f"{h.get('age_s', 0):.0f}s" if h.get("pid") else "—"
            port = "🟢" if h.get("port_listening") else "🔴" if svc.port else "—"
            lines.append(
                f"| {icon} **{svc.name}** | {status} | {pid} | {age} | {port} |"
            )

        up_count = sum(
            1 for h in health.values() if h.get("status") == "UP"
        )
        total = len(self.services)
        lines.append("")
        lines.append(f"**{up_count}/{total} services UP**")

        return "\n".join(lines)

    def run_forever(self, interval_s: int = 60) -> None:
        """Daemon loop: check every *interval_s* seconds, auto-restart down services."""
        log.info("fleet_monitor daemon starting (interval=%ds)", interval_s)
        while True:
            health = self.check()
            for name, h in health.items():
                if h["status"] == "DOWN":
                    log.warning(
                        "DOWN: %s — attempting restart...", name
                    )
                    self.restart(name)
            time.sleep(interval_s)


# ── CLI ──────────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if not argv or argv[0] in ("-h", "--help", "help"):
        print("Usage: python fleet_monitor.py <command>")
        print()
        print("Commands:")
        print("  status             One-shot health check")
        print("  daemon             Monitor loop (every 60s, auto-restart)")
        print("  daemon 30          Monitor loop with 30s interval")
        print("  restart <name>     Restart a specific service")
        print("  report             Markdown-format status report")
        return 0

    monitor = FleetMonitor()

    cmd = argv[0]
    if cmd == "status":
        health = monitor.check()
        for name, h in health.items():
            status_icon = "🟢" if h["status"] == "UP" else "🔴"
            pid_info = f"pid={h['pid']}" if h["pid"] else "no pid"
            port_info = f" port={'UP' if h['port_listening'] else 'DOWN'}" if _find_process_by_name(
                next(s.process_name for s in SERVICES if s.name == name)
            ) else ""
            print(f"  {status_icon} {name:15s} {h['status']:5s}  {pid_info:12s}  age={h['age_s']:.0f}s{port_info}")

    elif cmd in ("report", "markdown"):
        print(monitor.report())

    elif cmd == "daemon":
        interval = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 60
        try:
            monitor.run_forever(interval)
        except KeyboardInterrupt:
            log.info("Daemon stopped by user.")
        except Exception:
            log.exception("Daemon crashed.")

    elif cmd == "restart":
        if len(argv) < 2:
            print("Usage: fleet_monitor.py restart <service_name>", file=sys.stderr)
            return 1
        ok = monitor.restart(argv[1])
        return 0 if ok else 1

    else:
        print(f"Unknown command: {cmd!r}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
