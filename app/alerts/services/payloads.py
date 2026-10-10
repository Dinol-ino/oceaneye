from __future__ import annotations

from app.core.entities.alert import Alert, AlertPayload
from app.core.entities.event import Event


def build_payload(event: Event, alert: Alert, api_prefix: str) -> AlertPayload:
    base = f"{api_prefix}/evidence/{event.id}"
    ev = event.evidence
    return AlertPayload(
        alert_id=alert.id, event_id=event.id, camera_id=event.camera_id, track_id=event.track_id,
        risk_score=event.risk_score, risk_level=event.risk_level, timestamp=event.started_at,
        location=event.location, distress_signals=tuple(event.distress_signals), reason=event.reason,
        thumbnail_url=f"{base}/thumbnail" if ev and ev.thumbnail_key else None,
        clip_url=f"{base}/clip" if ev and ev.clip_key else None,
        ack_deadline=alert.ack_deadline, event_status=event.status,
        escalation_level=max(alert.escalation_level, event.escalation_level),
    )
