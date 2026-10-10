"""Simple in-process domain event bus. Handler failures are logged and isolated so a
failing notification can never fail the originating API request.
(PROPOSED SCAFFOLD; replaceable by a broker if modules are ever split into services.)"""
from __future__ import annotations

import logging
from collections import defaultdict

from app.core.domain.domain_events import DomainEvent
from app.core.interfaces.event_bus import DomainEventBus, Handler

logger = logging.getLogger(__name__)


class InProcessEventBus(DomainEventBus):
    def __init__(self) -> None:
        self._handlers: dict[type, list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: type, handler: Handler) -> None:
        self._handlers[event_type].append(handler)

    async def publish(self, event: DomainEvent) -> None:
        for handler in self._handlers.get(type(event), []):
            try:
                await handler(event)
            except Exception:  # noqa: BLE001 - isolation is intentional
                logger.exception("domain event handler failed", extra={"event_type": type(event).__name__})
