from __future__ import annotations

import logging
from datetime import timedelta

from app.alerts.notifications.base import NotificationProvider
from app.alerts.services.base import AlertService
from app.alerts.services.payloads import build_payload
from app.core.domain.domain_events import EventAcknowledged, EventCreated, EventOutcomeRecorded
from app.core.domain.ids import new_id
from app.core.entities.alert import Alert, AlertNotification, AlertPayload
from app.core.entities.event import Event
from app.core.enums import AlertNotificationType
from app.core.exceptions import NotFoundError
from app.core.interfaces.clock import Clock
from app.core.interfaces.repositories import AlertRepository, EventRepository

logger = logging.getLogger(__name__)


class DefaultAlertService(AlertService):
    """Creates/updates alerts in reaction to event lifecycle changes and delivers them through
    the NotificationProvider boundary."""

    def __init__(self, alerts: AlertRepository, events: EventRepository, notifier: NotificationProvider,
                 clock: Clock, ack_timeout_seconds: int, api_prefix: str) -> None:
        self._alerts = alerts
        self._events = events
        self._notifier = notifier
        self._clock = clock
        self._ack_timeout = timedelta(seconds=ack_timeout_seconds)
        self._prefix = api_prefix

    async def _deliver(self, alert: Alert, event: Event, kind: AlertNotificationType) -> None:
        now = self._clock.now()
        notification = AlertNotification(kind, build_payload(event, alert, self._prefix), now)
        alert.deliveries.extend(await self._notifier.send(notification))
        self._alerts.save(alert)

    async def on_event_created(self, e: EventCreated) -> None:
        now = self._clock.now()
        for existing in self._alerts.list(active_only=True, limit=50):
            ev = self._events.get(existing.event_id)
            if ev and ev.camera_id == e.event.camera_id and ev.track_id == e.event.track_id:
                logger.info("alert coalesced for active track %s on camera %s", e.event.track_id, e.event.camera_id)
                return
        alert = Alert(id=new_id("alt"), event_id=e.event.id, created_at=now, ack_deadline=now + self._ack_timeout)
        self._alerts.save(alert)
        logger.info("alert created", extra={"alert_id": alert.id, "event_id": e.event.id})
        await self._deliver(alert, e.event, AlertNotificationType.CREATED)

    async def on_event_acknowledged(self, e: EventAcknowledged) -> None:
        alert = self._alerts.get_by_event(e.event.id)
        if alert is None:
            return
        alert.acknowledged_at = self._clock.now()
        await self._deliver(alert, e.event, AlertNotificationType.ACKNOWLEDGED)

    async def on_event_outcome(self, e: EventOutcomeRecorded) -> None:
        alert = self._alerts.get_by_event(e.event.id)
        if alert is None:
            return
        alert.closed_at = self._clock.now()
        await self._deliver(alert, e.event, AlertNotificationType.CLOSED)

    def list_alerts(self, *, active_only: bool = True, limit: int = 50) -> list[Alert]:
        return self._alerts.list(active_only=active_only, limit=limit)

    def get(self, alert_id: str) -> Alert:
        alert = self._alerts.get(alert_id)
        if alert is None:
            raise NotFoundError("Alert", alert_id)
        return alert

    def build_payload(self, alert: Alert) -> AlertPayload:
        event = self._events.get(alert.event_id)
        if event is None:
            raise NotFoundError("Event", alert.event_id)
        return build_payload(event, alert, self._prefix)
