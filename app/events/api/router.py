from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.core.entities.event import EventLocation, EvidenceRef
from app.core.enums import EventStatus
from app.core.interfaces.repositories import EventFilter
from app.events.api.schemas import (
    AckRequest,
    EscalateRequest,
    EventCreate,
    EventResponse,
    OutcomeRequest,
)
from app.events.domain.commands import NewEventCommand
from app.events.services.event_service import EventService
from app.security.authorization import EVENT_PRODUCER_ROLES, RESPONDER_ROLES
from app.security.dependencies import require_roles
from app.security.principal import Principal
from app.security.validation import SAFE_ID_PATTERN
from app.shared.dependencies import get_api_prefix, get_event_service

router = APIRouter(prefix="/events", tags=["events"])
EventId = Annotated[str, Path(pattern=SAFE_ID_PATTERN)]


@router.post("", response_model=EventResponse, status_code=201,
             dependencies=[Depends(require_roles(*EVENT_PRODUCER_ROLES))])
async def create_event(body: EventCreate, service: EventService = Depends(get_event_service),
                       prefix: str = Depends(get_api_prefix)):
    """Vision/risk service raises a *candidate* event. Not a confirmed drowning."""
    event = await service.create_candidate(NewEventCommand(
        camera_id=body.camera_id, track_id=body.track_id, risk_score=body.risk_score,
        risk_level=body.risk_level, started_at=body.started_at,
        distress_signals=tuple(body.distress_signals), reason=body.reason,
        evidence=EvidenceRef(**body.evidence.model_dump()) if body.evidence else None,
        location=EventLocation(**body.location.model_dump()) if body.location else None,
    ))
    return EventResponse.from_domain(event, prefix)


@router.get("", response_model=list[EventResponse], dependencies=[Depends(require_roles(*RESPONDER_ROLES))])
async def list_events(
    camera_id: Annotated[str | None, Query(pattern=SAFE_ID_PATTERN)] = None,
    status: EventStatus | None = None,
    started_after: datetime | None = None,
    started_before: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    service: EventService = Depends(get_event_service),
    prefix: str = Depends(get_api_prefix),
):
    events = service.list(EventFilter(camera_id, status, started_after, started_before, limit, offset))
    return [EventResponse.from_domain(e, prefix) for e in events]


@router.get("/{event_id}", response_model=EventResponse, dependencies=[Depends(require_roles(*RESPONDER_ROLES))])
async def get_event(event_id: EventId, service: EventService = Depends(get_event_service),
                    prefix: str = Depends(get_api_prefix)):
    return EventResponse.from_domain(service.get(event_id), prefix)


@router.post("/{event_id}/ack", response_model=EventResponse)
async def acknowledge_event(event_id: EventId, body: AckRequest | None = None,
                            principal: Principal = Depends(require_roles(*RESPONDER_ROLES)),
                            service: EventService = Depends(get_event_service),
                            prefix: str = Depends(get_api_prefix)):
    event = await service.acknowledge(event_id, by=principal.subject, note=body.note if body else None)
    return EventResponse.from_domain(event, prefix)


@router.post("/{event_id}/escalate", response_model=EventResponse)
async def escalate_event(event_id: EventId, body: EscalateRequest | None = None,
                         principal: Principal = Depends(require_roles(*RESPONDER_ROLES)),
                         service: EventService = Depends(get_event_service),
                         prefix: str = Depends(get_api_prefix)):
    reason = body.reason if body else "manual escalation"
    event = await service.escalate(event_id, reason=f"{reason} (by {principal.subject})")
    return EventResponse.from_domain(event, prefix)


@router.post("/{event_id}/outcome", response_model=EventResponse)
async def record_outcome(event_id: EventId, body: OutcomeRequest,
                         _: Principal = Depends(require_roles(*RESPONDER_ROLES)),
                         service: EventService = Depends(get_event_service),
                         prefix: str = Depends(get_api_prefix)):
    """PROPOSED SCAFFOLD endpoint: closes the loop (resolved / false_alarm) for audit + training data."""
    event = await service.record_outcome(event_id, outcome=EventStatus(body.outcome), note=body.note)
    return EventResponse.from_domain(event, prefix)
