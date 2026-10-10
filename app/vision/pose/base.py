"""Pose contract (FUTURE: YOLO-pose / MediaPipe Pose)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from app.core.domain.frame import Frame
from app.vision.tracking.base import Track


@dataclass(frozen=True)
class PoseKeypoint:
    name: str
    x: float
    y: float
    confidence: float


@dataclass(frozen=True)
class PoseEstimate:
    track_id: str
    timestamp: datetime
    keypoints: tuple[PoseKeypoint, ...]


class PoseEstimator(ABC):
    @abstractmethod
    def estimate(self, frame: Frame, tracks: list[Track]) -> dict[str, PoseEstimate]:
        """Pose per track id (tracks without a usable pose are omitted)."""

    def warmup(self) -> float:
        """Load and exercise the model now; return the seconds it took. Default: nothing to do."""
        return 0.0
