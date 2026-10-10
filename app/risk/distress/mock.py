from __future__ import annotations

from datetime import datetime

from app.risk.distress.base import BehaviorAnalyzer, BehaviorAssessment
from app.vision.pose.base import PoseEstimate
from app.vision.tracking.base import Track


class MockBehaviorAnalyzer(BehaviorAnalyzer):
    """MOCK: reports no distress signals."""

    def analyze(self, track: Track, pose: PoseEstimate | None, now: datetime) -> BehaviorAssessment:
        return BehaviorAssessment(track.camera_id, track.track_id, now)
