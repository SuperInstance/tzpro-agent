"""
panel/serve.py — three-panel console HTTP server.

Three panels, all reading the cascade_out/ directory in real time:
  P1 (M1 logs)    transient delta notes, no images, EOD-evanescent
  P2 (M10 records) canonical 10-min captures + per-record JSON
  P3 (Briefings)  H1 hourly MD + JSON, D1 daily MD + JSON

Day picker, SSE for live updates, click an M10 record to fetch the
PNG (only the 10-min canonical images exist on disk — the M1 frames
were GC'd at EOD by retention.evening_final_read).

stdlib only: http.server, sqlite3, json, pathlib, urllib.parse, asyncio.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import re
import sqlite3
import time
from collections import deque
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Lock, Thread
from typing import Any, Iterator
from urllib.parse import parse_qs, urlparse


DEFAULT_WORKSPACE = Path(r"C:\Users\casey\.openclaw\workspace\tzpro-agent")
STATIC_DIR = Path(__file__).parent / "static"


# ── Helpers ───────────────────────────────────────────────────────────────

def cascade_paths(workspace: Path) -> dict[str, Path]:
    """Resolve the cascade_out tree for a workspace.

    Mirrors cascade/config.py. We don't *import* cascade/ here because
    the panel should boot even if cascade deps are missing.
    """
    out = workspace / "cascade_out"
    return {
        "out": out,
        "records": out / "records",
        "novel": out / "minute_notes" / "novel",
        "briefings": out / "briefings",
        "captures": workspace / "captures" / "v3",
        "twin_db": workspace / "memory" / "meta.db",
    }


def _parse_iso_day(s: str) -> tuple[int, int] | None:
    """YYYY-MM-DD → start/end epoch ms (UTC)."""
    try:
        dt = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        s_ms = int(dt.timestamp() * 1000)
        e_ms = int((dt.replace(hour=23, minute=59, second=59,
                               microsecond=999999).timestamp() * 1000))
        return s_ms, e_ms
    except ValueError:
        return None


def _today_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ── Data loaders ──────────────────────────────────────────────────────────

def _list_m1_notes(paths: dict[str, Path], date: str) -> list[dict]:
    """All retained novel M1 notes for `date` (UTC).

    The 'transient' tier notes lived in cascade_out/minute_notes/<day>/
    but were GC'd at EOD by retention — they're gone, by design. Novel
    M1 notes persist under minute_notes/novel/. We surface those as the
    'change log' since they're the only durable M1 artifact, and add a
    marker row count for the GC'd ones we lost.
    """
    notes = []
    nd = paths["novel"]
    if nd.is_dir():
        for f in sorted(nd.glob("*.json")):
            try:
                n = json.loads(f.read_text())
            except Exception:
                continue
            ts = (n.get("ts_utc") or "")[:10]
            if ts == date:
                notes.append({
                    "ts_utc": n.get("ts_utc"),
                    "lat": n.get("lat"),
                    "lon": n.get("lon"),
                    "caption": n.get("caption", ""),
                    "features": n.get("features", []),
                    "novelty": n.get("novelty"),
                    "gaze": n.get("gaze"),
                    "model": n.get("model"),
                    "kind": "novel_m1",
                })
    return notes


def _list_m10_records(paths: dict[str, Path], date: str) -> list[dict]:
    """All M10 records for `date`, joined to the capture PNG path."""
    recs = []
    rd = paths["records"]
    if not rd.is_dir():
        return recs
    for f in sorted(rd.glob("*_record.json")):
        try:
            r = json.loads(f.read_text())
        except Exception:
            continue
        ts = (r.get("ts_utc") or "")[:10]
        if ts != date:
            continue

        # Find the matching capture PNG (the source-of-truth image).
        capture_id = r.get("capture_id") or r.get("frame_id")
        png_rel = None
        cd = paths["captures"]
        if cd.is_dir() and capture_id:
            for d in cd.glob(f"{date}_*"):
                if d.is_dir():
                    p = d / f"{capture_id}.png"
                    if p.is_file():
                        png_rel = str(p.relative_to(cd.parent.parent))
                        break

        recs.append({
            "ts_utc": r.get("ts_utc"),
            "capture_id": capture_id,
            "lat": r.get("lat"),
            "lon": r.get("lon"),
            "sog_kts": r.get("sog_kts"),
            "cog_deg": r.get("cog_deg"),
            "summary": r.get("summary", ""),
            "bottom_fm": r.get("bottom_fm"),
            "bottom_type": r.get("bottom_type"),
            "schools": r.get("schools", []),
            "thermocline_fm": r.get("thermocline_fm"),
            "anomalies": r.get("anomalies", []),
            "search_terms": r.get("search_terms", []),
            "png": png_rel,
            "model": r.get("model"),
        })
    return recs


_BRIEF_TS_RE = re.compile(r"briefing_(\d{8})_(\d{4})")


def _list_h1_briefings(paths: dict[str, Path], date: str) -> list[dict]:
    """H1 briefings whose file mtime falls on `date` (UTC)."""
    out = []
    bd = paths["briefings"]
    if not bd.is_dir():
        return out
    for f in sorted(bd.glob("briefing_*.md")):
        mtime = f.stat().st_mtime
        if datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d") != date:
            continue
        stem_ts = _BRIEF_TS_RE.match(f.stem)
        ts_human = None
        if stem_ts:
            try:
                dt = datetime.strptime(stem_ts.group(1) + stem_ts.group(2),
                                       "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
                ts_human = dt.strftime("%H:%M UTC")
            except ValueError:
                pass
        out.append({
            "file": f.name,
            "ts_human": ts_human or datetime.fromtimestamp(
                mtime, tz=timezone.utc).strftime("%H:%M UTC"),
            "ts_utc": datetime.fromtimestamp(mtime, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"),
            "json_file": f.with_suffix(".json").name,
        })
    return out


def _list_d1_briefs(paths: dict[str, Path], date: str) -> list[dict]:
    """Daily briefs produced *for* `date`."""
    out = []
    bd = paths["briefings"]
    if not bd.is_dir():
        return out
    for f in sorted(bd.glob(f"day_{date}.*")):
        out.append({
            "file": f.name,
            "kind": "md" if f.suffix == ".md" else "json",
        })
    return out


def _read_briefing_body(paths: dict[str, Path], file_name: str) -> str | None:
    p = paths["briefings"] / file_name
    if p.is_file():
        return p.read_text(encoding="utf-8", errors="replace")
    return None


def _read_briefing_json(paths: dict[str, Path], file_name: str) -> dict | None:
    p = paths["briefings"] / file_name
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_record_json(paths: dict[str, Path], capture_id: str) -> dict | None:
    """Read a record by capture_id (the file's primary key)."""
    p = paths["records"] / f"{capture_id}_record.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


# ── Live update stream (SSE) ──────────────────────────────────────────────

class LiveBroadcaster:
    """Tiny in-process pub-sub for SSE clients.

    Polls cascade_out/ + captures on a thread and emits 'tick' events
    when something changed. Polling, not inotify — works on Windows
    without extra deps, and the load is trivial (a few dirs).
    """
    TICK = 5.0  # seconds between scans

    def __init__(self, paths: dict[str, Path]) -> None:
        self.paths = paths
        self._state: dict[str, float] = {}
        self._clients: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = Lock()
        self._stop = False
        self._thread: Thread | None = None

    def start(self) -> None:
        self._thread = Thread(target=self._scan_forever, daemon=True,
                              name="panel-live")
        self._thread.start()

    def stop(self) -> None:
        self._stop = True

    def _scan_forever(self) -> None:
        while not self._stop:
            try:
                self._scan_once()
            except Exception:
                pass
            time.sleep(self.TICK)

    def _scan_once(self) -> None:
        new_state: dict[str, float] = {}
        for key, dirpath in (
            ("records", self.paths["records"]),
            ("novel", self.paths["novel"]),
            ("briefings", self.paths["briefings"]),
            ("captures", self.paths["captures"]),
        ):
            if not dirpath.is_dir():
                continue
            for f in dirpath.rglob("*"):
                if f.is_file():
                    new_state[str(f)] = f.stat().st_mtime

        with self._lock:
            added = [k for k in new_state if k not in self._state]
            removed = [k for k in self._state if k not in new_state]
            self._state = new_state

        if added or removed:
            self._publish({
                "kind": "tick",
                "added": len(added),
                "removed": len(removed),
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })

    async def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._clients.add(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue) -> None:
        self._clients.discard(q)

    def _publish(self, event: dict) -> None:
        # Fire-and-forget push to subscribers. Called from the polling
        # thread, so we don't await — queue.put_nowait is non-blocking.
        msg = f"data: {json.dumps(event, separators=(',', ':'))}\n\n"
        for q in list(self._clients):
            try:
                q.put_nowait(msg)
            except Exception:
                self._clients.discard(q)


# ── HTTP handler ──────────────────────────────────────────────────────────

class PanelHandler(BaseHTTPRequestHandler):
    paths: dict[str, Path] = {}
    live: LiveBroadcaster | None = None

    def address_string(self):
        # Always-localhost: no reverse-DNS, ever.
        return self.client_address[0]

    def log_message(self, fmt: str, *args) -> None:
        return

    # ── routing ────────────────────────────────────────────────────────
    def do_GET(self):
        u = urlparse(self.path)
        p = u.path.rstrip("/") or "/"
        qs = parse_qs(u.query)

        if p == "/" or p.startswith("/static/"):
            return self.serve_static(p)
        if p == "/api/stream":
            return self.handle_stream()
        if p.startswith("/api/day/"):
            return self.handle_day_api(p, qs)
        if p.startswith("/api/image/"):
            return self.handle_image(p)
        if p.startswith("/api/briefing/"):
            return self.handle_briefing(p)
        if p.startswith("/api/record/"):
            return self.handle_record(p)
        self.send_error(404, "not found")

    # ── static ────────────────────────────────────────────────────────
    def serve_static(self, path: str):
        if path == "/":
            path = "/index.html"
        rel = path.lstrip("/")
        fp = STATIC_DIR / rel
        if not fp.is_file():
            self.send_error(404)
            return
        ctype, _ = mimetypes.guess_type(str(fp))
        body = fp.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # ── data ──────────────────────────────────────────────────────────
    def handle_day_api(self, path: str, qs: dict):
        parts = path.split("/")
        # /api/day/<date>[/panel/<n>]
        if len(parts) < 4:
            return self.send_json_error(400, "expected /api/day/<date>")
        date = parts[3]
        if not _parse_iso_day(date):
            return self.send_json_error(400, "bad date")

        if len(parts) >= 6 and parts[4] == "panel":
            n = parts[5]
            if n == "1":
                payload = {"notes": _list_m1_notes(self.paths, date)}
            elif n == "2":
                payload = {"records": _list_m10_records(self.paths, date)}
            elif n == "3":
                payload = {
                    "h1": _list_h1_briefings(self.paths, date),
                    "d1": _list_d1_briefs(self.paths, date),
                }
            else:
                return self.send_json_error(400, "bad panel")
            return self.send_json(payload)

        # default summary
        notes = _list_m1_notes(self.paths, date)
        records = _list_m10_records(self.paths, date)
        h1s = _list_h1_briefings(self.paths, date)
        d1s = _list_d1_briefs(self.paths, date)
        return self.send_json({
            "date": date,
            "today_utc": _today_iso(),
            "counts": {
                "m1_novel": len(notes),
                "m10_records": len(records),
                "h1_briefings": len(h1s),
                "d1_briefs": len(d1s),
            },
        })

    def handle_image(self, path: str):
        # /api/image/<capture_id> → capture PNG
        capture_id = path.rsplit("/", 1)[-1]
        cd = self.paths["captures"]
        if not cd.is_dir():
            self.send_json_error(404, "no captures dir")
            return
        for d in cd.glob("*"):
            if d.is_dir():
                p = d / f"{capture_id}.png"
                if p.is_file():
                    body = p.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
                    return
        self.send_json_error(404, "image not found")

    def handle_briefing(self, path: str):
        # /api/briefing/<name> → text body (or JSON if .json requested)
        name = path.rsplit("/", 1)[-1]
        if name.endswith(".json"):
            data = _read_briefing_json(self.paths, name)
            if data is None:
                self.send_json_error(404, "no json"); return
            return self.send_json(data)
        body = _read_briefing_body(self.paths, name)
        if body is None:
            self.send_json_error(404, "no body"); return
        if name.endswith(".json"):
            return self.send_json(body)
        # raw md text
        b = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/markdown; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def handle_record(self, path: str):
        # /api/record/<capture_id> → full record JSON
        cid = path.rsplit("/", 1)[-1]
        data = _read_record_json(self.paths, cid)
        if data is None:
            self.send_json_error(404, "no record"); return
        self.send_json(data)

    # ── SSE ───────────────────────────────────────────────────────────
    def handle_stream(self):
        if not self.live:
            self.send_json_error(503, "no broadcaster"); return
        # Hand off to async
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            asyncio.run(self._sse_loop())
        except BrokenPipeError:
            pass

    async def _sse_loop(self):
        q = await self.live.subscribe()
        try:
            # First message: 200 OK handshake so EventSource fires onopen.
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            # Keepalive + tick delivery.
            last = time.time()
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                    self.wfile.write(msg.encode("utf-8"))
                    self.wfile.flush()
                except asyncio.TimeoutError:
                    # keepalive
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    last = time.time()
        finally:
            await self.live.unsubscribe(q)

    # ── utils ─────────────────────────────────────────────────────────
    def send_json(self, obj):
        body = json.dumps(obj, separators=(",", ":"))
        b = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def send_json_error(self, code, msg):
        self.send_json({"error": msg, "code": code})


# ── Server ─────────────────────────────────────────────────────────────────

def run_server(host: str = "127.0.0.1", port: int = 8081,
               workspace: Path | None = None) -> None:
    workspace = Path(workspace or DEFAULT_WORKSPACE)
    paths = cascade_paths(workspace)
    paths["records"].mkdir(parents=True, exist_ok=True)
    paths["briefings"].mkdir(parents=True, exist_ok=True)

    live = LiveBroadcaster(paths)
    live.start()

    PanelHandler.paths = paths
    PanelHandler.live = live

    def factory(*args, **kw):
        return PanelHandler(*args, **kw)

    server = HTTPServer((host, port), factory)
    print(f"panel server running at http://{host}:{port}")
    print(f"workspace: {workspace}")
    print("Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        live.stop()
        server.shutdown()


def main():
    p = argparse.ArgumentParser(description="tzpro-agent panel server")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8081)
    p.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    a = p.parse_args()
    run_server(a.host, a.port, a.workspace)


if __name__ == "__main__":
    main()
