"""Tracking contract. FUTURE: ByteTrack / BoxMOT behind this interface.
Track ids are camera-scoped (e.g. 'C01-T17'); cross-camera re-identification is a later enhancement."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from app.vision.detection.base import Detection


@dataclass(frozen=True)
class Track:
    track_id: str
    camera_id: str
    history: tuple[Detection, ...]

    @property
    def current(self) -> Detection:
        return self.history[-1]

    @property
    def current_position(self) -> tuple[float, float]:
        return self.current.bbox.center

    @property
    def first_seen(self) -> datetime:
        return self.history[0].timestamp

    @property
    def last_seen(self) -> datetime:
        return self.history[-1].timestamp


class Tracker(ABC):
    @abstractmethod
    def update(self, camera_id: str, detections: list[Detection], timestamp: datetime) -> list[Track]: ...

    @abstractmethod
    def reset(self, camera_id: str) -> None: ...
