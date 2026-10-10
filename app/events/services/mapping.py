from __future__ import annotations

from app.events.domain.commands import NewEventCommand
from app.risk.engine.base import RiskAssessment


def command_from_assessment(a: RiskAssessment) -> NewEventCommand:
    """Risk engine output -> candidate event command (used by the worker's in-process sink)."""
    return NewEventCommand(
        camera_id=a.camera_id, track_id=a.track_id, risk_score=a.risk_score, risk_level=a.risk_level,
        started_at=a.timestamp, distress_signals=a.contributing_signals, reason=a.reason,
    )
