"""Domain <-> ORM mapping. The only place that knows both representations."""
from __future__ import annotations

from datetime import datetime

from app.core.domain.value_objects import GeoPoint, Polygon
from app.core.entities.alert import Alert, DeliveryRecord
from app.core.entities.beach import Beach
from app.core.entities.camera import Camera
from app.core.entities.event import Acknowledgement, Event, EventLocation, EvidenceRef
from app.core.entities.processing import AnalysisJob, UploadedVideo
from app.core.entities.push import PushSubscription
from app.core.entities.zone import Zone
from app.core.enums import (
    CameraSourceType,
    CameraStatus,
    DeliveryStatus,
    DistressSignalType,
    EventStatus,
    JobStatus,
    NotificationChannel,
    RiskLevel,
    Role,
    ZoneMode,
)
from app.persistence.models import (
    AlertModel,
    BeachModel,
    CameraModel,
    EventModel,
    JobModel,
    PushSubscriptionModel,
    UploadModel,
    ZoneModel,
)


def beach_to_model(b: Beach) -> BeachModel:
    return BeachModel(id=b.id, region=b.region, name=b.name, lat=b.location.lat, lon=b.location.lon,
                      is_active=b.is_active, authority_name=b.authority_name,
                      authority_phone=b.authority_phone, lifeguard_count=b.lifeguard_count,
                      notes=b.notes, source_id=b.source_id, created_at=b.created_at)


def beach_to_entity(m: BeachModel) -> Beach:
    return Beach(id=m.id, region=m.region, name=m.name, location=GeoPoint(m.lat, m.lon),
                 created_at=m.created_at, is_active=bool(m.is_active), authority_name=m.authority_name,
                 authority_phone=m.authority_phone, lifeguard_count=m.lifeguard_count or 0,
                 notes=m.notes, source_id=m.source_id)


def camera_to_model(c: Camera) -> CameraModel:
    return CameraModel(id=c.id, name=c.name, lat=c.location.lat, lon=c.location.lon, stream_url=c.stream_url,
                       source_type=c.source_type.value, status=c.status.value, created_at=c.created_at,
                       beach_id=c.beach_id)


def camera_to_entity(m: CameraModel) -> Camera:
    return Camera(m.id, m.name, GeoPoint(m.lat, m.lon), m.stream_url, CameraSourceType(m.source_type),
                  CameraStatus(m.status), m.created_at, beach_id=m.beach_id)


def zone_to_model(z: Zone) -> ZoneModel:
    return ZoneModel(id=z.id, camera_id=z.camera_id, name=z.name, mode=z.mode.value,
                     polygon=[list(p) for p in z.polygon.points], updated_at=z.updated_at)


def zone_to_entity(m: ZoneModel) -> Zone:
    return Zone(m.id, m.camera_id, m.name, Polygon(tuple((float(x), float(y)) for x, y in m.polygon)),
                ZoneMode(m.mode), m.updated_at)


def event_to_model(e: Event) -> EventModel:
    ack = e.acknowledgement
    return EventModel(
        id=e.id, camera_id=e.camera_id, track_id=e.track_id, started_at=e.started_at, risk_score=e.risk_score,
        risk_level=e.risk_level.value if e.risk_level else None, status=e.status.value,
        distress_signals=[s.value for s in e.distress_signals], reason=e.reason,
        evidence_clip_key=e.evidence.clip_key if e.evidence else None,
        evidence_thumbnail_key=e.evidence.thumbnail_key if e.evidence else None,
        loc_lat=e.location.lat, loc_lon=e.location.lon, zone_name=e.location.zone_name,
        ack_by=ack.by if ack else None, ack_at=ack.at if ack else None, ack_note=ack.note if ack else None,
        escalation_level=e.escalation_level, escalated_at=e.escalated_at, escalation_reason=e.escalation_reason,
        closed_at=e.closed_at, outcome_note=e.outcome_note, created_at=e.created_at, updated_at=e.updated_at,
    )


def event_to_entity(m: EventModel) -> Event:
    evidence = (EvidenceRef(m.evidence_clip_key, m.evidence_thumbnail_key)
                if (m.evidence_clip_key or m.evidence_thumbnail_key) else None)
    ack = Acknowledgement(m.ack_by, m.ack_at, m.ack_note) if m.ack_by and m.ack_at else None
    return Event(
        id=m.id, camera_id=m.camera_id, track_id=m.track_id, started_at=m.started_at, risk_score=m.risk_score,
        status=EventStatus(m.status), location=EventLocation(m.loc_lat, m.loc_lon, m.zone_name),
        created_at=m.created_at, updated_at=m.updated_at,
        risk_level=RiskLevel(m.risk_level) if m.risk_level else None,
        distress_signals=[DistressSignalType(s) for s in m.distress_signals], reason=m.reason, evidence=evidence,
        acknowledgement=ack, escalation_level=m.escalation_level, escalated_at=m.escalated_at,
        escalation_reason=m.escalation_reason, closed_at=m.closed_at, outcome_note=m.outcome_note,
    )


def alert_to_model(a: Alert) -> AlertModel:
    return AlertModel(
        id=a.id, event_id=a.event_id, created_at=a.created_at, ack_deadline=a.ack_deadline,
        acknowledged_at=a.acknowledged_at, escalation_level=a.escalation_level, closed_at=a.closed_at,
        deliveries=[{"channel": d.channel.value, "status": d.status.value, "at": d.at.isoformat(),
                     "detail": d.detail} for d in a.deliveries],
    )


def alert_to_entity(m: AlertModel) -> Alert:
    return Alert(
        id=m.id, event_id=m.event_id, created_at=m.created_at, ack_deadline=m.ack_deadline,
        acknowledged_at=m.acknowledged_at, escalation_level=m.escalation_level, closed_at=m.closed_at,
        deliveries=[DeliveryRecord(NotificationChannel(d["channel"]), DeliveryStatus(d["status"]),
                                   datetime.fromisoformat(d["at"]), d.get("detail")) for d in m.deliveries],
    )


def upload_to_model(u: UploadedVideo) -> UploadModel:
    return UploadModel(id=u.id, filename=u.filename, stored_name=u.stored_name, size_bytes=u.size_bytes,
                       created_at=u.created_at)


def upload_to_entity(m: UploadModel) -> UploadedVideo:
    return UploadedVideo(m.id, m.filename, m.stored_name, m.size_bytes, m.created_at)


def job_to_model(j: AnalysisJob) -> JobModel:
    return JobModel(id=j.id, upload_id=j.upload_id, camera_id=j.camera_id, status=j.status.value,
                    created_at=j.created_at, options=dict(j.options), progress=j.progress, started_at=j.started_at,
                    finished_at=j.finished_at, error=j.error, summary=dict(j.summary), overlay_key=j.overlay_key,
                    events_created=j.events_created)


def job_to_entity(m: JobModel) -> AnalysisJob:
    return AnalysisJob(id=m.id, upload_id=m.upload_id, camera_id=m.camera_id, status=JobStatus(m.status),
                       created_at=m.created_at, options=dict(m.options or {}), progress=m.progress,
                       started_at=m.started_at, finished_at=m.finished_at, error=m.error,
                       summary=dict(m.summary or {}), overlay_key=m.overlay_key, events_created=m.events_created)


def push_to_model(s: PushSubscription) -> PushSubscriptionModel:
    return PushSubscriptionModel(endpoint_hash=s.endpoint_hash, endpoint=s.endpoint, p256dh_key=s.p256dh_key,
                                 auth_key=s.auth_key, role=s.role.value, label=s.label,
                                 created_at=s.created_at, last_success_at=s.last_success_at,
                                 last_attempt_at=s.last_attempt_at, consecutive_failures=s.consecutive_failures,
                                 assigned_camera_ids=list(s.assigned_camera_ids) or None)


def push_to_entity(m: PushSubscriptionModel) -> PushSubscription:
    return PushSubscription(endpoint_hash=m.endpoint_hash, endpoint=m.endpoint, p256dh_key=m.p256dh_key,
                            auth_key=m.auth_key, role=Role(m.role), created_at=m.created_at, label=m.label,
                            last_success_at=m.last_success_at, last_attempt_at=m.last_attempt_at,
                            consecutive_failures=m.consecutive_failures or 0,
                            assigned_camera_ids=tuple(m.assigned_camera_ids or ()))
