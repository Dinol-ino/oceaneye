"""Visual water-motion analysis (optical flow / frame differencing) - FUTURE.
Deliberately separate from external wind/tide data."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from app.core.domain.frame import Frame
from app.core.entities.zone import Zone


@dataclass(frozen=True)
class WaterMotionEstimate:
    camera_id: str
    timestamp: datetime
    roughness: float | None  # None = not computed
    method: str


class WaterMotionAnalyzer(ABC):
    @abstractmethod
    def analyze(self, frame: Frame, zone: Zone | None) -> WaterMotionEstimate: ...
