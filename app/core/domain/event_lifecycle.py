"""Event state machine. PROPOSED SCAFFOLD: the reference lists the statuses but not the
transitions; these are the minimal ones needed by the documented workflow."""
from __future__ import annotations

from app.core.enums import EventStatus

TERMINAL_STATUSES = frozenset({EventStatus.RESOLVED, EventStatus.FALSE_ALARM})

ALLOWED_TRANSITIONS: dict[EventStatus, frozenset[EventStatus]] = {
    EventStatus.PENDING: frozenset(
        {EventStatus.ACKNOWLEDGED, EventStatus.ESCALATED, EventStatus.RESOLVED, EventStatus.FALSE_ALARM}
    ),
    EventStatus.ACKNOWLEDGED: frozenset(
        {EventStatus.ESCALATED, EventStatus.RESOLVED, EventStatus.FALSE_ALARM}
    ),
    # a responder may take over after escalation
    EventStatus.ESCALATED: frozenset(
        {EventStatus.ACKNOWLEDGED, EventStatus.RESOLVED, EventStatus.FALSE_ALARM}
    ),
    EventStatus.RESOLVED: frozenset(),
    EventStatus.FALSE_ALARM: frozenset(),
}


def can_transition(current: EventStatus, target: EventStatus) -> bool:
    return target in ALLOWED_TRANSITIONS[current]
