"""MOCK frame source: yields empty frames (image=None). No video, no CV."""
from __future__ import annotations

from datetime import datetime, timezone

from app.camera.domain.sources import CameraSource, FrameSource
from app.core.domain.frame import Frame
from app.core.enums import CameraSourceType


class MockFrameSource(FrameSource):
    def __init__(self, camera_id: str, max_frames: int = 3) -> None:
        self._camera_id = camera_id
        self._max = max_frames
        self._i = 0

    async def read(self) -> Frame | None:
        if self._i >= self._max:
            return None
        frame = Frame(camera_id=self._camera_id, captured_at=datetime.now(timezone.utc), index=self._i)
        self._i += 1
        return frame

    async def close(self) -> None:
        self._i = self._max


class MockCameraSource(CameraSource):
    source_type = CameraSourceType.MOCK

    def __init__(self, camera_id: str, max_frames: int = 3) -> None:
        self.camera_id = camera_id
        self._max_frames = max_frames

    async def open(self) -> FrameSource:
        return MockFrameSource(self.camera_id, self._max_frames)
