from __future__ import annotations

import logging

from app.core.domain.domain_events import (
    EventAcknowledged,
    EventCreated,
    EventEscalated,
    EventOutcomeRecorded,
)
from app.core.domain.ids import new_id
from app.core.entities.event import Event, EventLocation
from app.core.enums import EventStatus
from app.core.exceptions import NotFoundError
from app.core.interfaces.clock import Clock
from app.core.interfaces.event_bus import DomainEventBus
from app.core.interfaces.repositories import (
    CameraRepository,
    EventFilter,
    EventRepository,
    ZoneRepository,
)
from app.events.domain.commands import NewEventCommand

logger = logging.getLogger(__name__)


class EventService:
    """Owns the event lifecycle. Publishes domain events; knows nothing about alerts,
    notifications or WebSockets."""

    def __init__(self, events: EventRepository, cameras: CameraRepository, zones: ZoneRepository,
                 bus: DomainEventBus, clock: Clock) -> None:
        self._events = events
        self._cameras = cameras
        self._zones = zones
        self._bus = bus
        self._clock = clock

    async def create_candidate(self, cmd: NewEventCommand) -> Event:
        camera = self._cameras.get(cmd.camera_id)
        if camera is None:
            raise NotFoundError("Camera", cmd.camera_id)
        now = self._clock.now()
        location = cmd.location
        if location is None:
            zone = self._zones.get_by_camera(camera.id)
            location = EventLocation(camera.location.lat, camera.location.lon, zone.name if zone else None)
        event = Event(
            id=new_id("evt"), camera_id=camera.id, track_id=cmd.track_id,
            started_at=cmd.started_at or now, risk_score=cmd.risk_score, risk_level=cmd.risk_level,
            status=EventStatus.PENDING, distress_signals=list(cmd.distress_signals), reason=cmd.reason,
            evidence=cmd.evidence, location=location, created_at=now, updated_at=now,
        )
        self._events.save(event)
        logger.info("event created", extra={"event_id": event.id, "camera_id": event.camera_id})
        await self._bus.publish(EventCreated(event))
        return event

    def get(self, event_id: str) -> Event:
        event = self._events.get(event_id)
        if event is None:
            raise NotFoundError("Event", event_id)
        return event

    def list(self, flt: EventFilter) -> list[Event]:
        return self._events.list(flt)

    async def acknowledge(self, event_id: str, *, by: str, note: str | None = None) -> Event:
        event = self.get(event_id)
        event.acknowledge(by, self._clock.now(), note)
        self._events.save(event)
        logger.info("event acknowledged", extra={"event_id": event.id, "by": by})
        await self._bus.publish(EventAcknowledged(event))
        return event

    async def escalate(self, event_id: str, *, reason: str, automatic: bool = False) -> Event:
        event = self.get(event_id)
        event.escalate(self._clock.now(), reason)
        self._events.save(event)
        logger.info("event escalated", extra={"event_id": event.id, "automatic": automatic})
        await self._bus.publish(EventEscalated(event, automatic=automatic, reason=reason))
        return event

    async def record_outcome(self, event_id: str, *, outcome: EventStatus, note: str | None = None) -> Event:
        event = self.get(event_id)
        event.close(outcome, self._clock.now(), note)
        self._events.save(event)
        logger.info("event outcome recorded", extra={"event_id": event.id, "outcome": outcome.value})
        await self._bus.publish(EventOutcomeRecorded(event))
        return event
