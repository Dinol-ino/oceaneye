"""In-process domain events: the inter-module communication contract.

events -> (bus) -> alerts -> (notification provider) -> websocket.
The events module never imports alerts; alerts subscribe to these.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.entities.event import Event


@dataclass(frozen=True)
class DomainEvent:
    """Marker base class."""


@dataclass(frozen=True)
class EventCreated(DomainEvent):
    event: Event


@dataclass(frozen=True)
class EventAcknowledged(DomainEvent):
    event: Event


@dataclass(frozen=True)
class EventEscalated(DomainEvent):
    event: Event
    automatic: bool
    reason: str


@dataclass(frozen=True)
class EventOutcomeRecorded(DomainEvent):
    event: Event
