from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.core.entities.event import EventLocation, EvidenceRef
from app.core.enums import DistressSignalType, RiskLevel


@dataclass(frozen=True)
class NewEventCommand:
    camera_id: str
    track_id: str
    risk_score: float
    risk_level: RiskLevel | None = None
    started_at: datetime | None = None
    distress_signals: tuple[DistressSignalType, ...] = field(default_factory=tuple)
    reason: str | None = None
    evidence: EvidenceRef | None = None
    location: EventLocation | None = None  # defaults to camera location + zone name
