from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.domain.domain_events import EventEscalated


class EscalationService(ABC):
    @abstractmethod
    async def on_event_escalated(self, e: EventEscalated) -> None:
        """Update the alert and notify the next tier."""

    @abstractmethod
    async def process_timeouts(self) -> list[str]:
        """Escalate every alert whose ack deadline passed; returns escalated event ids."""
