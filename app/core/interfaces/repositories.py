"""Repository ports. Infrastructure (SQLite now, PostgreSQL later) implements these."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from app.core.entities.alert import Alert
from app.core.entities.beach import Beach
from app.core.entities.camera import Camera
from app.core.entities.event import Event
from app.core.entities.processing import AnalysisJob, UploadedVideo
from app.core.entities.push import PushSubscription
from app.core.entities.zone import Zone
from app.core.enums import EventStatus


@dataclass(frozen=True)
class EventFilter:
    camera_id: str | None = None
    status: EventStatus | None = None
    started_after: datetime | None = None
    started_before: datetime | None = None
    limit: int = 50
    offset: int = 0


class BeachRepository(ABC):
    @abstractmethod
    def save(self, beach: Beach) -> None: ...

    @abstractmethod
    def get(self, beach_id: str) -> Beach | None: ...

    @abstractmethod
    def list(self) -> list[Beach]:
        """All configured beaches, the active one first."""

    @abstractmethod
    def get_active(self) -> Beach | None:
        """The single beach this installation is deployed at, if one has been chosen."""

    @abstractmethod
    def set_active(self, beach_id: str) -> Beach:
        """Make ``beach_id`` the active beach and deactivate every other, atomically."""

    @abstractmethod
    def find_by_source_id(self, source_id: str) -> Beach | None:
        """Lookup by external (OpenStreetMap) id, so adding the same beach twice is a no-op."""


class CameraRepository(ABC):
    @abstractmethod
    def save(self, camera: Camera) -> None: ...

    @abstractmethod
    def get(self, camera_id: str) -> Camera | None: ...

    @abstractmethod
    def list(self, beach_id: str | None = None) -> list[Camera]:
        """All cameras, or only those belonging to ``beach_id``."""


class ZoneRepository(ABC):
    @abstractmethod
    def save(self, zone: Zone) -> None: ...

    @abstractmethod
    def get_by_camera(self, camera_id: str) -> Zone | None: ...


class EventRepository(ABC):
    @abstractmethod
    def save(self, event: Event) -> None:
        """Insert or update."""

    @abstractmethod
    def get(self, event_id: str) -> Event | None: ...

    @abstractmethod
    def list(self, flt: EventFilter) -> list[Event]:
        """Newest first."""


class AlertRepository(ABC):
    @abstractmethod
    def save(self, alert: Alert) -> None: ...

    @abstractmethod
    def get(self, alert_id: str) -> Alert | None: ...

    @abstractmethod
    def get_by_event(self, event_id: str) -> Alert | None: ...

    @abstractmethod
    def list(self, *, active_only: bool = True, limit: int = 50) -> list[Alert]: ...

    @abstractmethod
    def list_overdue(self, now: datetime) -> list[Alert]:
        """Active, never acknowledged, not yet escalated, deadline passed."""


class UploadRepository(ABC):
    @abstractmethod
    def save(self, upload: UploadedVideo) -> None: ...

    @abstractmethod
    def get(self, upload_id: str) -> UploadedVideo | None: ...

    @abstractmethod
    def list(self) -> list[UploadedVideo]: ...

    @abstractmethod
    def delete(self, upload_id: str) -> None:
        """Forget this upload. Deleting one that is already gone is not an error."""


class JobRepository(ABC):
    @abstractmethod
    def save(self, job: AnalysisJob) -> None: ...

    @abstractmethod
    def get(self, job_id: str) -> AnalysisJob | None: ...

    @abstractmethod
    def list(self, limit: int = 50) -> list[AnalysisJob]:
        """Newest first."""

    @abstractmethod
    def delete(self, job_id: str) -> None:
        """Forget this job record. Deleting one that is already gone is not an error."""

    @abstractmethod
    def list_by_upload(self, upload_id: str) -> list[AnalysisJob]:
        """Every job that ran against this upload, so callers can refuse to orphan one."""


class PushSubscriptionRepository(ABC):
    """Browser Web Push endpoints, so a closed lifeguard app can still be woken."""

    @abstractmethod
    def save(self, subscription: PushSubscription) -> None: ...

    @abstractmethod
    def list(self, role: str | None = None) -> list[PushSubscription]: ...

    @abstractmethod
    def delete(self, endpoint_hash: str) -> None:
        """Remove a subscription the push service has rejected as gone."""

    @abstractmethod
    def touch(self, endpoint_hash: str, at: datetime, failures: int) -> None:
        """Record the outcome of the last delivery attempt."""
