"""cascade/tools/daily_context.py — NOAA tide + weather context for the vessel.

Stdlib only, no API keys. Fetches:
- Nearest tide station (SE Alaska built-in table)
- 48-hour tide predictions (high/low, MLLW)
- NWS wind forecast via api.weather.gov points API

Offline behavior: any network failure returns {'offline': True, 'reason': str}
and never raises (boat rule).
"""
from __future__ import annotations

import json
import logging
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# ── SE Alaska tide stations ────────────────────────────────────────────────
# NOAA CO-OPS API: https://tidesandcurrents.noaa.gov/api/
# Station list for Southeast Alaska (near common fishing grounds)
_STATIONS = {
    "9450460": {"name": "Ketchikan", "lat": 55.342, "lon": -131.646},
    "9459454": {"name": "Petersburg", "lat": 56.812, "lon": -132.955},
    "9452210": {"name": "Juneau", "lat": 58.301, "lon": -134.415},
    "9451600": {"name": "Sitka", "lat": 57.053, "lon": -135.331},
    "9456487": {"name": "Wrangell", "lat": 56.470, "lon": -132.377},
    "9458040": {"name": "Craig", "lat": 55.475, "lon": -133.167},
}

_TIDE_BASE = "https://api.tidesandcurrents.noaa.gov/api/prod/datagitter"
# Correct endpoint from docs
_TIDE_BASE = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"

_WEATHER_BASE = "https://api.weather.gov"

_USER_AGENT = "boat-agent (contact@fv-eileen.demo)"  # Required by NWS

log = logging.getLogger("cascade.daily_context")


def _nearest_station(lat: float, lon: float) -> tuple[str, dict]:
    """Find nearest tide station by Haversine distance."""
    best_id = None
    best_dist = float("inf")
    best_data = {}

    for sid, data in _STATIONS.items():
        # Haversine approximation (good enough for SE AK scale)
        dlat = (lat - data["lat"]) * 111.0  # km per deg lat
        dlon = (lon - data["lon"]) * (111.0 * 0.6)  # rough km per deg lon at 56°N
        dist = (dlat**2 + dlon**2) ** 0.5
        if dist < best_dist:
            best_dist = dist
            best_id = sid
            best_data = data

    return best_id, best_data


def _urlopen_json(url: str, headers: dict | None = None) -> Any:
    """Fetch and parse JSON, returning None on any error (offline-safe)."""
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        log.debug("fetch failed: %s", e)
        return None


def get_context(lat: float, lon: float) -> dict:
    """Fetch tide + weather context for a position.

    Returns deterministic JSON with sorted keys:
    {
        "offline": False,
        "tide_station": {"id": str, "name": str, "lat": float, "lon": float},
        "tide_events": [
            {"type": "high"|"low", "t": "YYYY-MM-DD HH:MM", "height_ft": 12.3}
        ],
        "wind_forecast": [
            {"time": "YYYY-MM-DD HH:MM", "speed_knots": 10, "direction": "NW"}
        ],
        "fetched_at": "YYYY-MM-DD HH:MM:SSZ"
    }

    Offline: returns {'offline': True, 'reason': str}
    """
    result: dict[str, Any] = {"offline": False}

    # 1. Nearest tide station
    station_id, station_data = _nearest_station(lat, lon)
    result["tide_station"] = {
        "id": station_id,
        "name": station_data["name"],
        "lat": station_data["lat"],
        "lon": station_data["lon"],
    }

    # 2. Tide predictions (48h, high/low only)
    tide_url = (
        f"{_TIDE_BASE}"
        f"?product=predictions"
        f"&application=boat_agent"
        f"&station={station_id}"
        f"&datum=MLLW"
        f"&units=english"
        f"&time_zone=lst_ldt"
        f"&format=json"
        f"&interval=hilo"
        f"&range=48"
    )
    tide_data = _urlopen_json(tide_url)
    if tide_data is None:
        return {"offline": True, "reason": "tide_api_failed"}

    result["tide_events"] = []
    for rec in tide_data.get("predictions", []):
        # NOAA API returns: t (time), v (height value as string), type (H/L)
        tide_type = rec.get("type", "").upper()
        tide_type_str = "high" if tide_type == "H" else "low"
        height = 0.0
        try:
            height = float(rec.get("v", "0"))
        except (ValueError, TypeError):
            pass
        result["tide_events"].append({
            "type": tide_type_str,
            "t": rec.get("t", ""),
            "height_ft": height,
        })

    # 3. Weather forecast via NWS points API
    # Step A: get grid endpoint
    point_url = f"{_WEATHER_BASE}/points/{lat:.4f},{lon:.4f}"
    point_data = _urlopen_json(point_url, headers={"User-Agent": _USER_AGENT})
    if point_data is None:
        # Weather is optional — still return tides
        log.warning("NWS point lookup failed, returning tides only")
        result["wind_forecast"] = []
    else:
        # Step B: get forecast from grid endpoint
        forecast_url = point_data.get("properties", {}).get("forecast")
        if not forecast_url:
            log.warning("no forecast URL in NWS response")
            result["wind_forecast"] = []
        else:
            forecast_data = _urlopen_json(forecast_url, headers={"User-Agent": _USER_AGENT, "Accept": "application/ld+json"})
            if forecast_data is None:
                result["wind_forecast"] = []
            else:
                # Parse forecast periods for wind
                result["wind_forecast"] = []
                periods = forecast_data.get("periods", [])
                for p in periods[:12]:  # Next ~12 periods
                    wind = p.get("windSpeed", "")
                    # Parse "5 to 10 mph" or "10 mph" — extract number
                    import re
                    nums = re.findall(r"\d+", wind)
                    speed = int(nums[0]) if nums else 0
                    # Convert mph to knots (1 mph ≈ 0.869 knots)
                    speed_knots = round(speed * 0.869, 1)

                    wind_dir = p.get("windDirection", "Unknown").split()[0]

                    result["wind_forecast"].append({
                        "time": p.get("startTime", "")[:16].replace("T", " "),
                        "speed_knots": speed_knots,
                        "direction": wind_dir,
                    })

    result["fetched_at"] = time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime())

    # Return with deterministic key order
    return {
        "offline": result["offline"],
        "tide_station": result["tide_station"],
        "tide_events": result["tide_events"],
        "wind_forecast": result["wind_forecast"],
        "fetched_at": result["fetched_at"],
    }


def write_context(out_dir: Path, lat: float, lon: float) -> Path:
    """Write context file atomically to out_dir/context/<date>.json.

    Returns the path written. Creates directories as needed.
    Offline data still gets written (boat rule: persist what you have).
    """
    ctx_dir = out_dir / "context"
    ctx_dir.mkdir(parents=True, exist_ok=True)

    date = time.strftime("%Y-%m-%d", time.gmtime())
    out_path = ctx_dir / f"{date}.json"

    data = get_context(lat, lon)

    # Atomic write: temp + replace
    fd, tmp_path = tempfile.mkstemp(suffix=".tmp", dir=ctx_dir)
    try:
        with open(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        Path(tmp_path).replace(out_path)
        log.info("context written: %s (offline=%s)", out_path, data.get("offline"))
        return out_path
    except Exception:
        try:
            Path(tmp_path).unlink()
        except Exception:
            pass
        raise


def _print_cli(lat: float, lon: float) -> None:
    """CLI entry point — prints JSON to stdout."""
    data = get_context(lat, lon)
    print(json.dumps(data, indent=2))


def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Fetch NOAA tide + weather context for vessel position.")
    p.add_argument("lat", type=float, help="Latitude (e.g. 55.787)")
    p.add_argument("lon", type=float, help="Longitude (e.g. -131.70)")
    args = p.parse_args()

    _print_cli(args.lat, args.lon)


if __name__ == "__main__":
    main()
