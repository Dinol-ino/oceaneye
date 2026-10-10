"""STUB StreamManager: tracks start/stop intent only. It never connects to real streams and
is not started at application startup."""
from __future__ import annotations

import logging

from app.camera.domain.sources import FrameSource, StreamManager
from app.camera.infrastructure.factory import CameraSourceFactory
from app.core.entities.camera import Camera
from app.core.enums import CameraStatus

logger = logging.getLogger(__name__)


class StubStreamManager(StreamManager):
    def __init__(self, factory: CameraSourceFactory | None = None) -> None:
        self._factory = factory or CameraSourceFactory()
        self._open: dict[str, FrameSource] = {}

    async def start(self, camera: Camera) -> None:
        source = self._factory.create(camera)  # raises NotImplementedFeature for real sources
        self._open[camera.id] = await source.open()
        logger.info("stub stream started", extra={"camera_id": camera.id})

    async def stop(self, camera_id: str) -> None:
        source = self._open.pop(camera_id, None)
        if source:
            await source.close()

    def status(self, camera_id: str) -> CameraStatus:
        return CameraStatus.ONLINE if camera_id in self._open else CameraStatus.UNKNOWN

    async def stop_all(self) -> None:
        for camera_id in list(self._open):
            await self.stop(camera_id)
