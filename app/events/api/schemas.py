"""Event API schemas (scaffold contracts; minimal fields from reference section 7)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.core.entities.event import Event
from app.core.enums import DistressSignalType, EventStatus, RiskLevel
from app.security.validation import SAFE_ID_PATTERN, validate_storage_key


class EvidenceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clip_key: str | None = None
    thumbnail_key: str | None = None

    @field_validator("clip_key", "thumbnail_key")
    @classmethod
    def _key(cls, v):
        return validate_storage_key(v) if v is not None else v


class LocationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    zone_name: str | None = Field(default=None, max_length=120)


class EventCreate(BaseModel):
    """Raised by the vision/risk service (role 'service')."""

    model_config = ConfigDict(extra="forbid")
    camera_id: str = Field(pattern=SAFE_ID_PATTERN)
    track_id: str = Field(min_length=1, max_length=64)
    risk_score: float = Field(ge=0.0, le=1.0)
    risk_level: RiskLevel | None = None
    started_at: AwareDatetime | None = None
    distress_signals: list[DistressSignalType] = Field(default_factory=list, max_length=20)
    reason: str | None = Field(default=None, max_length=500)
    evidence: EvidenceIn | None = None
    location: LocationIn | None = None


class AckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(default=None, max_length=500)


class EscalateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="manual escalation", min_length=1, max_length=500)


class OutcomeRequest(BaseModel):
    """PROPOSED SCAFFOLD (not in the reference endpoint list): records resolved / false_alarm."""

    model_config = ConfigDict(extra="forbid")
    outcome: Literal["resolved", "false_alarm"]
    note: str | None = Field(default=None, max_length=500)


class LocationOut(BaseModel):
    lat: float
    lon: float
    zone_name: str | None = None


class AcknowledgementOut(BaseModel):
    by: str
    at: datetime
    note: str | None = None


class EventResponse(BaseModel):
    id: str
    camera_id: str
    track_id: str
    started_at: datetime
    risk_score: float
    risk_level: RiskLevel | None
    status: EventStatus
    distress_signals: list[DistressSignalType]
    reason: str | None
    location: LocationOut
    evidence_clip_url: str | None
    evidence_thumbnail_url: str | None
    acknowledgement: AcknowledgementOut | None
    escalation_level: int
    escalated_at: datetime | None
    closed_at: datetime | None
    outcome_note: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, e: Event, api_prefix: str) -> "EventResponse":
        ev = e.evidence
        base = f"{api_prefix}/evidence/{e.id}"
        return cls(
            id=e.id, camera_id=e.camera_id, track_id=e.track_id, started_at=e.started_at,
            risk_score=e.risk_score, risk_level=e.risk_level, status=e.status,
            distress_signals=list(e.distress_signals), reason=e.reason,
            location=LocationOut(lat=e.location.lat, lon=e.location.lon, zone_name=e.location.zone_name),
            evidence_clip_url=f"{base}/clip" if ev and ev.clip_key else None,
            evidence_thumbnail_url=f"{base}/thumbnail" if ev and ev.thumbnail_key else None,
            acknowledgement=(AcknowledgementOut(by=e.acknowledgement.by, at=e.acknowledgement.at,
                                                note=e.acknowledgement.note) if e.acknowledgement else None),
            escalation_level=e.escalation_level, escalated_at=e.escalated_at, closed_at=e.closed_at,
            outcome_note=e.outcome_note, created_at=e.created_at, updated_at=e.updated_at,
        )
