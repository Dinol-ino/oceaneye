from __future__ import annotations

from app.risk.engine.base import RiskAssessment, RiskEngine, RiskInput


class MockRiskEngine(RiskEngine):
    """MOCK: computes nothing and is never actionable. score 0.0 means 'not computed'."""

    name = "mock"

    def assess(self, risk_input: RiskInput) -> RiskAssessment:
        return RiskAssessment(
            camera_id=risk_input.camera_id, track_id=risk_input.track.track_id,
            timestamp=risk_input.now, risk_score=0.0, risk_level=None,
            contributing_signals=(), reason="MOCK engine: no risk computed",
            actionable=False, engine=self.name,
        )
