from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from app.core.domain.frame import Frame
from app.vision.detection.base import Detection
from app.vision.pose.base import PoseEstimate
from app.vision.tracking.base import Track


@dataclass(frozen=True)
class FrameResult:
    camera_id: str
    captured_at: datetime
    detections: list[Detection] = field(default_factory=list)
    tracks: list[Track] = field(default_factory=list)
    poses: dict[str, PoseEstimate] = field(default_factory=dict)


class VisionPipeline(ABC):
    """Perception only: frame -> detections -> tracks (-> poses). No risk reasoning here."""

    @abstractmethod
    def process(self, frame: Frame) -> FrameResult: ...

    def reset(self, camera_id: str) -> None:
        """Forget per-camera state (e.g. when a looped video restarts). Default: nothing to reset."""

    def warmup(self) -> float:
        """Pay any one-off model start-up cost now; return the seconds it took.

        Callers use this so the first real frame is not dramatically slower than the rest, and so
        measured frame rates describe steady state. Default: nothing to warm up.
        """
        return 0.0
