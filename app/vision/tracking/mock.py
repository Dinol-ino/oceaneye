from __future__ import annotations

from datetime import datetime

from app.vision.detection.base import Detection
from app.vision.tracking.base import Track, Tracker


class MockTracker(Tracker):
    """MOCK: one single-point track per detection, id by order. NOT real identity tracking."""

    def update(self, camera_id: str, detections: list[Detection], timestamp: datetime) -> list[Track]:
        return [Track(f"{camera_id}-mock{i}", camera_id, (d,)) for i, d in enumerate(detections)]

    def reset(self, camera_id: str) -> None:
        return None
