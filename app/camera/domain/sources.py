"""Video-source contracts. Implementations: mock now; RTSP/CCTV/mobile later."""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.entities.camera import Camera
from app.core.domain.frame import Frame
from app.core.enums import CameraSourceType, CameraStatus


class FrameSource(ABC):
    """An opened stream that yields frames."""

    @abstractmethod
    async def read(self) -> Frame | None:
        """Next frame, or None at end-of-stream."""

    @abstractmethod
    async def close(self) -> None: ...


class CameraSource(ABC):
    """Describes how to reach one camera; opening it yields a FrameSource."""

    camera_id: str
    source_type: CameraSourceType

    @abstractmethod
    async def open(self) -> FrameSource: ...


class StreamManager(ABC):
    """Owns running streams for registered cameras (one FrameSource per camera)."""

    @abstractmethod
    async def start(self, camera: Camera) -> None: ...

    @abstractmethod
    async def stop(self, camera_id: str) -> None: ...

    @abstractmethod
    def status(self, camera_id: str) -> CameraStatus: ...

    @abstractmethod
    async def stop_all(self) -> None: ...
