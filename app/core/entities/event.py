from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.core.domain.event_lifecycle import TERMINAL_STATUSES, can_transition
from app.core.enums import DistressSignalType, EventStatus, RiskLevel
from app.core.exceptions import DomainValidationError, InvalidStateTransition


@dataclass(frozen=True)
class EvidenceRef:
    """Opaque storage keys. Resolved to protected URLs by the API layer."""

    clip_key: str | None = None
    thumbnail_key: str | None = None


@dataclass(frozen=True)
class EventLocation:
    lat: float
    lon: float
    zone_name: str | None = None


@dataclass(frozen=True)
class Acknowledgement:
    by: str
    at: datetime
    note: str | None = None


@dataclass
class Event:
    """Candidate or confirmed drowning-risk event (reference section 7).

    Terminology: this is a *candidate* event requiring human interpretation, not a
    confirmed drowning.
    """

    id: str
    camera_id: str
    track_id: str  # camera-scoped track reference; no separate tracks table yet
    started_at: datetime
    risk_score: float
    status: EventStatus
    location: EventLocation
    created_at: datetime
    updated_at: datetime
    risk_level: RiskLevel | None = None
    distress_signals: list[DistressSignalType] = field(default_factory=list)
    reason: str | None = None
    evidence: EvidenceRef | None = None
    acknowledgement: Acknowledgement | None = None
    escalation_level: int = 0
    escalated_at: datetime | None = None
    escalation_reason: str | None = None
    closed_at: datetime | None = None
    outcome_note: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.risk_score <= 1.0:
            raise DomainValidationError("risk_score must be within [0, 1]")

    # -- behaviour ------------------------------------------------------
    def _transition(self, target: EventStatus) -> None:
        if not can_transition(self.status, target):
            raise InvalidStateTransition(
                f"Event {self.id}: cannot go from '{self.status.value}' to '{target.value}'"
            )
        self.status = target

    def acknowledge(self, by: str, at: datetime, note: str | None = None) -> None:
        self._transition(EventStatus.ACKNOWLEDGED)
        self.acknowledgement = Acknowledgement(by=by, at=at, note=note)
        self.updated_at = at

    def escalate(self, at: datetime, reason: str) -> None:
        self._transition(EventStatus.ESCALATED)
        self.escalation_level += 1
        self.escalated_at = at
        self.escalation_reason = reason
        self.updated_at = at

    def close(self, outcome: EventStatus, at: datetime, note: str | None = None) -> None:
        if outcome not in TERMINAL_STATUSES:
            raise DomainValidationError("outcome must be 'resolved' or 'false_alarm'")
        self._transition(outcome)
        self.closed_at = at
        self.outcome_note = note
        self.updated_at = at
