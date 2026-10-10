from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.core.enums import (
    AlertNotificationType,
    DeliveryStatus,
    DistressSignalType,
    EventStatus,
    NotificationChannel,
    RiskLevel,
)
from app.core.entities.event import EventLocation


@dataclass(frozen=True)
class DeliveryRecord:
    channel: NotificationChannel
    status: DeliveryStatus
    at: datetime
    detail: str | None = None


@dataclass
class Alert:
    """Delivery/ack tracking for one event. The event remains the source of truth for status."""

    id: str
    event_id: str
    created_at: datetime
    ack_deadline: datetime
    acknowledged_at: datetime | None = None
    escalation_level: int = 0
    closed_at: datetime | None = None
    deliveries: list[DeliveryRecord] = field(default_factory=list)

    @property
    def is_active(self) -> bool:
        return self.closed_at is None


@dataclass(frozen=True)
class AlertPayload:
    """What actually reaches a responder (reference section 7, AlertPayload) plus
    PROPOSED SCAFFOLD fields (alert_id, track_id, status, reasons) the lifeguard client needs."""

    alert_id: str
    event_id: str
    camera_id: str
    track_id: str
    risk_score: float
    risk_level: RiskLevel | None
    timestamp: datetime
    location: EventLocation
    distress_signals: tuple[DistressSignalType, ...]
    reason: str | None
    thumbnail_url: str | None
    clip_url: str | None
    ack_deadline: datetime
    event_status: EventStatus
    escalation_level: int


@dataclass(frozen=True)
class AlertNotification:
    """Envelope pushed through notification providers / WebSocket."""

    type: AlertNotificationType
    payload: AlertPayload
    sent_at: datetime
