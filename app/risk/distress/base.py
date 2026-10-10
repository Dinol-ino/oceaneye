"""Distress/behaviour contracts. FUTURE: implementations compute signals from tracks (+pose)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from app.core.enums import DistressSignalType
from app.vision.pose.base import PoseEstimate
from app.vision.tracking.base import Track


@dataclass(frozen=True)
class DistressSignal:
    type: DistressSignalType
    observed_at: datetime
    confidence: float | None = None
    detail: str | None = None


@dataclass(frozen=True)
class BehaviorAssessment:
    camera_id: str
    track_id: str
    assessed_at: datetime
    signals: tuple[DistressSignal, ...] = field(default_factory=tuple)
    observation_window_seconds: float | None = None  # how long evidence has been observed (persistence)


class BehaviorAnalyzer(ABC):
    @abstractmethod
    def analyze(self, track: Track, pose: PoseEstimate | None, now: datetime) -> BehaviorAssessment: ...
