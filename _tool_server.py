#!/usr/bin/env python3
"""
_tool_server.py — File-based tool execution for MCP transport safety.

The problem: DesktopCommander MCP connection gets corrupted by large output
(ANSI escapes, image data, OpenCV windows). By writing results to a file and
only returning the file path, the MCP transport never sees the large output.

Usage:
  python _tool_server.py exec "dir"     → writes .tool_output.json, prints path
  python _tool_server.py python "code"  → runs Python snippet
  python _tool_server.py git "message"  → git add/commit/push

The agent reads .tool_output.json directly, avoiding MCP transport entirely.
"""
import sys
import os
import subprocess
import json
import time
from pathlib import Path

HERE = Path(__file__).parent.resolve()
OUT = HERE / ".tool_output.json"
ENCODING = "utf-8"


def run(cmd: str, timeout: int = 120) -> dict:
    """Run a shell command, capture output, return result dict."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=str(HERE)
        )
        return {
            "ok": True,
            "rc": r.returncode,
            "out": r.stdout[:100000],
            "err": r.stderr[:10000],
            "cmd": cmd,
            "cwd": str(HERE),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "cmd": cmd}
    except FileNotFoundError:
        return {"ok": False, "error": f"command not found: {cmd.split()[0]}", "cmd": cmd}
    except Exception as e:
        return {"ok": False, "error": str(e), "cmd": cmd}


def run_python(code: str, timeout: int = 120) -> dict:
    """Run a Python snippet, capture output, return result dict."""
    try:
        r = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True,
            timeout=timeout, cwd=str(HERE)
        )
        return {
            "ok": True,
            "rc": r.returncode,
            "out": r.stdout[:100000],
            "err": r.stderr[:10000],
            "code": code,
            "cwd": str(HERE),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def git_push(message: str = "auto") -> dict:
    """Git add all, commit, push."""
    cmds = [
        ["git", "add", "-A"],
        ["git", "commit", "-m", message],
        ["git", "push"],
    ]
    results = []
    for cmd in cmds:
        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30, cwd=str(HERE)
            )
            results.append(f"[{'OK' if r.returncode == 0 else 'ERR'}] {' '.join(cmd)}")
            stdout = r.stdout.strip()
            stderr = r.stderr.strip()
            if stdout:
                results.append(f"  stdout: {stdout[:2000]}")
            if stderr:
                results.append(f"  stderr: {stderr[:2000]}")
        except subprocess.TimeoutExpired:
            results.append(f"[TIMEOUT] {' '.join(cmd)}")
        except Exception as e:
            results.append(f"[ERR] {' '.join(cmd)}: {e}")
    return {"ok": True, "steps": results}


def write_and_print(result: dict) -> None:
    """Write result to .tool_output.json and print only the file path."""
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding=ENCODING)
    # Only print the path — no large output through MCP transport
    print(str(OUT))
    # Also write a .last_command file for easy reference
    cmd_file = HERE / ".last_command"
    cmd_file.write_text(sys.argv[1] if len(sys.argv) > 1 else "none")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "exec":
        result = run(" ".join(sys.argv[2:]))
        write_and_print(result)

    elif len(sys.argv) >= 3 and sys.argv[1] == "python":
        result = run_python(" ".join(sys.argv[2:]))
        write_and_print(result)

    elif len(sys.argv) >= 2 and sys.argv[1] == "git":
        msg = " ".join(sys.argv[2:]) or "auto"
        result = git_push(msg)
        write_and_print(result)

    elif len(sys.argv) >= 2 and sys.argv[1] == "status":
        stat = {}
        stat["_tool_output_exists"] = OUT.exists()
        if OUT.exists():
            try:
                cached = json.loads(OUT.read_text(encoding=ENCODING))
                stat["_last_result_keys"] = list(cached.keys())
                stat["_last_result_ok"] = cached.get("ok")
                stat["_last_result_rc"] = cached.get("rc")
            except Exception:
                stat["_last_result"] = "corrupt"
        result = {"ok": True, "status": stat}
        write_and_print(result)

    else:
        print("Usage: python _tool_server.py exec <cmd>")
        print("       python _tool_server.py python <code>")
        print("       python _tool_server.py git <message>")
        print("       python _tool_server.py status")
