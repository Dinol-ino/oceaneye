"""External environmental data (wind, waves/swell, sea level, forecast) - Open-Meteo (reference PDF §8).
A camera cannot measure wind; this comes from an external feed. Temperature is context only.

Also the read-only place lookup behind the setup search. A ``PlaceResult`` is a map hit, not a
configured site: picking one is what creates a :class:`app.core.entities.beach.Beach`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class ForecastPoint:
    time: str  # local ISO time from the provider
    wind_speed_ms: float | None = None
    wind_gusts_ms: float | None = None
    wave_height_m: float | None = None
    swell_height_m: float | None = None
    sea_level_m: float | None = None
    precipitation_prob: float | None = None


@dataclass(frozen=True)
class EnvironmentalConditions:
    lat: float
    lon: float
    fetched_at: datetime
    source: str
    status: str = "ok"  # ok | partial | unavailable
    error: str | None = None
    wind_speed_ms: float | None = None
    wind_gusts_ms: float | None = None
    wind_direction_deg: float | None = None
    air_temperature_c: float | None = None  # contextual metadata only
    weather_code: int | None = None
    precipitation_mm: float | None = None
    wave_height_m: float | None = None
    wave_period_s: float | None = None
    wave_direction_deg: float | None = None
    swell_height_m: float | None = None
    tide_height_m: float | None = None  # sea_level_height_msl (includes tides)
    sea_surface_temperature_c: float | None = None
    ocean_current_ms: float | None = None
    forecast: tuple[ForecastPoint, ...] = field(default_factory=tuple)


class EnvironmentalDataProvider(ABC):
    @abstractmethod
    async def get_conditions(self, lat: float, lon: float) -> EnvironmentalConditions: ...


@dataclass(frozen=True)
class PlaceResult:
    """One place found on the map. Not yet a configured deployment site.

    ``address`` is the provider's human-readable line ("Panambur Beach, Mangaluru, Karnataka,
    India"). It is what the operator reads to confirm they picked the right place, so it is carried
    all the way to the screen rather than reduced to a name.
    """

    name: str
    lat: float
    lon: float
    address: str = ""
    distance_km: float | None = None  # only when the search was biased to a point
    source_id: str | None = None      # provider's place id, so adding the same place twice is a no-op

    @property
    def label(self) -> str:
        return self.address or self.name


class PlaceDirectory(ABC):
    """Finds places to deploy at. One free-text search, one nearby-beaches lookup - no more."""

    @abstractmethod
    async def search(self, text: str, *, near: tuple[float, float] | None = None,
                     limit: int = 10) -> list[PlaceResult]:
        """Free-text search: a beach name, a town, a district. Nearest first when ``near`` is given.

        Returns an empty list when the lookup is unavailable, so the operator can still type a place
        in by hand rather than being blocked.
        """

    @abstractmethod
    async def nearby_beaches(self, lat: float, lon: float, radius_km: float,
                             limit: int = 20) -> list[PlaceResult]:
        """Beaches around a point, nearest first."""

    @property
    def available(self) -> bool:
        """False when the provider has no credentials and can only return empty lists."""
        return True

    @property
    def last_error(self) -> str | None:
        """Why the most recent lookup came back empty, for the operator to read."""
        return None
