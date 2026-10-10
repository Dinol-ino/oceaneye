"""Open-Meteo (free, no API key) weather + marine provider.

* Forecast API: wind, gusts, direction, temperature, weather code, precipitation (+ 12 h forecast)
* Marine API: wave height/period/direction, swell, sea level incl. tides, sea temperature, current

Results are cached (``ttl_seconds``) per ~1 km cell. Network problems never raise to the API user:
they return ``status="unavailable"``, so the dashboard and the risk engine keep working offline.

Place search lives in :mod:`app.environment.external_data.geoapify`.
"""
from __future__ import annotations

import asyncio
import logging
import time

import httpx

from app.core.interfaces.clock import Clock
from app.environment.external_data.base import (
    EnvironmentalConditions,
    EnvironmentalDataProvider,
    ForecastPoint,
)

logger = logging.getLogger(__name__)

FORECAST_CURRENT = "temperature_2m,wind_speed_10m,wind_gusts_10m,wind_direction_10m,weather_code,precipitation"
FORECAST_HOURLY = "wind_speed_10m,wind_gusts_10m,precipitation_probability"
MARINE_CURRENT = ("wave_height,wave_period,wave_direction,swell_wave_height,sea_level_height_msl,"
                  "sea_surface_temperature,ocean_current_velocity")
MARINE_HOURLY = "wave_height,swell_wave_height,sea_level_height_msl"


def _f(d: dict, key: str) -> float | None:
    v = d.get(key)
    return float(v) if isinstance(v, (int, float)) else None


class _TtlCache:
    def __init__(self, ttl: float) -> None:
        self.ttl, self._d = ttl, {}

    def get(self, key):
        hit = self._d.get(key)
        return hit[1] if hit and time.monotonic() - hit[0] < self.ttl else None

    def put(self, key, value) -> None:
        self._d[key] = (time.monotonic(), value)


def parse_conditions(lat: float, lon: float, fetched_at, forecast: dict | None, marine: dict | None,
                     errors: list[str], hours: int = 12) -> EnvironmentalConditions:
    fc = (forecast or {}).get("current", {}) or {}
    mc = (marine or {}).get("current", {}) or {}
    fh = (forecast or {}).get("hourly", {}) or {}
    mh = (marine or {}).get("hourly", {}) or {}
    times = fh.get("time") or mh.get("time") or []
    mtimes = {t: i for i, t in enumerate(mh.get("time") or [])}

    def pick(src: dict, key: str, idx: int | None):
        if idx is None:
            return None
        series = src.get(key) or []
        return series[idx] if idx < len(series) else None

    points = []
    for i, t in enumerate(times[:hours]):
        j = mtimes.get(t)
        points.append(ForecastPoint(
            time=t, wind_speed_ms=pick(fh, "wind_speed_10m", i), wind_gusts_ms=pick(fh, "wind_gusts_10m", i),
            precipitation_prob=pick(fh, "precipitation_probability", i), wave_height_m=pick(mh, "wave_height", j),
            swell_height_m=pick(mh, "swell_wave_height", j), sea_level_m=pick(mh, "sea_level_height_msl", j),
        ))
    status = "ok" if forecast and marine else ("partial" if forecast or marine else "unavailable")
    current_kmh = _f(mc, "ocean_current_velocity")
    return EnvironmentalConditions(
        lat=lat, lon=lon, fetched_at=fetched_at, source="open-meteo", status=status,
        error="; ".join(errors) or None,
        wind_speed_ms=_f(fc, "wind_speed_10m"), wind_gusts_ms=_f(fc, "wind_gusts_10m"),
        wind_direction_deg=_f(fc, "wind_direction_10m"), air_temperature_c=_f(fc, "temperature_2m"),
        weather_code=int(fc["weather_code"]) if isinstance(fc.get("weather_code"), (int, float)) else None,
        precipitation_mm=_f(fc, "precipitation"), wave_height_m=_f(mc, "wave_height"),
        wave_period_s=_f(mc, "wave_period"), wave_direction_deg=_f(mc, "wave_direction"),
        swell_height_m=_f(mc, "swell_wave_height"), tide_height_m=_f(mc, "sea_level_height_msl"),
        sea_surface_temperature_c=_f(mc, "sea_surface_temperature"),
        ocean_current_ms=(current_kmh / 3.6) if current_kmh is not None else None,
        forecast=tuple(points),
    )


class OpenMeteoProvider(EnvironmentalDataProvider):
    def __init__(self, clock: Clock, forecast_url: str, marine_url: str, ttl_seconds: int = 600,
                 timeout: float = 12.0, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._clock, self._forecast_url, self._marine_url = clock, forecast_url, marine_url
        self._cache = _TtlCache(ttl_seconds)
        self._timeout, self._transport = timeout, transport

    async def _get(self, client: httpx.AsyncClient, url: str, params: dict) -> tuple[dict | None, str | None]:
        try:
            r = await client.get(url, params=params)
            r.raise_for_status()
            return r.json(), None
        except Exception as exc:  # noqa: BLE001 - offline must not break the app
            logger.warning("open-meteo request failed: %s", type(exc).__name__)
            return None, f"{url.split('/')[2]}: {type(exc).__name__}"

    async def get_conditions(self, lat: float, lon: float) -> EnvironmentalConditions:
        key = (round(lat, 2), round(lon, 2))
        cached = self._cache.get(key)
        if cached:
            return cached
        common = {"latitude": lat, "longitude": lon, "timezone": "auto", "forecast_hours": 12}
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            (fc, e1), (mc, e2) = await asyncio.gather(
                self._get(client, self._forecast_url, {**common, "current": FORECAST_CURRENT,
                                                       "hourly": FORECAST_HOURLY, "wind_speed_unit": "ms"}),
                self._get(client, self._marine_url, {**common, "current": MARINE_CURRENT, "hourly": MARINE_HOURLY}),
            )
        result = parse_conditions(lat, lon, self._clock.now(), fc, mc, [e for e in (e1, e2) if e])
        if result.status != "unavailable":
            self._cache.put(key, result)
        return result
