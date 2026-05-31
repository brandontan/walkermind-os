"""Async forecast fetchers: Open-Meteo (ECMWF/HRRR), METAR, Visual Crossing."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import httpx

from .locations import Location

log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
_METAR_URL = "https://aviationweather.gov/api/data/metar"
_VC_URL = "https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline"


@dataclass
class ForecastResult:
    source: str
    temp_max_f: float | None = None
    temp_min_f: None | float = None
    available: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


def _c_to_f(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


async def fetch_ecmwf(loc: Location, target_date: str) -> ForecastResult:
    """Fetch daily Tmax from Open-Meteo ECMWF model for target_date (YYYY-MM-DD)."""
    params = {
        "latitude": loc.latitude,
        "longitude": loc.longitude,
        "daily": "temperature_2m_max,temperature_2m_min",
        "temperature_unit": "celsius",
        "timezone": loc.timezone,
        "start_date": target_date,
        "end_date": target_date,
        "models": "ecmwf_ifs04",
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(_OPEN_METEO_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        daily = data.get("daily", {})
        tmax_list = daily.get("temperature_2m_max") or []
        tmin_list = daily.get("temperature_2m_min") or []
        tmax = _c_to_f(tmax_list[0]) if tmax_list and tmax_list[0] is not None else None
        tmin = _c_to_f(tmin_list[0]) if tmin_list and tmin_list[0] is not None else None
        return ForecastResult(source="ecmwf", temp_max_f=tmax, temp_min_f=tmin,
                              available=tmax is not None, raw=data)
    except Exception as exc:
        log.warning("ecmwf fetch failed", extra={"city": loc.city, "err": str(exc)})
        return ForecastResult(source="ecmwf")


async def fetch_hrrr(loc: Location, target_date: str) -> ForecastResult:
    """Fetch daily Tmax from Open-Meteo HRRR model (US only).

    HRRR is only available for CONUS — returns unavailable for non-US locations.
    """
    if loc.country != "US":
        return ForecastResult(source="hrrr")
    params = {
        "latitude": loc.latitude,
        "longitude": loc.longitude,
        "daily": "temperature_2m_max,temperature_2m_min",
        "temperature_unit": "celsius",
        "timezone": loc.timezone,
        "start_date": target_date,
        "end_date": target_date,
        "models": "best_match",   # Open-Meteo selects HRRR for US when best_match
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(_OPEN_METEO_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        daily = data.get("daily", {})
        tmax_list = daily.get("temperature_2m_max") or []
        tmin_list = daily.get("temperature_2m_min") or []
        tmax = _c_to_f(tmax_list[0]) if tmax_list and tmax_list[0] is not None else None
        tmin = _c_to_f(tmin_list[0]) if tmin_list and tmin_list[0] is not None else None
        return ForecastResult(source="hrrr", temp_max_f=tmax, temp_min_f=tmin,
                              available=tmax is not None, raw=data)
    except Exception as exc:
        log.warning("hrrr fetch failed", extra={"city": loc.city, "err": str(exc)})
        return ForecastResult(source="hrrr")


async def fetch_metar(loc: Location) -> ForecastResult:
    """Fetch latest METAR observation temperature for the airport station."""
    params = {
        "ids": loc.metar_station,
        "format": "json",
        "taf": "false",
        "hours": "3",
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(_METAR_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        if not data or not isinstance(data, list) or not data[0]:
            return ForecastResult(source="metar")
        obs = data[0]
        temp_c = obs.get("temp")
        if temp_c is None:
            return ForecastResult(source="metar")
        temp_f = _c_to_f(float(temp_c))
        return ForecastResult(source="metar", temp_max_f=temp_f, available=True, raw=obs)
    except Exception as exc:
        log.warning("metar fetch failed", extra={"station": loc.metar_station, "err": str(exc)})
        return ForecastResult(source="metar")


async def fetch_visual_crossing(loc: Location, target_date: str) -> ForecastResult:
    """Fetch daily Tmax from Visual Crossing Timeline API.

    Requires VISUALCROSSING_API_KEY environment variable. Returns unavailable
    when the key is absent — no silent fail, logged at warning.
    """
    api_key = os.environ.get("VISUALCROSSING_API_KEY", "")
    if not api_key:
        log.warning("VISUALCROSSING_API_KEY not set — Visual Crossing fetch skipped")
        return ForecastResult(source="visual_crossing")

    location_str = f"{loc.latitude},{loc.longitude}"
    url = f"{_VC_URL}/{location_str}/{target_date}/{target_date}"
    params = {
        "key": api_key,
        "unitGroup": "us",       # Fahrenheit
        "include": "days",
        "elements": "tempmax,tempmin",
        "contentType": "json",
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        days = data.get("days") or []
        if not days:
            return ForecastResult(source="visual_crossing")
        day = days[0]
        tmax = day.get("tempmax")
        tmin = day.get("tempmin")
        return ForecastResult(
            source="visual_crossing",
            temp_max_f=float(tmax) if tmax is not None else None,
            temp_min_f=float(tmin) if tmin is not None else None,
            available=tmax is not None,
            raw=day,
        )
    except Exception as exc:
        log.warning("visual_crossing fetch failed",
                    extra={"city": loc.city, "date": target_date, "err": str(exc)})
        return ForecastResult(source="visual_crossing")


async def fetch_all(loc: Location, target_date: str) -> list[ForecastResult]:
    """Fetch from all sources concurrently; return only available results."""
    import asyncio
    results = await asyncio.gather(
        fetch_ecmwf(loc, target_date),
        fetch_hrrr(loc, target_date),
        fetch_visual_crossing(loc, target_date),
        return_exceptions=False,
    )
    available = [r for r in results if isinstance(r, ForecastResult) and r.available]
    return available


def ensemble_tmax(results: list[ForecastResult]) -> float | None:
    """Simple average of available Tmax forecasts across sources."""
    temps = [r.temp_max_f for r in results if r.temp_max_f is not None]
    if not temps:
        return None
    return sum(temps) / len(temps)
