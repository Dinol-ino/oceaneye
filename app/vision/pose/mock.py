from __future__ import annotations

from app.core.domain.frame import Frame
from app.vision.pose.base import PoseEstimate, PoseEstimator
from app.vision.tracking.base import Track


class MockPoseEstimator(PoseEstimator):
    """MOCK: never returns a pose."""

    def estimate(self, frame: Frame, tracks: list[Track]) -> dict[str, PoseEstimate]:
        return {}
