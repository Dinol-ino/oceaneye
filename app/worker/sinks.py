"""Where actionable assessments go. The reference wants the vision/risk pipeline and the alert API
as separate processes: production sink = HTTP POST /api/events (FUTURE HttpEventSink)."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from app.events.services.event_service import EventService
from app.events.services.mapping import command_from_assessment
from app.risk.engine.base import RiskAssessment

logger = logging.getLogger(__name__)


class EventSink(ABC):
    @abstractmethod
    async def submit(self, assessment: RiskAssessment) -> None: ...


class LoggingEventSink(EventSink):
    async def submit(self, assessment: RiskAssessment) -> None:
        logger.info("candidate event (log only)", extra={"camera_id": assessment.camera_id,
                                                         "track_id": assessment.track_id})


class InProcessEventSink(EventSink):
    """Single-process development/testing sink."""

    def __init__(self, events: EventService) -> None:
        self._events = events

    async def submit(self, assessment: RiskAssessment) -> None:
        await self._events.create_candidate(command_from_assessment(assessment))
