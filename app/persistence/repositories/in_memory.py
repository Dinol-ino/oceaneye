"""In-memory repositories: executable proof the ports are swappable, and handy test doubles."""
from __future__ import annotations

import copy
from datetime import datetime

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


class InMemoryBeachRepository(BeachRepository):
    def __init__(self) -> None:
        self._d: dict[str, Beach] = {}

    def save(self, beach: Beach) -> None:
        self._d[beach.id] = copy.deepcopy(beach)

    def get(self, beach_id: str) -> Beach | None:
        return copy.deepcopy(self._d.get(beach_id))

    def list(self) -> list[Beach]:
        rows = sorted(self._d.values(), key=lambda b: (not b.is_active, b.name, b.id))
        return [copy.deepcopy(b) for b in rows]

    def get_active(self) -> Beach | None:
        return next((copy.deepcopy(b) for b in self._d.values() if b.is_active), None)

    def set_active(self, beach_id: str) -> Beach:
        if beach_id not in self._d:
            raise NotFoundError("Beach", beach_id)
        for bid, beach in self._d.items():
            beach.is_active = bid == beach_id
        return copy.deepcopy(self._d[beach_id])

    def find_by_source_id(self, source_id: str) -> Beach | None:
        return next((copy.deepcopy(b) for b in self._d.values() if b.source_id == source_id), None)


class InMemoryCameraRepository(CameraRepository):
    def __init__(self) -> None:
        self._d: dict[str, Camera] = {}

    def save(self, camera: Camera) -> None:
        self._d[camera.id] = copy.deepcopy(camera)

    def get(self, camera_id: str) -> Camera | None:
        return copy.deepcopy(self._d.get(camera_id))

    def list(self, beach_id: str | None = None) -> list[Camera]:
        rows = [c for c in self._d.values() if beach_id is None or c.beach_id == beach_id]
        return [copy.deepcopy(c) for c in sorted(rows, key=lambda c: (c.created_at, c.id))]


class InMemoryZoneRepository(ZoneRepository):
    def __init__(self) -> None:
        self._d: dict[str, Zone] = {}

    def save(self, zone: Zone) -> None:
        self._d[zone.camera_id] = copy.deepcopy(zone)

    def get_by_camera(self, camera_id: str) -> Zone | None:
        return copy.deepcopy(self._d.get(camera_id))


class InMemoryEventRepository(EventRepository):
    def __init__(self) -> None:
        self._d: dict[str, Event] = {}

    def save(self, event: Event) -> None:
        self._d[event.id] = copy.deepcopy(event)

    def get(self, event_id: str) -> Event | None:
        return copy.deepcopy(self._d.get(event_id))

    def list(self, flt: EventFilter) -> list[Event]:
        rows = [e for e in self._d.values()
                if (not flt.camera_id or e.camera_id == flt.camera_id)
                and (not flt.status or e.status == flt.status)
                and (not flt.started_after or e.started_at >= flt.started_after)
                and (not flt.started_before or e.started_at <= flt.started_before)]
        rows.sort(key=lambda e: (-e.started_at.timestamp(), e.id))
        return [copy.deepcopy(e) for e in rows[flt.offset: flt.offset + flt.limit]]


class InMemoryAlertRepository(AlertRepository):
    def __init__(self) -> None:
        self._d: dict[str, Alert] = {}

    def save(self, alert: Alert) -> None:
        self._d[alert.id] = copy.deepcopy(alert)

    def get(self, alert_id: str) -> Alert | None:
        return copy.deepcopy(self._d.get(alert_id))

    def get_by_event(self, event_id: str) -> Alert | None:
        return next((copy.deepcopy(a) for a in self._d.values() if a.event_id == event_id), None)

    def list(self, *, active_only: bool = True, limit: int = 50) -> list[Alert]:
        rows = [a for a in self._d.values() if not active_only or a.closed_at is None]
        rows.sort(key=lambda a: (-a.created_at.timestamp(), a.id))
        return [copy.deepcopy(a) for a in rows[:limit]]

    def list_overdue(self, now: datetime) -> list[Alert]:
        return [copy.deepcopy(a) for a in self._d.values()
                if a.closed_at is None and a.acknowledged_at is None
                and a.escalation_level == 0 and a.ack_deadline <= now]


class InMemoryUploadRepository(UploadRepository):
    def __init__(self) -> None:
        self._d: dict[str, UploadedVideo] = {}

    def save(self, upload: UploadedVideo) -> None:
        self._d[upload.id] = copy.deepcopy(upload)

    def get(self, upload_id: str) -> UploadedVideo | None:
        return copy.deepcopy(self._d.get(upload_id))

    def list(self) -> list[UploadedVideo]:
        return [copy.deepcopy(u) for u in sorted(self._d.values(), key=lambda u: (-u.created_at.timestamp(), u.id))]

    def delete(self, upload_id: str) -> None:
        self._d.pop(upload_id, None)


class InMemoryJobRepository(JobRepository):
    def __init__(self) -> None:
        self._d: dict[str, AnalysisJob] = {}

    def save(self, job: AnalysisJob) -> None:
        self._d[job.id] = copy.deepcopy(job)

    def get(self, job_id: str) -> AnalysisJob | None:
        return copy.deepcopy(self._d.get(job_id))

    def list(self, limit: int = 50) -> list[AnalysisJob]:
        rows = sorted(self._d.values(), key=lambda j: (-j.created_at.timestamp(), j.id))
        return [copy.deepcopy(j) for j in rows[:limit]]

    def delete(self, job_id: str) -> None:
        self._d.pop(job_id, None)

    def list_by_upload(self, upload_id: str) -> list[AnalysisJob]:
        return [copy.deepcopy(j) for j in self._d.values() if j.upload_id == upload_id]


class InMemoryPushSubscriptionRepository(PushSubscriptionRepository):
    def __init__(self) -> None:
        self._d: dict[str, PushSubscription] = {}

    def save(self, subscription: PushSubscription) -> None:
        self._d[subscription.endpoint_hash] = copy.deepcopy(subscription)

    def list(self, role: str | None = None) -> list[PushSubscription]:
        rows = [s for s in self._d.values() if role is None or s.role.value == role]
        return [copy.deepcopy(s) for s in sorted(rows, key=lambda s: (-s.created_at.timestamp(), s.endpoint_hash))]

    def delete(self, endpoint_hash: str) -> None:
        self._d.pop(endpoint_hash, None)

    def touch(self, endpoint_hash: str, at: datetime, failures: int) -> None:
        s = self._d.get(endpoint_hash)
        if s is None:
            return
        s.last_attempt_at = at
        s.consecutive_failures = failures
        if failures == 0:
            s.last_success_at = at
