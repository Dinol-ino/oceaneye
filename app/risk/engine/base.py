"""Risk-engine contract: combine zone + behaviour + persistence + environment -> RiskAssessment.
First real version: interpretable rule-based. Later: learned temporal model / hybrid."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from app.core.enums import DistressSignalType, RiskLevel
from app.core.exceptions import DomainValidationError
from app.environment.context import EnvironmentContext
from app.environment.zones.models import ZoneAssessment
from app.risk.distress.base import BehaviorAssessment
from app.vision.tracking.base import Track


@dataclass(frozen=True)
class RiskInput:
    camera_id: str
    track: Track
    zone: ZoneAssessment
    behavior: BehaviorAssessment
    environment: EnvironmentContext
    now: datetime


@dataclass(frozen=True)
class RiskAssessment:
    camera_id: str
    track_id: str
    timestamp: datetime
    risk_score: float
    risk_level: RiskLevel | None
    contributing_signals: tuple[DistressSignalType, ...]
    reason: str
    actionable: bool  # engine's decision that a candidate event should be raised (gating + persistence)
    engine: str  # which implementation produced this (e.g. "mock")

    def __post_init__(self) -> None:
        if not 0.0 <= self.risk_score <= 1.0:
            raise DomainValidationError("risk_score must be within [0, 1]")


class RiskEngine(ABC):
    name: str = "unnamed"

    @abstractmethod
    def assess(self, risk_input: RiskInput) -> RiskAssessment: ...
