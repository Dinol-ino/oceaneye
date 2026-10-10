from __future__ import annotations

from typing import Sequence

from app.core.domain.frame import Frame
from app.vision.detection.base import Detection, Detector


class MockDetector(Detector):
    """MOCK: returns only the detections injected by the caller (none by default)."""

    def __init__(self, canned: Sequence[Detection] = ()) -> None:
        self._canned = list(canned)

    def detect(self, frame: Frame) -> list[Detection]:
        return list(self._canned)
