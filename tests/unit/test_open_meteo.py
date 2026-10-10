"""Sea and weather from Open-Meteo. Offline must degrade, never raise: the risk engine and the
dashboard both keep working without it."""
import asyncio

import httpx

from app.environment.external_data.open_meteo import OpenMeteoProvider
from tests.conftest import FakeClock

FORECAST = {"current": {"temperature_2m": 29.1, "wind_speed_10m": 6.5, "wind_gusts_10m": 11.0,
                        "wind_direction_10m": 250, "weather_code": 3, "precipitation": 0.0},
            "hourly": {"time": ["2026-10-05T10:00", "2026-10-05T11:00"], "wind_speed_10m": [6, 7],
                       "wind_gusts_10m": [10, 12], "precipitation_probability": [10, 40]}}
MARINE = {"current": {"wave_height": 1.8, "wave_period": 9.0, "wave_direction": 260,
                      "swell_wave_height": 1.2, "sea_level_height_msl": 0.43,
                      "sea_surface_temperature": 28.5, "ocean_current_velocity": 1.8},
          "hourly": {"time": ["2026-10-05T10:00", "2026-10-05T11:00"], "wave_height": [1.8, 2.0],
                     "swell_wave_height": [1.2, 1.3], "sea_level_height_msl": [0.43, 0.5]}}


def provider(handler):
    return OpenMeteoProvider(FakeClock(), "https://api.example/forecast", "https://marine.example/marine",
                             transport=httpx.MockTransport(handler))


def test_parses_current_and_forecast():
    calls = []

    def handler(req):
        calls.append(req.url.host)
        return httpx.Response(200, json=MARINE if "marine" in req.url.host else FORECAST)

    p = provider(handler)
    c = asyncio.run(p.get_conditions(12.84, 74.8))
    assert c.status == "ok" and c.wind_speed_ms == 6.5 and c.wave_height_m == 1.8
    assert c.tide_height_m == 0.43
    assert abs(c.ocean_current_ms - 0.5) < 1e-9   # km/h -> m/s
    assert len(c.forecast) == 2 and c.forecast[1].wave_height_m == 2.0
    asyncio.run(p.get_conditions(12.84, 74.8))
    assert len(calls) == 2, "the second call must come from the cache"


def test_offline_degrades_gracefully():
    def handler(req):
        raise httpx.ConnectError("offline")

    c = asyncio.run(provider(handler).get_conditions(1, 2))
    assert c.status == "unavailable" and c.wind_speed_ms is None and "ConnectError" in c.error


def test_partial_when_only_marine_fails():
    def handler(req):
        return httpx.Response(500) if "marine" in req.url.host else httpx.Response(200, json=FORECAST)

    c = asyncio.run(provider(handler).get_conditions(1, 2))
    assert c.status == "partial" and c.wind_speed_ms == 6.5 and c.wave_height_m is None


def test_a_failed_lookup_is_not_cached():
    """Otherwise one blip would hide the weather for the rest of the cache window."""
    attempts = []

    def handler(req):
        attempts.append(1)
        if len(attempts) <= 2:          # first pair of calls fails
            raise httpx.ConnectError("offline")
        return httpx.Response(200, json=MARINE if "marine" in req.url.host else FORECAST)

    p = provider(handler)
    assert asyncio.run(p.get_conditions(5, 5)).status == "unavailable"
    assert asyncio.run(p.get_conditions(5, 5)).status == "ok"
