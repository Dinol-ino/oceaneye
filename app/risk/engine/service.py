from __future__ import annotations

import logging

from app.risk.engine.base import RiskAssessment, RiskEngine, RiskInput

logger = logging.getLogger(__name__)


class RiskService:
    """Application-level entry point. Depends only on the RiskEngine interface, so engines are swappable."""

    def __init__(self, engine: RiskEngine) -> None:
        self._engine = engine

    def assess(self, risk_input: RiskInput) -> RiskAssessment:
        assessment = self._engine.assess(risk_input)
        logger.debug("risk assessed", extra={"camera_id": assessment.camera_id,
                                             "track_id": assessment.track_id, "engine": assessment.engine})
        return assessment
