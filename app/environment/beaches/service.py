"""The beach this installation watches: search for it, configure it, keep exactly one active.

Framework-free; the API router translates HTTP to these calls.

Setting up a deployment is one search box. You type a beach, a town or a district, pick the right
result, and that becomes the site. There is no built-in list of regions to choose from - a hardcoded
list is wrong the moment someone deploys somewhere it does not mention.

The invariant this service owns: **exactly one beach is active** once any beach exists. That is the
single-beach reality of a real installation, expressed as data rather than as a config file the
operator cannot change.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.domain.ids import new_id
from app.core.domain.value_objects import GeoPoint
from app.core.entities.beach import Beach
from app.core.exceptions import DomainValidationError, NotFoundError
from app.core.interfaces.clock import Clock
from app.core.interfaces.repositories import BeachRepository, CameraRepository
from app.environment.external_data.base import PlaceDirectory, PlaceResult

logger = logging.getLogger(__name__)

NEARBY_RADIUS_KM = 25.0
MIN_QUERY_LENGTH = 2


@dataclass(frozen=True)
class NewBeachCommand:
    name: str
    lat: float
    lon: float
    region: str = ""          # free text: "Mangaluru, Karnataka, India" - whatever the map returned
    authority_name: str | None = None
    authority_phone: str | None = None
    lifeguard_count: int = 0
    notes: str | None = None
    source_id: str | None = None
    activate: bool = False


@dataclass(frozen=True)
class BeachSeed:
    """Values from configuration used to create the first beach on a fresh installation."""

    name: str
    region: str
    lat: float
    lon: float
    authority_name: str | None = None
    authority_phone: str | None = None


class BeachService:
    def __init__(self, beaches: BeachRepository, cameras: CameraRepository, places: PlaceDirectory,
                 clock: Clock) -> None:
        self._beaches, self._cameras, self._places, self._clock = beaches, cameras, places, clock

    # -- configured sites ---------------------------------------------------
    def list(self) -> list[Beach]:
        return self._beaches.list()

    def get(self, beach_id: str) -> Beach:
        beach = self._beaches.get(beach_id)
        if beach is None:
            raise NotFoundError("Beach", beach_id)
        return beach

    def active(self) -> Beach | None:
        return self._beaches.get_active()

    def add(self, cmd: NewBeachCommand) -> Beach:
        """Configure a beach. Adding the same map result twice updates it instead of duplicating."""
        existing = self._beaches.find_by_source_id(cmd.source_id) if cmd.source_id else None
        beach = Beach(
            id=existing.id if existing else new_id("bch"),
            region=(cmd.region or "").strip(), name=cmd.name.strip(),
            location=GeoPoint(cmd.lat, cmd.lon),
            created_at=existing.created_at if existing else self._clock.now(),
            is_active=existing.is_active if existing else False,
            authority_name=cmd.authority_name, authority_phone=cmd.authority_phone,
            lifeguard_count=cmd.lifeguard_count, notes=cmd.notes, source_id=cmd.source_id,
        )
        self._beaches.save(beach)
        # The first beach configured becomes the deployment site: an installation is never useful
        # without one, and asking the operator to activate it separately is a step with one answer.
        if cmd.activate or self._beaches.get_active() is None:
            beach = self._beaches.set_active(beach.id)
        logger.info("beach configured", extra={"beach_id": beach.id, "active": beach.is_active})
        return beach

    def activate(self, beach_id: str) -> Beach:
        self.get(beach_id)  # 404 before mutating
        beach = self._beaches.set_active(beach_id)
        logger.info("deployment beach changed", extra={"beach_id": beach.id})
        return beach

    def update(self, beach_id: str, *, authority_name: str | None = None,
               authority_phone: str | None = None, lifeguard_count: int | None = None,
               notes: str | None = None) -> Beach:
        """Edit the details an operator maintains. Name and position are not editable: a beach that
        moved is a different site."""
        beach = self.get(beach_id)
        if authority_name is not None:
            beach.authority_name = authority_name.strip() or None
        if authority_phone is not None:
            beach.authority_phone = authority_phone.strip() or None
        if lifeguard_count is not None:
            if lifeguard_count < 0:
                raise DomainValidationError("lifeguard_count must not be negative")
            beach.lifeguard_count = lifeguard_count
        if notes is not None:
            beach.notes = notes.strip() or None
        self._beaches.save(beach)
        return beach

    def ensure_seeded(self, seed: BeachSeed) -> Beach:
        """Create the configured beach on a fresh installation, so the UI is never empty.

        Idempotent: once any beach exists, the active one is returned untouched.
        """
        active = self._beaches.get_active()
        if active is not None:
            return active
        existing = self._beaches.list()
        if existing:
            return self._beaches.set_active(existing[0].id)
        return self.add(NewBeachCommand(
            name=seed.name, region=seed.region, lat=seed.lat, lon=seed.lon,
            authority_name=seed.authority_name, authority_phone=seed.authority_phone, activate=True))

    def camera_count(self, beach_id: str) -> int:
        return len(self._cameras.list(beach_id))

    # -- map lookup -----------------------------------------------------------
    @property
    def search_available(self) -> bool:
        return self._places.available

    @property
    def search_error(self) -> str | None:
        return self._places.last_error

    async def search(self, text: str, *, near: tuple[float, float] | None = None,
                     limit: int = 10) -> list[PlaceResult]:
        """Free-text place search. Anything the operator types: a beach, a town, a district."""
        text = (text or "").strip()
        if len(text) < MIN_QUERY_LENGTH:
            raise DomainValidationError(f"search text must be at least {MIN_QUERY_LENGTH} characters")
        return await self._places.search(text, near=near, limit=limit)

    async def nearby_beaches(self, lat: float, lon: float,
                             radius_km: float = NEARBY_RADIUS_KM) -> list[PlaceResult]:
        """Beaches around a point - used both by the picker and by the dashboard map."""
        return await self._places.nearby_beaches(lat, lon, radius_km)
