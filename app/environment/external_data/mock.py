from __future__ import annotations

from app.core.interfaces.clock import Clock
from app.environment.external_data.base import (
    EnvironmentalConditions,
    EnvironmentalDataProvider,
    PlaceDirectory,
    PlaceResult,
)


class MockEnvironmentalDataProvider(EnvironmentalDataProvider):
    """MOCK: makes no remote call and invents no measurements (all values None)."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    async def get_conditions(self, lat: float, lon: float) -> EnvironmentalConditions:
        return EnvironmentalConditions(lat=lat, lon=lon, fetched_at=self._clock.now(), source="mock",
                                       status="unavailable", error="mock provider")


class MockPlaceDirectory(PlaceDirectory):
    """MOCK: no lookup, returns nothing. The operator types a place in by hand instead."""

    async def search(self, text: str, *, near=None, limit: int = 10) -> list[PlaceResult]:
        return []

    async def nearby_beaches(self, lat: float, lon: float, radius_km: float,
                             limit: int = 20) -> list[PlaceResult]:
        return []

    @property
    def available(self) -> bool:
        return False

    @property
    def last_error(self) -> str | None:
        return "place search is switched off (OCEANEYE_PLACES_PROVIDER=mock)"
