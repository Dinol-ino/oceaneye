from datetime import datetime, timezone

import pytest

from app.core.domain.value_objects import BoundingBox
from app.core.enums import RiskLevel
from app.core.exceptions import DomainValidationError
from app.environment.context import EnvironmentContext
from app.environment.zones.service import MockZoneGate
from app.risk.distress.mock import MockBehaviorAnalyzer
from app.risk.engine.base import RiskAssessment, RiskEngine, RiskInput
from app.risk.engine.mock import MockRiskEngine
from app.risk.engine.service import RiskService
from app.vision.detection.base import Detection
from app.vision.tracking.base import Track

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _input() -> RiskInput:
    det = Detection("cam_1", "person", 0.9, BoundingBox(0, 0, 2, 2), NOW)
    track = Track("C1-T1", "cam_1", (det,))
    return RiskInput("cam_1", track, MockZoneGate().evaluate(track, None, NOW),
                     MockBehaviorAnalyzer().analyze(track, None, NOW), EnvironmentContext(), NOW)


def test_mock_engine_satisfies_contract_and_is_never_actionable():
    a = RiskService(MockRiskEngine()).assess(_input())
    assert a.engine == "mock" and a.actionable is False and a.risk_score == 0.0 and "MOCK" in a.reason
    assert a.track_id == "C1-T1" and a.camera_id == "cam_1"


def test_engine_is_swappable_behind_the_interface():
    class Fixed(RiskEngine):
        name = "fixed"

        def assess(self, i):
            return RiskAssessment(i.camera_id, i.track.track_id, i.now, 0.9, RiskLevel.HIGH, (), "test", True, self.name)

    assert RiskService(Fixed()).assess(_input()).actionable is True


def test_assessment_validates_score():
    with pytest.raises(DomainValidationError):
        RiskAssessment("c", "t", NOW, 2.0, None, (), "x", False, "x")
