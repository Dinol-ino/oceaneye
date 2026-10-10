"""A notification that exercises the real delivery path without inventing an incident.

"Does the PC actually reach the phone?" is the question an operator needs answered before a shift,
and the only honest answer runs the same code a real alert runs. This builds a notification that
goes through every configured channel - WebSocket and Web Push - carrying a payload that is
unmistakably a test, so it can never be mistaken for a swimmer in trouble.

It deliberately does **not** create an Event. A test must not land in the incident log, the metrics
or the false-alarm rate.
"""
from __future__ import annotations

from datetime import datetime

from app.core.entities.alert import AlertNotification, AlertPayload
from app.core.entities.event import EventLocation
from app.core.enums import AlertNotificationType, EventStatus, RiskLevel

TEST_EVENT_ID = "test"
TEST_REASON = "TEST — connection check from the control room. Not an incident."


def build_test_notification(now: datetime, camera_label: str = "Connection test") -> AlertNotification:
    payload = AlertPayload(
        alert_id=TEST_EVENT_ID,
        event_id=TEST_EVENT_ID,
        camera_id=camera_label,
        track_id=TEST_EVENT_ID,
        risk_score=0.0,
        risk_level=RiskLevel.LOW,
        timestamp=now,
        location=EventLocation(0.0, 0.0, "Connection test"),
        distress_signals=(),
        reason=TEST_REASON,
        thumbnail_url=None,
        clip_url=None,
        ack_deadline=now,
        event_status=EventStatus.RESOLVED,   # nothing to acknowledge; phones must not alarm on it
        escalation_level=0,
    )
    return AlertNotification(AlertNotificationType.CREATED, payload, now)


def is_test_notification(payload: AlertPayload) -> bool:
    return payload.event_id == TEST_EVENT_ID
