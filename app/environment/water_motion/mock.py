from __future__ import annotations

from app.core.domain.frame import Frame
from app.core.entities.zone import Zone
from app.environment.water_motion.base import WaterMotionAnalyzer, WaterMotionEstimate


class MockWaterMotionAnalyzer(WaterMotionAnalyzer):
    """MOCK: roughness is never computed."""

    def analyze(self, frame: Frame, zone: Zone | None) -> WaterMotionEstimate:
        return WaterMotionEstimate(frame.camera_id, frame.captured_at, roughness=None, method="mock")
