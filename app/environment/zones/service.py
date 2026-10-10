from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.core.domain.geometry import point_in_polygon
from app.core.domain.ids import new_id
from app.core.domain.value_objects import Polygon
from app.core.entities.zone import Zone
from app.core.enums import ZoneMode
from app.core.interfaces.clock import Clock
from app.core.interfaces.repositories import ZoneRepository
from app.environment.zones.models import ZoneAssessment
from app.vision.tracking.base import Track


class ZoneService(ABC):
    @abstractmethod
    def get_zone(self, camera_id: str) -> Zone | None: ...

    @abstractmethod
    def set_static_zone(self, camera_id: str, polygon: Polygon, name: str = "default") -> Zone: ...


class RepositoryZoneService(ZoneService):
    """Static, manually configured zone (first prototype). FUTURE: dynamic zones plug in as
    another ZoneService without changing callers."""

    def __init__(self, zones: ZoneRepository, clock: Clock) -> None:
        self._zones = zones
        self._clock = clock

    def get_zone(self, camera_id: str) -> Zone | None:
        return self._zones.get_by_camera(camera_id)

    def set_static_zone(self, camera_id: str, polygon: Polygon, name: str = "default") -> Zone:
        existing = self._zones.get_by_camera(camera_id)
        zone = Zone(
            id=existing.id if existing else new_id("zone"),
            camera_id=camera_id, name=name, polygon=polygon,
            mode=ZoneMode.STATIC, updated_at=self._clock.now(),
        )
        self._zones.save(zone)
        return zone


class ZoneGate(ABC):
    """Zone-breach evaluation (pipeline stage 'gate')."""

    @abstractmethod
    def evaluate(self, track: Track, zone: Zone | None, now: datetime,
                 frame_size: tuple[int, int] | None = None) -> ZoneAssessment:
        """``frame_size`` = (width, height) in pixels; zone polygons are normalised 0..1."""


class MockZoneGate(ZoneGate):
    """MOCK: always 'not evaluated'. No breach logic is implemented."""

    def evaluate(self, track: Track, zone: Zone | None, now: datetime,
                 frame_size: tuple[int, int] | None = None) -> ZoneAssessment:
        return ZoneAssessment(track.camera_id, track.track_id, now, inside_zone=None,
                              zone_mode=zone.mode if zone else None)


class PolygonZoneGate(ZoneGate):
    """Static polygon gate (roadmap Stages 5-6): is the track's anchor point inside the camera's zone?

    Anchor = bottom-centre of the box by default (the waterline for a swimmer, the feet for a wader).
    ``inside_zone`` is None when no zone is configured; callers decide how to treat that.
    Remembers when each track entered the zone (``breach_since``) - dwell time is evidence too.
    """

    def __init__(self, anchor: str = "bottom") -> None:
        self._anchor = anchor
        self._entered: dict[str, datetime] = {}

    def evaluate(self, track: Track, zone: Zone | None, now: datetime,
                 frame_size: tuple[int, int] | None = None) -> ZoneAssessment:
        if zone is None or frame_size is None:
            return ZoneAssessment(track.camera_id, track.track_id, now, inside_zone=None)
        w, h = frame_size
        b = track.current.bbox
        x = (b.x_min + b.x_max) / 2 / w
        y = (b.y_max if self._anchor == "bottom" else (b.y_min + b.y_max) / 2) / h
        inside = point_in_polygon(x, y, zone.polygon.points)
        if inside:
            since = self._entered.setdefault(track.track_id, now)
        else:
            self._entered.pop(track.track_id, None)
            since = None
        return ZoneAssessment(track.camera_id, track.track_id, now, inside_zone=inside,
                              zone_mode=zone.mode, breach_since=since)
