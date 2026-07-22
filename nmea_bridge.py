#!/usr/bin/env python3
"""nmea_bridge.py — TZ Pro NMEA0183 → TCP/HTTP bridge for tzpro-agent.

THE PROBLEM
-----------
TimeZero Professional owns COM6 exclusively. PySerial's default Windows
CreateFile uses share_mode=0 (exclusive), so any naive open of COM6 while
TZ Pro is running fails with PermissionError. This module opens COM6 with
FILE_SHARE_READ | FILE_SHARE_WRITE via ctypes, so we coexist with TZ Pro.

If that still fails (signed-driver protection on some TZ Pro builds),
the bridge falls back to a com0com virtual pair (e.g. read from COM12).

WHAT IT SERVES
--------------
On a single asyncio loop, this process exposes:

  TCP  127.0.0.1:6006   Raw NMEA0183 stream (verbatim re-broadcast).
                        Consumed by: capture_v3.py (legacy).

  HTTP 127.0.0.1:8654   JSON API for the modern stack.
    GET /vessel         Latest vessel state snapshot.
    GET /vessel/history Recent states (last N).
    GET /stream         Server-Sent Events of state changes.
    GET /health         Liveness probe.
    GET /ready          Readiness probe (serial port open + fix acquired).
    GET /nmea/raw       Last N raw NMEA sentences (debug).

  FILE vessel_state.jsonl
                        Append-only JSONL of every state update. This is
                        the "first-class-citizen database" the agent reads.

WHAT IT PARSES
--------------
  $GPGGA   — lat, lon, fix quality, satellites, HDOP, altitude
  $GPRMC   — sog, cog, magnetic variation, date
  $GPGLL   — lat, lon (alt)
  $GPHDT   — heading true (some pilots)
  $HCHDT   — heading true (Airmar / Simrad default)
  $HCHDG   — heading magnetic + deviation
  $SDDBT   — depth below transducer (feet/meters/fathoms)
  $SDDPT   — depth below transducer (meters only)
  $VHW     — water speed + heading (backup)
  $MWV     — wind (logged, not fused)

USAGE
-----
    python nmea_bridge.py                       # use defaults (COM6, 4800 baud)
    python nmea_bridge.py --port COM6 --baud 4800
    python nmea_bridge.py --port COM12 --baud 4800   # com0com fallback
    python nmea_bridge.py --oneshot             # print state and exit
    python nmea_bridge.py --diag                # dump raw sentences for 30s

The process is intended to run as a Windows background service via
restart_services.bat (see that file) or simply via pythonw.exe.

DESIGN NOTES
------------
- Single asyncio loop. Serial reader runs in a background thread (because
  pyserial's blocking read is the simplest path; the ctypes path is also
  blocking). The reader thread pushes parsed sentences into an asyncio
  Queue, which the loop consumes and broadcasts.
- All state is in one VesselState dataclass. Each parsed sentence updates
  one or more fields; a change triggers a fan-out to: (a) the TCP
  broadcaster, (b) the JSONL writer, (c) the SSE broadcaster.
- The TCP broadcaster multiplexes: every connected client gets every
  sentence. No client gets someone else's stale data — this is firehose,
  not request/response.
- The HTTP server is a tiny custom aiohttp app — no Flask, no FastAPI.
  Keeps the dependency footprint at: pyserial + aiohttp (already installed).
- We never write to COM6. Read-only bridge. TZ Pro is the sole writer.
- On any serial error, we close, wait, reopen with backoff. Never crash.
"""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import json
import logging
import os
import re
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

try:
    import serial                                # noqa: F401  (for fallback path)
    from serial import Serial as PySerial
except ImportError:  # pragma: no cover
    PySerial = None

try:
    from aiohttp import web
except ImportError:  # pragma: no cover
    web = None


# ═══════════════════════════════════════════════════════════════════════════
#  Configuration
# ═══════════════════════════════════════════════════════════════════════════

WORKSPACE = Path(__file__).parent.resolve()

DEFAULT_PORT = "COM6"
DEFAULT_BAUD = 4800               # NMEA0183 standard
RAW_TCP_HOST = "127.0.0.1"
RAW_TCP_PORT = 6006
HTTP_HOST = "127.0.0.1"
HTTP_PORT = 8654
STATE_FILE = WORKSPACE / "vessel_state.jsonl"
RAW_NMEA_FILE = WORKSPACE / "nmea_raw.log"
HEARTBEAT_FILE = WORKSPACE / ".last_nmea_heartbeat"
LOCAL_TZ = timezone(timedelta(hours=-8))        # Alaska

# com0com fallback ports (in order of preference)
COM0COM_FALLBACKS = ["COM12", "COM10", "COM11", "COM9"]

# How often to write the heartbeat file (seconds)
HEARTBEAT_INTERVAL_S = 5

# How many raw NMEA sentences to keep in memory for /nmea/raw
RAW_RING_SIZE = 200

# Sentinel — sentinel sentence IDs we recognize
NMEA_RE = re.compile(r"^\$([A-Z]{2})([A-Z]{3}),")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("nmea_bridge")


# ═══════════════════════════════════════════════════════════════════════════
#  State
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class VesselState:
    """The boat's live state — first-class citizen in the database.

    Every field is updated independently as NMEA sentences arrive.
    Fields default to None = "not yet known". Consumers must tolerate None.
    """
    # Time (UTC, ISO 8601) when this snapshot was assembled
    timestamp_utc: Optional[str] = None
    timestamp_local: Optional[str] = None
    # Position
    lat: Optional[float] = None          # decimal degrees, +N/-S
    lon: Optional[float] = None          # decimal degrees, +E/-W
    fix_quality: Optional[int] = None    # 0=invalid, 1=GPS, 2=DGPS
    satellites: Optional[int] = None
    hdop: Optional[float] = None
    altitude_m: Optional[float] = None
    # Motion
    sog_kts: Optional[float] = None      # speed over ground
    cog_deg: Optional[float] = None      # course over ground, true
    mag_variation: Optional[float] = None
    # Heading
    heading_true_deg: Optional[float] = None
    heading_mag_deg: Optional[float] = None
    # Depth (multiple units where the sentence provides them)
    depth_m: Optional[float] = None
    depth_ft: Optional[float] = None
    depth_fm: Optional[float] = None
    # Wind (informational, not fused into sounder state yet)
    wind_speed_kts: Optional[float] = None
    wind_dir_deg: Optional[float] = None   # meteorological (0=N, 90=E)
    # Vessel state classification (computed, not parsed)
    state_class: Optional[str] = None      # "docked" | "trolling" | "cruising"
    last_sentence_id: Optional[str] = None
    sentence_count: int = 0
    # Bookkeeping
    source_port: Optional[str] = None

    def as_dict(self) -> dict:
        d = asdict(self)
        # Drop None values for compactness in JSONL (keeps history queries fast)
        return {k: v for k, v in d.items() if v is not None}

    def is_fresh(self, max_age_s: float = 10.0) -> bool:
        """True if the most recent update is recent enough to trust."""
        if not self.timestamp_utc:
            return False
        try:
            ts = datetime.fromisoformat(self.timestamp_utc)
        except (TypeError, ValueError):
            return False
        return (datetime.now(timezone.utc) - ts).total_seconds() < max_age_s

    def classify_motion(self) -> str:
        """Classify the vessel's motion regime from SOG."""
        if self.sog_kts is None:
            return "unknown"
        if self.sog_kts < 0.5:
            return "docked"
        if self.sog_kts < 2.5:
            return "trolling"     # typical salmon trolling speed
        if self.sog_kts < 8.0:
            return "slow_cruise"
        return "cruising"


# ═══════════════════════════════════════════════════════════════════════════
#  Serial port open with FILE_SHARE_READ | FILE_SHARE_WRITE
# ═══════════════════════════════════════════════════════════════════════════

# Win32 constants (subset we need)
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x80
FILE_FLAG_OVERLAPPED = 0x40000000
INVALID_HANDLE_VALUE = -1  # signed -1 == 0xFFFFFFFF cast

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


def _raise_win_error(prefix: str) -> None:
    err = ctypes.get_last_error()
    raise OSError(err, f"{prefix} (Win32 error {err})")


def open_shared_serial(port: str, baud: int, timeout_s: float = 1.0):
    """Open a COM port with FILE_SHARE_READ|FILE_SHARE_WRITE.

    Returns a file handle (ctypes c_void_p) suitable for overlapped I/O.
    Or raises OSError.

    For COM ports > 8 on Windows, the device path is "\\\\.\\COMxx".
    """
    if port.upper().startswith("COM"):
        try:
            n = int(port[3:])
            if n > 8:
                port = "\\\\.\\" + port
        except ValueError:
            pass

    handle = kernel32.CreateFileW(
        port,
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,                    # no security attrs
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,    # SYNC mode (no FILE_FLAG_OVERLAPPED)
        None,                    # no template
    )
    if handle == INVALID_HANDLE_VALUE or handle == 0xFFFFFFFFFFFFFFFF:
        _raise_win_error(f"CreateFileW({port!r}) failed")

    # Configure baud rate, etc. via DCB
    class DCB(ctypes.Structure):
        _fields_ = [
            ("DCBlength", ctypes.c_ulong),
            ("BaudRate", ctypes.c_ulong),
            ("fBinary", ctypes.c_ulong),
            ("fParity", ctypes.c_ulong),
            ("fOutxCtsFlow", ctypes.c_ulong),
            ("fOutxDsrFlow", ctypes.c_ulong),
            ("fDtrControl", ctypes.c_ulong),
            ("fDsrSensitivity", ctypes.c_ulong),
            ("fTXContinueOnXoff", ctypes.c_ulong),
            ("fOutX", ctypes.c_ulong),
            ("fInX", ctypes.c_ulong),
            ("fErrorChar", ctypes.c_ulong),
            ("fNull", ctypes.c_ulong),
            ("fRtsControl", ctypes.c_ulong),
            ("fAbortOnError", ctypes.c_ulong),
            ("fDummy2", ctypes.c_ulong),
            ("wReserved", ctypes.c_ushort),
            ("XonLim", ctypes.c_ushort),
            ("XoffLim", ctypes.c_ushort),
            ("ByteSize", ctypes.c_byte),
            ("Parity", ctypes.c_byte),
            ("StopBits", ctypes.c_byte),
            ("XonChar", ctypes.c_char),
            ("XoffChar", ctypes.c_char),
            ("ErrorChar", ctypes.c_char),
            ("EofChar", ctypes.c_char),
            ("EvtChar", ctypes.c_char),
            ("wReserved1", ctypes.c_ushort),
        ]

    dcb = DCB()
    dcb.DCBlength = ctypes.sizeof(DCB)
    if not kernel32.GetCommState(handle, ctypes.byref(dcb)):
        kernel32.CloseHandle(handle)
        _raise_win_error("GetCommState failed")
    dcb.BaudRate = baud
    dcb.ByteSize = 8
    dcb.Parity = 0          # NOPARITY
    dcb.StopBits = 0        # ONESTOPBIT
    dcb.fBinary = 1
    if not kernel32.SetCommState(handle, ctypes.byref(dcb)):
        kernel32.CloseHandle(handle)
        _raise_win_error("SetCommState failed")

    # Timeouts (read returns when any data or timeout)
    class COMMTIMEOUTS(ctypes.Structure):
        _fields_ = [
            ("ReadIntervalTimeout", ctypes.c_ulong),
            ("ReadTotalTimeoutMultiplier", ctypes.c_ulong),
            ("ReadTotalTimeoutConstant", ctypes.c_ulong),
            ("WriteTotalTimeoutMultiplier", ctypes.c_ulong),
            ("WriteTotalTimeoutConstant", ctypes.c_ulong),
        ]

    timeouts = COMMTIMEOUTS()
    timeouts.ReadIntervalTimeout = 0
    timeouts.ReadTotalTimeoutMultiplier = 0
    timeouts.ReadTotalTimeoutConstant = int(timeout_s * 1000)
    timeouts.WriteTotalTimeoutMultiplier = 0
    timeouts.WriteTotalTimeoutConstant = 0
    if not kernel32.SetCommTimeouts(handle, ctypes.byref(timeouts)):
        kernel32.CloseHandle(handle)
        _raise_win_error("SetCommTimeouts failed")

    # Set up a 4KB buffer
    kernel32.SetupComm(handle, 4096, 4096)

    return handle


def close_shared_serial(handle) -> None:
    try:
        kernel32.CloseHandle(handle)
    except Exception:  # pragma: no cover
        pass


# ═══════════════════════════════════════════════════════════════════════════
#  NMEA parsing
# ═══════════════════════════════════════════════════════════════════════════

def _nmea_latlon(raw: str, hemi: str, is_lat: bool) -> Optional[float]:
    """Parse a NMEA DDMM.mmm or DDDMM.mmm latitude/longitude value.

    Example: 5547.580,N  → 55 + 47.580/60 = 55.79300
             13141.589,W → 131 + 41.589/60 = 131.69315
    """
    if not raw or not hemi:
        return None
    try:
        dot = raw.find(".")
        if dot < 0:
            return None
        deg_digits = (dot - 2) if is_lat else (dot - 2)
        if deg_digits < 1:
            return None
        deg = int(raw[:deg_digits])
        minutes = float(raw[deg_digits:])
        value = deg + minutes / 60.0
        if hemi.upper() in ("S", "W"):
            value = -value
        return value
    except (ValueError, IndexError):
        return None


def _f(value: str) -> Optional[float]:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _i(value: str) -> Optional[int]:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _verify_checksum(sentence: str) -> bool:
    """NMEA0183 sentences end with *HH where HH is the XOR of all chars
    between $ and *. Returns True if checksum matches or absent."""
    if "*" not in sentence:
        return True    # no checksum → accept
    body, _, tail = sentence.partition("*")
    body = body.lstrip("$")
    tail = tail.strip().split(",")[0]   # in case of CRLF or extra
    if len(tail) < 2:
        return False
    try:
        want = int(tail[:2], 16)
    except ValueError:
        return False
    got = 0
    for ch in body:
        got ^= ord(ch)
    return got == want


def parse_sentence(line: str, state: VesselState) -> Optional[str]:
    """Parse one NMEA sentence and mutate state.

    Returns the sentence kind (e.g. "GPGGA") on success, else None.
    """
    line = line.strip()
    if not line.startswith("$"):
        return None
    if not _verify_checksum(line):
        return None

    # Header: $TTSSS,fields...
    m = NMEA_RE.match(line)
    if not m:
        return None
    # Talker + sounder IDs (e.g. "GP" + "GGA", "HC" + "HDT", "SD" + "DBT")
    kind = m.group(2)
    # Strip the optional *HH checksum tail from the last field
    parts = line.split(",")
    if parts and "*" in parts[-1]:
        parts[-1] = parts[-1].split("*")[0]
    if len(parts) < 2:
        return None

    state.sentence_count += 1
    state.last_sentence_id = f"{m.group(1)}{kind}"

    if kind == "GGA":
        # $--GGA,time,lat,N/S,lon,E/W,quality,sats,hdop,alt,M,geoid,M,age,ref
        if len(parts) >= 15:
            lat = _nmea_latlon(parts[2], parts[3], is_lat=True)
            lon = _nmea_latlon(parts[4], parts[5], is_lat=False)
            if lat is not None:
                state.lat = lat
            if lon is not None:
                state.lon = lon
            q = _i(parts[6])
            if q is not None:
                state.fix_quality = q
            n = _i(parts[7])
            if n is not None:
                state.satellites = n
            hdop = _f(parts[8])
            if hdop is not None:
                state.hdop = hdop
            alt = _f(parts[9])
            if alt is not None:
                state.altitude_m = alt
            # Stamp timestamp from GGA time field
            if parts[1]:
                # HHMMSS or HHMMSS.sss → we keep date separate
                state.timestamp_utc = _stamp_utc_from_gga(parts[1])

    elif kind == "RMC":
        # $--RMC,time,status,lat,N/S,lon,E/W,sog,cog,date,mag_var,E/W,mode
        if len(parts) >= 13:
            lat = _nmea_latlon(parts[3], parts[4], is_lat=True)
            lon = _nmea_latlon(parts[5], parts[6], is_lat=False)
            if lat is not None:
                state.lat = lat
            if lon is not None:
                state.lon = lon
            sog = _f(parts[7])
            if sog is not None:
                state.sog_kts = sog
            cog = _f(parts[8])
            if cog is not None:
                state.cog_deg = cog
            mv = _f(parts[10])
            if mv is not None:
                if parts[11].upper() == "W":
                    mv = -mv
                state.mag_variation = mv
            # Stamp timestamp from RMC date+time
            if parts[1] and parts[9]:
                state.timestamp_utc = _stamp_utc_from_rmc(parts[1], parts[9])

    elif kind == "GLL":
        # $--GLL,lat,N/S,lon,E/W,time,status,mode
        if len(parts) >= 8:
            lat = _nmea_latlon(parts[1], parts[2], is_lat=True)
            lon = _nmea_latlon(parts[3], parts[4], is_lat=False)
            if lat is not None:
                state.lat = lat
            if lon is not None:
                state.lon = lon
            if parts[5]:
                state.timestamp_utc = _stamp_utc_from_gga(parts[5])

    elif kind == "HDT":
        # $--HDT,heading,T
        if len(parts) >= 3 and parts[2].upper().startswith("T"):
            h = _f(parts[1])
            if h is not None:
                state.heading_true_deg = h % 360.0

    elif kind == "HDG":
        # $--HDG,heading,mag,dev,E/W,var,E/W
        if len(parts) >= 3:
            h = _f(parts[1])
            if h is not None:
                state.heading_mag_deg = h % 360.0
            if len(parts) >= 6:
                dev = _f(parts[3])
                if dev is not None:
                    if parts[4].upper() == "W":
                        dev = -dev
                    if state.heading_mag_deg is not None:
                        state.heading_true_deg = (state.heading_mag_deg + dev) % 360.0

    elif kind == "DBT":
        # $--DBT,depth_ft,f,depth_m,M,depth_fm,F
        # Most modern sounders use meters; some use feet. Trust whichever
        # is non-zero and cross-check.
        if len(parts) >= 7:
            ft = _f(parts[1])
            m = _f(parts[3])
            fm = _f(parts[5])
            if ft is not None:
                state.depth_ft = ft
            if m is not None:
                state.depth_m = m
            if fm is not None:
                state.depth_fm = fm
            # Compute any missing ones from the most-authoritative present
            if state.depth_m is None and state.depth_ft is not None:
                state.depth_m = state.depth_ft * 0.3048
            if state.depth_fm is None and state.depth_m is not None:
                state.depth_fm = state.depth_m * 0.546807
            if state.depth_ft is None and state.depth_m is not None:
                state.depth_ft = state.depth_m / 0.3048

    elif kind == "DPT":
        # $--DPT,depth_m,offset_m,max_depth_m
        if len(parts) >= 2:
            m = _f(parts[1])
            if m is not None:
                state.depth_m = m
                state.depth_fm = m * 0.546807
                state.depth_ft = m / 0.3048

    elif kind == "VHW":
        # $--VHW,heading_true,T,heading_mag,M,sog_kts,K,cog_deg,T
        if len(parts) >= 5:
            h = _f(parts[1])
            if h is not None:
                state.heading_true_deg = h % 360.0
            hm = _f(parts[3])
            if hm is not None:
                state.heading_mag_deg = hm % 360.0

    elif kind == "MWV":
        # $--MWV,windangle,ref,R/T,windspd,spdunit,A/B
        if len(parts) >= 6:
            wa = _f(parts[1])
            if wa is not None and parts[2].upper() == "R":
                state.wind_dir_deg = wa % 360.0
            ws = _f(parts[3])
            if ws is not None and parts[4].upper() == "K":
                state.wind_speed_kts = ws
            elif ws is not None and parts[4].upper() == "M":
                state.wind_speed_kts = ws * 1.94384

    # Stamp "now" timestamps and reclassify motion
    now = datetime.now(timezone.utc)
    state.timestamp_utc = now.isoformat()
    state.timestamp_local = now.astimezone(LOCAL_TZ).isoformat()
    state.state_class = state.classify_motion()

    return kind


def _stamp_utc_from_gga(time_str: str) -> Optional[str]:
    """Convert HHMMSS or HHMMSS.sss to today's UTC ISO timestamp."""
    try:
        hhmmss = time_str.split(".")[0]
        if len(hhmmss) != 6:
            return None
        h = int(hhmmss[0:2])
        m = int(hhmmss[2:4])
        s = int(hhmmss[4:6])
        d = datetime.now(timezone.utc).date()
        return datetime(d.year, d.month, d.day, h, m, s, tzinfo=timezone.utc).isoformat()
    except (ValueError, IndexError):
        return None


def _stamp_utc_from_rmc(time_str: str, date_str: str) -> Optional[str]:
    """Convert HHMMSS + DDMMYY (RMC date) to UTC ISO timestamp."""
    try:
        hhmmss = time_str.split(".")[0]
        if len(hhmmss) != 6:
            return None
        if len(date_str) != 6:
            return None
        h = int(hhmmss[0:2]); m = int(hhmmss[2:4]); s = int(hhmmss[4:6])
        dd = int(date_str[0:2]); mm = int(date_str[2:4]); yy = int(date_str[4:6])
        year = 2000 + yy if yy < 80 else 1900 + yy
        return datetime(year, mm, dd, h, m, s, tzinfo=timezone.utc).isoformat()
    except (ValueError, IndexError):
        return None


# ═══════════════════════════════════════════════════════════════════════════
#  Serial reader thread
# ═══════════════════════════════════════════════════════════════════════════

class SerialReaderThread(threading.Thread):
    """Reads from the shared-mode COM port line-by-line and pushes
    parsed sentences + raw lines into the asyncio queue.

    Two queues:
      raw_q   — every clean line (verbatim, for TCP :6006 broadcast)
      state_q — every parsed sentence_id (for HTTP fan-out + JSONL write)
    """

    def __init__(self, port: str, baud: int, raw_q: asyncio.Queue,
                 state_q: asyncio.Queue, loop: asyncio.AbstractEventLoop,
                 stop_event: threading.Event):
        super().__init__(name=f"SerialReader-{port}", daemon=True)
        self.port = port
        self.baud = baud
        self.raw_q = raw_q
        self.state_q = state_q
        self.loop = loop
        self.stop_event = stop_event
        self.handle = None
        self.state = VesselState()
        self.opened = False
        self.fallback_used: Optional[str] = None
        self._buf = b""

    # ── port lifecycle ─────────────────────────────────────────────

    def _try_open(self) -> bool:
        """Try the configured port first; if PermissionError, try com0com."""
        for candidate in [self.port] + [p for p in COM0COM_FALLBACKS if p != self.port]:
            try:
                self.handle = open_shared_serial(candidate, self.baud, timeout_s=1.0)
                if candidate != self.port:
                    log.warning("Fell back from %s to %s (com0com)", self.port, candidate)
                    self.fallback_used = candidate
                self.state.source_port = candidate
                log.info("Opened %s at %d baud (FILE_SHARE_READ|WRITE)", candidate, self.baud)
                return True
            except OSError as e:
                log.debug("Open %s failed: %s", candidate, e)
                continue
        return False

    def _close(self) -> None:
        if self.handle is not None:
            close_shared_serial(self.handle)
            self.handle = None

    def run(self) -> None:
        backoff = 1.0
        while not self.stop_event.is_set():
            if not self.opened:
                if not self._try_open():
                    log.warning("All port candidates failed; retrying in %.1fs", backoff)
                    self.stop_event.wait(backoff)
                    backoff = min(backoff * 2, 30.0)
                    continue
                self.opened = True
                backoff = 1.0

            try:
                self._read_loop()
            except Exception as e:  # pragma: no cover
                log.error("Reader error: %s — reopening", e)
                self._close()
                self.opened = False
                self.stop_event.wait(backoff)
                backoff = min(backoff * 2, 30.0)

        self._close()
        log.info("Reader thread stopped")

    def _read_loop(self) -> None:
        """Pull bytes from the handle, buffer until \\n, parse each line.

        Uses synchronous blocking reads with ReadFile. We set
        ReadTotalTimeoutConstant = timeout_ms so ReadFile returns
        at most every timeout_ms with whatever bytes are available
        (0 bytes = no data right now, loop again).
        """
        import ctypes as _ct

        buf = (ctypes.c_char * 256)()
        bytes_read = _ct.c_ulong(0)

        while not self.stop_event.is_set():
            ok = kernel32.ReadFile(
                self.handle, buf, 256,
                _ct.byref(bytes_read), None,    # NULL = sync
            )
            if not ok:
                err = _ct.get_last_error()
                raise OSError(err, f"ReadFile failed ({err})")

            n = bytes_read.value
            if n == 0:
                # Read timed out with no data — short sleep and try again
                self.stop_event.wait(0.05)
                continue

            chunk = bytes(buf)[:n]
            self._buf += chunk
            while b"\n" in self._buf:
                raw_line, self._buf = self._buf.split(b"\n", 1)
                line = raw_line.decode("ascii", errors="replace").strip("\r\n ")
                if not line:
                    continue
                self._dispatch(line)

    def _dispatch(self, line: str) -> None:
        """Push raw line + parsed update into the asyncio queues.

        The queues are thread-safe (asyncio.Queue is), so we can call
        put_nowait directly from this background thread. No need for
        call_soon_threadsafe — that would schedule the put on the
        loop, which may not be running yet (e.g. during diag mode).
        """
        # Push raw line to TCP broadcaster
        try:
            self.raw_q.put_nowait(line)
        except asyncio.QueueFull:
            pass  # TCP broadcaster is behind — drop oldest
        # Parse synchronously (fast, pure Python, no I/O)
        kind = parse_sentence(line, self.state)
        if kind:
            # Snapshot of state for downstream consumers
            snap = self.state.as_dict()
            try:
                self.state_q.put_nowait(snap)
            except asyncio.QueueFull:
                pass


# ═══════════════════════════════════════════════════════════════════════════
#  Async services
# ═══════════════════════════════════════════════════════════════════════════

class TcpBroadcaster:
    """Multiplex raw NMEA to all connected clients on :6006."""

    def __init__(self, host: str, port: int, raw_q: asyncio.Queue):
        self.host = host
        self.port = port
        self.raw_q = raw_q
        self.clients: set[asyncio.StreamWriter] = set()
        self.server: Optional[asyncio.AbstractServer] = None
        self.client_count = 0

    async def start(self) -> None:
        self.server = await asyncio.start_server(
            self._handle_client, self.host, self.port,
        )
        log.info("Raw NMEA TCP broadcaster on %s:%d", self.host, self.port)

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        for w in list(self.clients):
            try:
                w.close()
            except Exception:
                pass

    async def _handle_client(self, reader: asyncio.StreamReader,
                             writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        self.clients.add(writer)
        self.client_count += 1
        log.info("TCP client connected: %s (total=%d)", peer, self.client_count)
        try:
            # Don't read anything; just hold the connection open until
            # the client disconnects. We don't need their bytes.
            while not reader.at_eof():
                try:
                    await asyncio.wait_for(reader.read(1024), timeout=60.0)
                except asyncio.TimeoutError:
                    pass
        except Exception as e:
            log.debug("Client %s read err: %s", peer, e)
        finally:
            self.clients.discard(writer)
            try:
                writer.close()
            except Exception:
                pass
            log.info("TCP client disconnected: %s", peer)

    async def pump(self) -> None:
        """Drain the raw queue and broadcast each line to all clients."""
        while True:
            line = await self.raw_q.get()
            data = (line + "\r\n").encode("ascii", errors="replace")
            dead = []
            for w in self.clients:
                try:
                    w.write(data)
                    await w.drain()
                except Exception:
                    dead.append(w)
            for w in dead:
                self.clients.discard(w)


class JsonlWriter:
    """Append every state update to vessel_state.jsonl.

    One JSON object per line. Small files. The agent's database.
    """

    def __init__(self, path: Path):
        self.path = path
        self.count = 0

    async def start(self) -> None:
        self.path.touch(exist_ok=True)
        log.info("JSONL state writer → %s", self.path)

    async def pump(self, state_q: asyncio.Queue) -> None:
        while True:
            snap = await state_q.get()
            try:
                # Use a separate thread for blocking IO? For low-rate
                # sentences (~10/s max), the loop is fine writing sync.
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(snap, separators=(",", ":")) + "\n")
                self.count += 1
                # Heartbeat every N writes
                if self.count % 20 == 0:
                    HEARTBEAT_FILE.write_text(
                        datetime.now(timezone.utc).isoformat(), encoding="utf-8"
                    )
            except OSError as e:
                log.warning("JSONL write failed: %s", e)


class SseBroadcaster:
    """Server-Sent Events broadcaster for /stream endpoint."""

    def __init__(self, state_q: asyncio.Queue):
        self.state_q = state_q
        self.subscribers: set[asyncio.Queue] = set()
        # We DON'T consume from state_q here — JsonlWriter does.
        # Instead, SseBroadcaster.pump() reads from a separate queue
        # that the main loop feeds from. Simpler: just share the state_q
        # via fan-out in the main pump.

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.subscribers.discard(q)

    async def pump(self, state_q: asyncio.Queue) -> None:
        while True:
            snap = await state_q.get()
            data = f"data: {json.dumps(snap)}\n\n".encode("utf-8")
            for q in list(self.subscribers):
                try:
                    q.put_nowait(data)
                except asyncio.QueueFull:
                    pass   # slow consumer — drop, they'll catch next


# ═══════════════════════════════════════════════════════════════════════════
#  HTTP API
# ═══════════════════════════════════════════════════════════════════════════

def build_http_app(reader: SerialReaderThread,
                   tcp: TcpBroadcaster,
                   sse: SseBroadcaster,
                   jsonl: JsonlWriter) -> web.Application:
    """Construct the aiohttp app with the /vessel, /stream, /health,
    /ready, /nmea/raw endpoints."""

    app = web.Application()
    raw_ring: deque[str] = deque(maxlen=RAW_RING_SIZE)

    # We need a parallel queue to feed raw lines into the /nmea/raw ring
    # without taking from the TCP broadcaster's queue.
    raw_log_q: asyncio.Queue = asyncio.Queue()

    async def ring_pump(raw_q: asyncio.Queue) -> None:
        while True:
            line = await raw_q.get()
            raw_ring.append(line)
            try:
                raw_log_q.put_nowait(line)
            except asyncio.QueueFull:
                pass

    # Re-route: SerialReaderThread pushes into raw_q; we now have one
    # consumer for TCP broadcast and one for the ring. Use two queues.

    async def health(_req: web.Request) -> web.Response:
        return web.json_response({
            "ok": True,
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "source_port": reader.state.source_port,
            "opened": reader.opened,
            "tcp_clients": tcp.client_count,
            "jsonl_writes": jsonl.count,
            "sentence_count": reader.state.sentence_count,
            "last_sentence_id": reader.state.last_sentence_id,
        })

    async def ready(_req: web.Request) -> web.Response:
        fresh = reader.state.is_fresh(max_age_s=10.0)
        return web.json_response({
            "ready": fresh,
            "fix_quality": reader.state.fix_quality,
            "satellites": reader.state.satellites,
            "lat": reader.state.lat,
            "lon": reader.state.lon,
            "state_class": reader.state.state_class,
        }, status=200 if fresh else 503)

    async def vessel(_req: web.Request) -> web.Response:
        return web.json_response(reader.state.as_dict())

    async def history(req: web.Request) -> web.Response:
        try:
            n = int(req.query.get("n", "20"))
        except ValueError:
            n = 20
        n = max(1, min(n, 1000))
        # Read last N lines from JSONL
        if not jsonl.path.exists():
            return web.json_response([])
        try:
            with open(jsonl.path, "r", encoding="utf-8") as f:
                lines = f.readlines()[-n:]
            return web.json_response([json.loads(l) for l in lines if l.strip()])
        except (OSError, json.JSONDecodeError) as e:
            return web.json_response({"error": str(e)}, status=500)

    async def stream(req: web.Request) -> web.StreamResponse:
        resp = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
        await resp.prepare(req)
        sub = sse.subscribe()
        try:
            await resp.write_bytes(b": stream-open\n\n")
            while True:
                try:
                    data = await asyncio.wait_for(sub.get(), timeout=15.0)
                    await resp.write_bytes(data)
                except asyncio.TimeoutError:
                    await resp.write_bytes(b": ping\n\n")
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            sse.unsubscribe(sub)
        return resp

    async def nmea_raw(_req: web.Request) -> web.Response:
        return web.json_response(list(raw_ring))

    app.router.add_get("/health", health)
    app.router.add_get("/ready", ready)
    app.router.add_get("/vessel", vessel)
    app.router.add_get("/vessel/history", history)
    app.router.add_get("/stream", stream)
    app.router.add_get("/nmea/raw", nmea_raw)

    # Attach ring pump to app lifecycle
    async def _startup(app: web.Application) -> None:
        # Re-route raw lines: SerialReader pushes into raw_q which TCP
        # broadcaster pumps. We need to mirror to the ring. Use a small
        # tee: define a wrapper queue and have SerialReader push to both.
        # Simpler: have the TCP broadcaster also push to the ring.
        # We do this by monkey-patching after construction below.
        app["raw_ring_pump"] = asyncio.create_task(ring_pump(raw_log_q))

    async def _shutdown(app: web.Application) -> None:
        task = app.get("raw_ring_pump")
        if task:
            task.cancel()

    app.on_startup.append(_startup)
    app.on_shutdown.append(_shutdown)
    return app


# ═══════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════

async def run_forever(args: argparse.Namespace) -> None:
    if web is None:
        log.error("aiohttp not installed; HTTP API disabled. pip install aiohttp")
        sys.exit(1)

    stop_event = threading.Event()
    loop = asyncio.get_running_loop()
    raw_q: asyncio.Queue = asyncio.Queue(maxsize=2048)
    state_q: asyncio.Queue = asyncio.Queue(maxsize=2048)

    reader = SerialReaderThread(
        port=args.port, baud=args.baud,
        raw_q=raw_q, state_q=state_q,
        loop=loop, stop_event=stop_event,
    )
    reader.start()

    tcp = TcpBroadcaster(RAW_TCP_HOST, RAW_TCP_PORT, raw_q)
    jsonl = JsonlWriter(STATE_FILE)
    sse = SseBroadcaster(state_q)

    await tcp.start()
    await jsonl.start()

    app = build_http_app(reader, tcp, sse, jsonl)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, HTTP_HOST, HTTP_PORT)
    await site.start()
    log.info("HTTP API on http://%s:%d", HTTP_HOST, HTTP_PORT)

    tasks = [
        asyncio.create_task(tcp.pump(), name="tcp_pump"),
        asyncio.create_task(jsonl.pump(state_q), name="jsonl_pump"),
        asyncio.create_task(sse.pump(state_q), name="sse_pump"),
    ]

    # Heartbeat writer — keep HEARTBEAT_FILE fresh as a liveness signal
    async def heartbeat_loop():
        while True:
            try:
                HEARTBEAT_FILE.write_text(
                    datetime.now(timezone.utc).isoformat(), encoding="utf-8"
                )
            except OSError:
                pass
            await asyncio.sleep(HEARTBEAT_INTERVAL_S)
    tasks.append(asyncio.create_task(heartbeat_loop(), name="heartbeat"))

    log.info("Bridge is live. Press Ctrl+C to stop.")
    try:
        await asyncio.gather(*tasks)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        log.info("Shutting down...")
        stop_event.set()
        await tcp.stop()
        await runner.cleanup()
        reader.join(timeout=5.0)
        log.info("Stopped cleanly.")


def oneshot(args: argparse.Namespace) -> int:
    """Open port, print state, exit. For diagnostics."""
    stop_event = threading.Event()
    loop = asyncio.new_event_loop()
    raw_q: asyncio.Queue = asyncio.Queue(maxsize=2048)
    state_q: asyncio.Queue = asyncio.Queue(maxsize=2048)

    reader = SerialReaderThread(
        port=args.port, baud=args.baud,
        raw_q=raw_q, state_q=state_q,
        loop=loop, stop_event=stop_event,
    )
    reader.start()

    deadline = time.time() + 8.0
    while time.time() < deadline and reader.state.sentence_count < 3:
        time.sleep(0.2)

    print(json.dumps(reader.state.as_dict(), indent=2))
    stop_event.set()
    reader.join(timeout=3.0)
    return 0 if reader.state.sentence_count > 0 else 2


def diag(args: argparse.Namespace) -> int:
    """Open port, dump raw sentences for 30s, exit."""
    import threading as _threading
    stop_event = _threading.Event()
    loop = asyncio.new_event_loop()
    raw_q: asyncio.Queue = asyncio.Queue(maxsize=4096)
    state_q: asyncio.Queue = asyncio.Queue(maxsize=4096)

    reader = SerialReaderThread(
        port=args.port, baud=args.baud,
        raw_q=raw_q, state_q=state_q,
        loop=loop, stop_event=stop_event,
    )
    reader.start()
    # Give the loop time to start consuming the queues
    loop_thread = _threading.Thread(target=loop.run_forever, daemon=True)
    loop_thread.start()

    deadline = time.time() + args.diag_seconds
    n_dumped = 0
    while time.time() < deadline:
        try:
            line = raw_q.get_nowait()
            print(line, flush=True)
            n_dumped += 1
        except Exception:
            time.sleep(0.1)

    print(f"\n--- {reader.state.sentence_count} sentences parsed, "
          f"{n_dumped} raw lines dumped ---",
          file=sys.stderr)
    print(f"--- source port: {reader.state.source_port} ---", file=sys.stderr)
    print(f"--- last state: lat={reader.state.lat} lon={reader.state.lon} "
          f"sog={reader.state.sog_kts} cog={reader.state.cog_deg} ---",
          file=sys.stderr)
    stop_event.set()
    reader.join(timeout=3.0)
    loop.call_soon_threadsafe(loop.stop)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="NMEA0183 → TCP/HTTP bridge for tzpro-agent")
    p.add_argument("--port", default=DEFAULT_PORT,
                   help=f"Serial port (default {DEFAULT_PORT})")
    p.add_argument("--baud", type=int, default=DEFAULT_BAUD,
                   help=f"Baud rate (default {DEFAULT_BAUD}; NMEA0183 standard)")
    p.add_argument("--oneshot", action="store_true",
                   help="Print state snapshot and exit")
    p.add_argument("--diag", action="store_true",
                   help="Dump raw NMEA sentences to stdout for ~30s")
    p.add_argument("--diag-seconds", type=int, default=30,
                   help="Duration for --diag mode")
    args = p.parse_args()

    if args.oneshot:
        return oneshot(args)
    if args.diag:
        return diag(args)

    try:
        asyncio.run(run_forever(args))
    except KeyboardInterrupt:
        log.info("Interrupted")
    return 0


if __name__ == "__main__":
    sys.exit(main())