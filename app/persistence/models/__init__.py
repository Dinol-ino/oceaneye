"""ORM models (persistence layer only; never exposed through the API)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.database.base import Base
from app.persistence.database.types import UtcDateTime


class BeachModel(Base):
    """The deployment site. Exactly one row has ``is_active`` set (enforced by the repository)."""

    __tablename__ = "beaches"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    region: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(160))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    authority_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    authority_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    lifeguard_count: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)


class CameraModel(Base):
    __tablename__ = "cameras"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    stream_url: Mapped[str] = mapped_column(String(2048))
    source_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    # No FK: a camera may outlive the beach row it was attached to, and SQLite cannot add a
    # constrained column to an existing table (see Database._add_missing_columns).
    beach_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class ZoneModel(Base):
    __tablename__ = "zones"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id"), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    mode: Mapped[str] = mapped_column(String(16))
    polygon: Mapped[list] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)


class EventModel(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id"))
    track_id: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(UtcDateTime)
    risk_score: Mapped[float] = mapped_column(Float)
    risk_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(16))
    distress_signals: Mapped[list] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_clip_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    evidence_thumbnail_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    loc_lat: Mapped[float] = mapped_column(Float)
    loc_lon: Mapped[float] = mapped_column(Float)
    zone_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ack_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ack_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    ack_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    escalation_level: Mapped[int] = mapped_column(Integer, default=0)
    escalated_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    escalation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    outcome_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)

    __table_args__ = (Index("ix_events_camera_started", "camera_id", "started_at"),
                      Index("ix_events_status", "status"))


class AlertModel(Base):
    __tablename__ = "alerts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    ack_deadline: Mapped[datetime] = mapped_column(UtcDateTime)
    acknowledged_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    escalation_level: Mapped[int] = mapped_column(Integer, default=0)
    closed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    deliveries: Mapped[list] = mapped_column(JSON)


class UploadModel(Base):
    __tablename__ = "uploads"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)


class JobModel(Base):
    __tablename__ = "analysis_jobs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    upload_id: Mapped[str] = mapped_column(ForeignKey("uploads.id"))
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id"))
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    options: Mapped[dict] = mapped_column(JSON)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[dict] = mapped_column(JSON)
    overlay_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    events_created: Mapped[int] = mapped_column(Integer, default=0)


class PushSubscriptionModel(Base):
    """One browser's Web Push endpoint. ``endpoint`` is sensitive and never returned by the API."""

    __tablename__ = "push_subscriptions"
    endpoint_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    endpoint: Mapped[str] = mapped_column(Text)
    p256dh_key: Mapped[str] = mapped_column(String(200))
    auth_key: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(32), index=True)
    label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    #: Camera ids this guard covers; [] or NULL means roaming (every alert). JSON rather than a
    #: join table: it is a short list read on every alert and never queried across devices.
    assigned_camera_ids: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)


__all__ = ["BeachModel", "CameraModel", "ZoneModel", "EventModel", "AlertModel", "UploadModel", "JobModel",
           "PushSubscriptionModel"]
