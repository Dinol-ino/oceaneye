from __future__ import annotations

import logging

from app.alerts.escalation.base import EscalationService
from app.alerts.notifications.base import NotificationProvider
from app.alerts.services.payloads import build_payload
from app.core.domain.domain_events import EventEscalated
from app.core.entities.alert import AlertNotification
from app.core.enums import AlertNotificationType
from app.core.exceptions import ConflictError
from app.core.interfaces.clock import Clock
from app.core.interfaces.repositories import AlertRepository
from app.events.services.event_service import EventService

logger = logging.getLogger(__name__)


class DefaultEscalationService(EscalationService):
    """Single escalation tier for now. TODO: multi-tier policy (senior lifeguard -> coastal
    authority), per-tier recipients and deadlines."""

    def __init__(self, alerts: AlertRepository, events: EventService, notifier: NotificationProvider,
                 clock: Clock, api_prefix: str) -> None:
        self._alerts = alerts
        self._events = events
        self._notifier = notifier
        self._clock = clock
        self._prefix = api_prefix

    async def on_event_escalated(self, e: EventEscalated) -> None:
        alert = self._alerts.get_by_event(e.event.id)
        if alert is None:
            return
        alert.escalation_level = e.event.escalation_level
        notification = AlertNotification(
            AlertNotificationType.ESCALATED, build_payload(e.event, alert, self._prefix), self._clock.now()
        )
        alert.deliveries.extend(await self._notifier.send(notification))
        self._alerts.save(alert)

    async def process_timeouts(self) -> list[str]:
        escalated: list[str] = []
        for alert in self._alerts.list_overdue(self._clock.now()):
            try:
                await self._events.escalate(alert.event_id, reason="acknowledgement timeout", automatic=True)
                escalated.append(alert.event_id)
            except ConflictError:
                logger.info("skip escalation (state changed)", extra={"event_id": alert.event_id})
        return escalated
