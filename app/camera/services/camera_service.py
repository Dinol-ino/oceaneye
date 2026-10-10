from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.domain.ids import new_id
from app.core.domain.value_objects import GeoPoint, Polygon
from app.core.entities.camera import Camera
from app.core.enums import CameraSourceType, CameraStatus
from app.core.exceptions import NotFoundError
from app.core.interfaces.clock import Clock
from app.core.interfaces.repositories import CameraRepository
from app.environment.zones.service import ZoneService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NewCameraCommand:
    name: str
    lat: float
    lon: float
    stream_url: str
    source_type: CameraSourceType
    zone_polygon: tuple[tuple[float, float], ...] | None = None
    beach_id: str | None = None


class CameraService:
    def __init__(self, cameras: CameraRepository, zones: ZoneService, clock: Clock) -> None:
        self._cameras = cameras
        self._zones = zones
        self._clock = clock

    def register(self, cmd: NewCameraCommand) -> Camera:
        camera = Camera(
            id=new_id("cam"),
            name=cmd.name,
            location=GeoPoint(cmd.lat, cmd.lon),
            stream_url=cmd.stream_url,
            source_type=cmd.source_type,
            status=CameraStatus.UNKNOWN,  # no stream is opened at registration
            created_at=self._clock.now(),
            beach_id=cmd.beach_id,
        )
        self._cameras.save(camera)
        if cmd.zone_polygon:
            self._zones.set_static_zone(camera.id, Polygon(cmd.zone_polygon), name="default")
        logger.info("camera registered", extra={"camera_id": camera.id, "beach_id": cmd.beach_id})
        return camera

    def list(self, beach_id: str | None = None) -> list[Camera]:
        """All cameras, or only one beach's. The Control Room passes the active beach."""
        return self._cameras.list(beach_id)

    def get(self, camera_id: str) -> Camera:
        camera = self._cameras.get(camera_id)
        if camera is None:
            raise NotFoundError("Camera", camera_id)
        return camera

    def assign_to_beach(self, camera_id: str, beach_id: str | None) -> Camera:
        """Move a camera between deployment sites (or detach it)."""
        camera = self.get(camera_id)
        camera.beach_id = beach_id
        self._cameras.save(camera)
        return camera
