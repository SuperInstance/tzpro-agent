#!/usr/bin/env python3
"""
_tool_server.py — Persistent Python shell that survives MCP transport issues.
Run once, then send commands to it via a simple FIFO file.

Usage:
  python _tool_server.py              # Start server (listens on stdin)
  python _tool_server.py exec "cmd"   # One-shot exec with output to stdout

This avoids the MCP transport corruption that happens when large output
streams through the Telegram channel renderer.
"""
import sys, os, json, subprocess, shlex, time
from pathlib import Path

HERE = Path(__file__).parent.resolve()

def run_command(cmd: str) -> dict:
    """Run a shell command and return results."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=120,
            cwd=str(HERE)
        )
        return {
            "status": "ok",
            "returncode": result.returncode,
            "stdout": result.stdout[:50000],
            "stderr": result.stderr[:50000],
        }
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "stdout": "", "stderr": "Command timed out"}
    except Exception as e:
        return {"status": "error", "stdout": "", "stderr": str(e)}

def run_python(code: str) -> dict:
    """Run a Python snippet and return results."""
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=120,
            cwd=str(HERE)
        )
        return {
            "status": "ok",
            "returncode": result.returncode,
            "stdout": result.stdout[:50000],
            "stderr": result.stderr[:50000],
        }
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "stdout": "", "stderr": "Command timed out"}
    except Exception as e:
        return {"status": "error", "stdout": "", "stderr": str(e)}

def git_pull_push(message: str = "auto-update"):
    """Git add/commit/push."""
    try:
        subprocess.run(["git", "add", "-A"], cwd=str(HERE), capture_output=True, timeout=10)
        subprocess.run(["git", "commit", "-m", message], cwd=str(HERE), capture_output=True, timeout=10)
        push = subprocess.run(["git", "push"], cwd=str(HERE), capture_output=True, text=True, timeout=30)
        return {"status": "ok", "output": push.stdout[:2000] + push.stderr[:2000]}
    except Exception as e:
        return {"status": "error", "output": str(e)}

if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "exec":
        result = run_command(" ".join(sys.argv[2:]))
        json.dump(result, sys.stdout, indent=2)
    elif len(sys.argv) >= 2 and sys.argv[1] == "python":
        result = run_python(" ".join(sys.argv[2:]))
        json.dump(result, sys.stdout, indent=2)
    elif len(sys.argv) >= 2 and sys.argv[1] == "git":
        msg = " ".join(sys.argv[2:]) or "auto-update"
        result = git_pull_push(msg)
        json.dump(result, sys.stdout, indent=2)
    else:
        # Interactive mode: read commands from stdin
        print("Tool server ready. Send JSON commands on stdin.", flush=True)
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            if line == "exit":
                break
            try:
                cmd = json.loads(line)
                if cmd.get("type") == "exec":
                    result = run_command(cmd["command"])
                elif cmd.get("type") == "python":
                    result = run_python(cmd["code"])
                elif cmd.get("type") == "git":
                    result = git_pull_push(cmd.get("message", "auto-update"))
                else:
                    result = {"status": "error", "stderr": f"Unknown command type: {cmd.get('type')}"}
                json.dump(result, sys.stdout)
                print()
                sys.stdout.flush()
            except json.JSONDecodeError:
                json.dump({"status": "error", "stderr": "Invalid JSON"}, sys.stdout)
                print()
                sys.stdout.flush()
