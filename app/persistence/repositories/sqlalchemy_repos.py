"""SQLAlchemy implementations of the repository ports (SQLite now, PostgreSQL later).
Each call uses its own short-lived session/transaction (thread-safe; no cross-repo atomicity -
PROPOSED SCAFFOLD, introduce a unit-of-work when needed)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from app.core.entities.alert import Alert
from app.core.entities.beach import Beach
from app.core.entities.camera import Camera
from app.core.entities.event import Event
from app.core.entities.processing import AnalysisJob, UploadedVideo
from app.core.entities.push import PushSubscription
from app.core.entities.zone import Zone
from app.core.exceptions import NotFoundError
from app.core.interfaces.repositories import (
    AlertRepository,
    BeachRepository,
    CameraRepository,
    EventFilter,
    EventRepository,
    JobRepository,
    PushSubscriptionRepository,
    UploadRepository,
    ZoneRepository,
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
from app.persistence.repositories import mappers as m


class SqlBeachRepository(BeachRepository):
    def __init__(self, sf: sessionmaker) -> None:
        self._sf = sf

    def save(self, beach: Beach) -> None:
        with self._sf() as s, s.begin():
            s.merge(m.beach_to_model(beach))

    def get(self, beach_id: str) -> Beach | None:
        with self._sf() as s:
            row = s.get(BeachModel, beach_id)
            return m.beach_to_entity(row) if row else None

    def list(self) -> list[Beach]:
        with self._sf() as s:
            rows = s.scalars(select(BeachModel).order_by(
                BeachModel.is_active.desc(), BeachModel.name, BeachModel.id)).all()
            return [m.beach_to_entity(r) for r in rows]

    def get_active(self) -> Beach | None:
        with self._sf() as s:
            row = s.scalars(select(BeachModel).where(BeachModel.is_active.is_(True))).first()
            return m.beach_to_entity(row) if row else None

    def set_active(self, beach_id: str) -> Beach:
        """One transaction, so there is never a moment with two active beaches or none."""
        with self._sf() as s, s.begin():
            row = s.get(BeachModel, beach_id)
            if row is None:
                raise NotFoundError("Beach", beach_id)
            s.execute(update(BeachModel).where(BeachModel.id != beach_id).values(is_active=False))
            row.is_active = True
            s.flush()
            return m.beach_to_entity(row)

    def find_by_source_id(self, source_id: str) -> Beach | None:
        with self._sf() as s:
            row = s.scalars(select(BeachModel).where(BeachModel.source_id == source_id)).first()
            return m.beach_to_entity(row) if row else None


class SqlCameraRepository(CameraRepository):
    def __init__(self, sf: sessionmaker) -> None:
        self._sf = sf

    def save(self, camera: Camera) -> None:
        with self._sf() as s, s.begin():
            s.merge(m.camera_to_model(camera))

    def get(self, camera_id: str) -> Camera | None:
        with self._sf() as s:
            row = s.get(CameraModel, camera_id)
            return m.camera_to_entity(row) if row else None

    def list(self, beach_id: str | None = None) -> list[Camera]:
        stmt = select(CameraModel)
        if beach_id is not None:
            stmt = stmt.where(CameraModel.beach_id == beach_id)
        stmt = stmt.order_by(CameraModel.created_at, CameraModel.id)
        with self._sf() as s:
            return [m.camera_to_entity(r) for r in s.scalars(stmt).all()]


class SqlZoneRepository(ZoneRepository):
    def __init__(self, sf: sessionmaker) -> None:
        self._sf = sf

    def save(self, zone: Zone) -> None:
        with self._sf() as s, s.begin():
            s.merge(m.zone_to_model(zone))

    def get_by_camera(self, camera_id: str) -> Zone | None:
        with self._sf() as s:
            row = s.scalars(select(ZoneModel).where(ZoneModel.camera_id == camera_id)).first()
            return m.zone_to_entity(row) if row else None


class SqlEventRepository(EventRepository):
    def __init__(self, sf: sessionmaker) -> None:
        self._sf = sf

    def save(self, event: Event) -> None:
        with self._sf() as s, s.begin():
            s.merge(m.event_to_model(event))

    def get(self, event_id: str) -> Event | None:
        with self._sf() as s:
            row = s.get(EventModel, event_id)
            return m.event_to_entity(row) if row else None

    def list(self, flt: EventFilter) -> list[Event]:
        stmt = select(EventModel)
        if flt.camera_id:
            stmt = stmt.where(EventModel.camera_id == flt.camera_id)
        if flt.status:
            stmt = stmt.where(EventModel.status == flt.status.value)
        if flt.started_after:
            stmt = stmt.where(EventModel.started_at >= flt.started_after)
        if flt.started_before:
            stmt = stmt.where(EventModel.started_at <= flt.started_before)
        stmt = stmt.order_by(EventModel.started_at.desc(), EventModel.id).limit(flt.limit).offset(flt.offset)
        with self._sf() as s:
            return [m.event_to_entity(r) for r in s.scalars(stmt).all()]


class SqlAlertRepository(AlertRepository):
    def __init__(self, sf: sessionmaker) -> None:
        self._sf = sf

    def save(self, alert: Alert) -> None:
        with self._sf() as s, s.begin():
            s.merge(m.alert_to_model(alert))

    def get(self, alert_id: str) -> Alert | None:
        with self._sf() as s:
            row = s.get(AlertModel, alert_id)
            return m.alert_to_entity(row) if row else None

    def get_by_event(self, event_id: str) -> Alert | None:
        with self._sf() as s:
            row = s.scalars(select(AlertModel).where(AlertModel.event_id == event_id)).first()
            return m.alert_to_entity(row) if row else None

    def list(self, *, active_only: bool = True, limit: int = 50) -> list[Alert]:
        stmt = select(AlertModel)
        if active_only:
            stmt = stmt.where(AlertModel.closed_at.is_(None))
        stmt = stmt.order_by(AlertModel.created_at.desc(), AlertModel.id).limit(limit)
        with self._sf() as s:
            return [m.alert_to_entity(r) for r in s.scalars(stmt).all()]

    def list_overdue(self, now: datetime) -> list[Alert]:
        stmt = select(AlertModel).where(
            AlertModel.closed_at.is_(None), AlertModel.acknowledged_at.is_(None),
            AlertModel.escalation_level == 0, AlertModel.ack_deadline <= now,
        )
        with self._sf() as s:
            return [m.alert_to_entity(r) for r in s.scalars(stmt).all()]


class SqlUploadRepository(UploadRepository):
    def __init__(self, sf: sessionmaker) -> None:
        self._sf = sf

    def save(self, upload: UploadedVideo) -> None:
        with self._sf() as s, s.begin():
            s.merge(m.upload_to_model(upload))

    def get(self, upload_id: str) -> UploadedVideo | None:
        with self._sf() as s:
            row = s.get(UploadModel, upload_id)
            return m.upload_to_entity(row) if row else None

    def list(self) -> list[UploadedVideo]:
        with self._sf() as s:
            rows = s.scalars(select(UploadModel).order_by(UploadModel.created_at.desc(), UploadModel.id)).all()
            return [m.upload_to_entity(r) for r in rows]

    def delete(self, upload_id: str) -> None:
        with self._sf() as s, s.begin():
            row = s.get(UploadModel, upload_id)
            if row is not None:
                s.delete(row)


class SqlJobRepository(JobRepository):
    def __init__(self, sf: sessionmaker) -> None:
        self._sf = sf

    def save(self, job: AnalysisJob) -> None:
        with self._sf() as s, s.begin():
            s.merge(m.job_to_model(job))

    def get(self, job_id: str) -> AnalysisJob | None:
        with self._sf() as s:
            row = s.get(JobModel, job_id)
            return m.job_to_entity(row) if row else None

    def list(self, limit: int = 50) -> list[AnalysisJob]:
        with self._sf() as s:
            rows = s.scalars(select(JobModel).order_by(JobModel.created_at.desc(), JobModel.id).limit(limit)).all()
            return [m.job_to_entity(r) for r in rows]

    def delete(self, job_id: str) -> None:
        with self._sf() as s, s.begin():
            row = s.get(JobModel, job_id)
            if row is not None:
                s.delete(row)

    def list_by_upload(self, upload_id: str) -> list[AnalysisJob]:
        with self._sf() as s:
            rows = s.scalars(select(JobModel).where(JobModel.upload_id == upload_id)).all()
            return [m.job_to_entity(r) for r in rows]


class SqlPushSubscriptionRepository(PushSubscriptionRepository):
    def __init__(self, sf: sessionmaker) -> None:
        self._sf = sf

    def save(self, subscription: PushSubscription) -> None:
        with self._sf() as s, s.begin():
            s.merge(m.push_to_model(subscription))

    def list(self, role: str | None = None) -> list[PushSubscription]:
        stmt = select(PushSubscriptionModel)
        if role:
            stmt = stmt.where(PushSubscriptionModel.role == role)
        stmt = stmt.order_by(PushSubscriptionModel.created_at.desc(), PushSubscriptionModel.endpoint_hash)
        with self._sf() as s:
            return [m.push_to_entity(r) for r in s.scalars(stmt).all()]

    def delete(self, endpoint_hash: str) -> None:
        with self._sf() as s, s.begin():
            row = s.get(PushSubscriptionModel, endpoint_hash)
            if row is not None:
                s.delete(row)

    def touch(self, endpoint_hash: str, at: datetime, failures: int) -> None:
        with self._sf() as s, s.begin():
            row = s.get(PushSubscriptionModel, endpoint_hash)
            if row is None:
                return
            row.last_attempt_at = at
            row.consecutive_failures = failures
            if failures == 0:
                row.last_success_at = at
