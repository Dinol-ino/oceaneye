from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.domain.domain_events import (
    EventAcknowledged,
    EventCreated,
    EventOutcomeRecorded,
)
from app.core.entities.alert import Alert, AlertPayload


class AlertService(ABC):
    @abstractmethod
    async def on_event_created(self, e: EventCreated) -> None: ...

    @abstractmethod
    async def on_event_acknowledged(self, e: EventAcknowledged) -> None: ...

    @abstractmethod
    async def on_event_outcome(self, e: EventOutcomeRecorded) -> None: ...

    @abstractmethod
    def list_alerts(self, *, active_only: bool = True, limit: int = 50) -> list[Alert]: ...

    @abstractmethod
    def get(self, alert_id: str) -> Alert: ...

    @abstractmethod
    def build_payload(self, alert: Alert) -> AlertPayload: ...
