"""Interpretable rule-based risk engine (roadmap Stages 8-9).

score = (sum of weighted signal confidences) x zone factor x environment boost, clipped to [0, 1].
An assessment becomes *actionable* (-> candidate event) only when the score stays above the threshold
for ``persistence_seconds`` inside the danger zone (or with no zone configured), respecting a per-track
cooldown and a per-camera rate limit. Stateful per track; one engine instance per camera stream.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime

from app.core.enums import RiskLevel
from app.risk.engine.base import RiskAssessment, RiskEngine, RiskInput
from app.risk.scoring.config import RiskScoringConfig


class RuleBasedRiskEngine(RiskEngine):
    name = "rules-v1"

    def __init__(self, config: RiskScoringConfig | None = None) -> None:
        self.cfg = config or RiskScoringConfig()
        self._elevated_since: dict[str, datetime] = {}
        self._last_event: dict[str, datetime] = {}
        self._recent_events: deque[datetime] = deque()

    def level(self, score: float) -> RiskLevel:
        m, h, c = self.cfg.level_boundaries
        return (RiskLevel.CRITICAL if score >= c else RiskLevel.HIGH if score >= h
                else RiskLevel.MEDIUM if score >= m else RiskLevel.LOW)

    def assess(self, risk_input: RiskInput) -> RiskAssessment:
        cfg, now, tid = self.cfg, risk_input.now, risk_input.track.track_id
        signals = risk_input.behavior.signals
        base = sum(cfg.signal_weights.get(s.type.value, 0.0) * (s.confidence or 0.5) for s in signals)
        reasons = [f"{s.type.value} ({s.confidence:.2f}: {s.detail})" for s in signals]

        inside = risk_input.zone.inside_zone
        if inside is False:
            base *= cfg.outside_zone_factor
            reasons.append("outside danger zone")
        elif inside is True:
            reasons.insert(0, "inside danger zone")
        else:
            reasons.insert(0, "no zone configured (whole frame)")

        cond = risk_input.environment.conditions
        if cond and ((cond.wave_height_m or 0) >= cfg.rough_sea_wave_m or (cond.wind_speed_ms or 0) >= cfg.strong_wind_ms):
            base *= cfg.environment_boost
            reasons.append(f"rough conditions (waves {cond.wave_height_m} m, wind {cond.wind_speed_ms} m/s)")

        score = round(min(1.0, base), 3)
        actionable = False
        if score >= cfg.alert_threshold and inside is not False:
            since = self._elevated_since.setdefault(tid, now)
            held = (now - since).total_seconds()
            reasons.append(f"elevated for {held:.1f}s")
            if held >= cfg.persistence_seconds and self._allowed(tid, now):
                actionable = True
                self._last_event[tid] = now
                self._recent_events.append(now)
        else:
            self._elevated_since.pop(tid, None)

        return RiskAssessment(
            camera_id=risk_input.camera_id, track_id=tid, timestamp=now, risk_score=score,
            risk_level=self.level(score), contributing_signals=tuple(s.type for s in signals),
            reason="; ".join(reasons) or "no distress signals", actionable=actionable, engine=self.name,
        )

    def _allowed(self, track_id: str, now: datetime) -> bool:
        last = self._last_event.get(track_id)
        if last and (now - last).total_seconds() < self.cfg.cooldown_seconds:
            return False
        while self._recent_events and (now - self._recent_events[0]).total_seconds() > 60:
            self._recent_events.popleft()
        return len(self._recent_events) < self.cfg.max_events_per_minute
