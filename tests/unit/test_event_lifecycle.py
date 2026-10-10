from datetime import datetime, timezone

import pytest

from app.core.entities.event import Event, EventLocation
from app.core.enums import EventStatus
from app.core.exceptions import DomainValidationError, InvalidStateTransition

T = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make(status=EventStatus.PENDING) -> Event:
    return Event("evt_1", "cam_1", "t1", T, 0.5, status, EventLocation(0, 0), T, T)


def test_happy_path():
    e = make(); e.acknowledge("a", T); e.close(EventStatus.RESOLVED, T)
    assert e.status is EventStatus.RESOLVED and e.closed_at == T


def test_terminal_states_are_final():
    e = make(); e.close(EventStatus.FALSE_ALARM, T)
    for action in (lambda: e.acknowledge("a", T), lambda: e.escalate(T, "r")):
        with pytest.raises(InvalidStateTransition):
            action()


def test_escalated_can_be_acknowledged_but_not_re_escalated():
    e = make(); e.escalate(T, "timeout"); e.acknowledge("senior", T)
    assert e.status is EventStatus.ACKNOWLEDGED and e.escalation_level == 1


def test_close_requires_terminal_outcome():
    with pytest.raises(DomainValidationError):
        make().close(EventStatus.ESCALATED, T)


def test_risk_score_range():
    with pytest.raises(DomainValidationError):
        Event("e", "c", "t", T, 1.2, EventStatus.PENDING, EventLocation(0, 0), T, T)
