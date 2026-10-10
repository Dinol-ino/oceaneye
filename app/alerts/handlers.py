"""Subscribes alert/escalation services to domain events (inter-module wiring)."""
from __future__ import annotations

from app.alerts.escalation.base import EscalationService
from app.alerts.services.base import AlertService
from app.core.domain.domain_events import (
    EventAcknowledged,
    EventCreated,
    EventEscalated,
    EventOutcomeRecorded,
)
from app.core.interfaces.event_bus import DomainEventBus


def register_alert_handlers(bus: DomainEventBus, alerts: AlertService, escalation: EscalationService) -> None:
    bus.subscribe(EventCreated, alerts.on_event_created)
    bus.subscribe(EventAcknowledged, alerts.on_event_acknowledged)
    bus.subscribe(EventOutcomeRecorded, alerts.on_event_outcome)
    bus.subscribe(EventEscalated, escalation.on_event_escalated)
