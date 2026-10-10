from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.core.entities.alert import Alert, AlertPayload
from app.core.enums import DeliveryStatus, DistressSignalType, EventStatus, NotificationChannel, RiskLevel


class LocationOut(BaseModel):
    lat: float
    lon: float
    zone_name: str | None = None


class AlertPayloadSchema(BaseModel):
    """Shared by REST and WebSocket. Mirrors the reference AlertPayload (+ scaffold fields)."""

    alert_id: str
    event_id: str
    camera_id: str
    track_id: str
    risk_score: float
    risk_level: RiskLevel | None
    timestamp: datetime
    location: LocationOut
    distress_signals: list[DistressSignalType]
    reason: str | None
    thumbnail_url: str | None
    clip_url: str | None
    ack_deadline: datetime
    event_status: EventStatus
    escalation_level: int

    @classmethod
    def from_domain(cls, p: AlertPayload) -> "AlertPayloadSchema":
        return cls(
            alert_id=p.alert_id, event_id=p.event_id, camera_id=p.camera_id, track_id=p.track_id,
            risk_score=p.risk_score, risk_level=p.risk_level, timestamp=p.timestamp,
            location=LocationOut(lat=p.location.lat, lon=p.location.lon, zone_name=p.location.zone_name),
            distress_signals=list(p.distress_signals), reason=p.reason, thumbnail_url=p.thumbnail_url,
            clip_url=p.clip_url, ack_deadline=p.ack_deadline, event_status=p.event_status,
            escalation_level=p.escalation_level,
        )


class DeliverySchema(BaseModel):
    channel: NotificationChannel
    status: DeliveryStatus
    at: datetime
    detail: str | None = None


class AlertResponse(BaseModel):
    id: str
    event_id: str
    created_at: datetime
    ack_deadline: datetime
    acknowledged_at: datetime | None
    escalation_level: int
    closed_at: datetime | None
    deliveries: list[DeliverySchema]
    payload: AlertPayloadSchema

    @classmethod
    def from_domain(cls, a: Alert, payload: AlertPayload) -> "AlertResponse":
        return cls(
            id=a.id, event_id=a.event_id, created_at=a.created_at, ack_deadline=a.ack_deadline,
            acknowledged_at=a.acknowledged_at, escalation_level=a.escalation_level, closed_at=a.closed_at,
            deliveries=[DeliverySchema(channel=d.channel, status=d.status, at=d.at, detail=d.detail)
                        for d in a.deliveries],
            payload=AlertPayloadSchema.from_domain(payload),
        )
