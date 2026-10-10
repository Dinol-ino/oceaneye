from __future__ import annotations

from app.core.domain.frame import Frame
from app.vision.detection.base import Detector
from app.vision.pipeline.base import FrameResult, VisionPipeline
from app.vision.pose.base import PoseEstimator
from app.vision.tracking.base import Tracker


class DefaultVisionPipeline(VisionPipeline):
    """Composition of Detector -> Tracker -> optional PoseEstimator. Works with mocks today and
    with YOLO/ByteTrack implementations later, unchanged."""

    def __init__(self, detector: Detector, tracker: Tracker, pose: PoseEstimator | None = None) -> None:
        self._detector = detector
        self._tracker = tracker
        self._pose = pose

    def process(self, frame: Frame) -> FrameResult:
        detections = self._detector.detect(frame)
        tracks = self._tracker.update(frame.camera_id, detections, frame.captured_at)
        poses = self._pose.estimate(frame, tracks) if self._pose else {}
        return FrameResult(frame.camera_id, frame.captured_at, detections, tracks, poses)

    def reset(self, camera_id: str) -> None:
        self._tracker.reset(camera_id)

    def warmup(self) -> float:
        """Delegate to any stage that has a start-up cost (the detector loads and compiles a model)."""
        return sum(stage.warmup() for stage in (self._detector, self._pose) if stage is not None)
