"""Interpretable distress heuristics over a track's recent history (roadmap Stage 7).

These are *heuristics*, not a drowning classifier: each signal is weak evidence that can also fit
normal behaviour (someone floating still, playing in waves). The risk engine combines them with the
zone gate, persistence and environment before anything becomes a candidate event.
Not implemented: ``arms_raised`` (needs a pose model - future PoseEstimator).
"""
from __future__ import annotations

import math
from datetime import datetime
from statistics import median

from app.core.enums import DistressSignalType
from app.risk.distress.base import BehaviorAnalyzer, BehaviorAssessment, DistressSignal
from app.risk.scoring.config import RiskScoringConfig
from app.vision.pose.base import PoseEstimate
from app.vision.tracking.base import Track


class RuleBasedBehaviorAnalyzer(BehaviorAnalyzer):
    def __init__(self, config: RiskScoringConfig | None = None) -> None:
        self.cfg = config or RiskScoringConfig()

    def analyze(self, track: Track, pose: PoseEstimate | None, now: datetime) -> BehaviorAssessment:
        cfg = self.cfg
        hist = [d for d in track.history if (now - d.timestamp).total_seconds() <= max(cfg.window_seconds, cfg.still_seconds)]
        if len(hist) < cfg.min_samples:
            return BehaviorAssessment(track.camera_id, track.track_id, now)
        body = median(d.bbox.y_max - d.bbox.y_min for d in hist) or 1.0
        window = [d for d in hist if (now - d.timestamp).total_seconds() <= cfg.window_seconds]
        observed = (hist[-1].timestamp - hist[0].timestamp).total_seconds()
        signals: list[DistressSignal] = []
        for fn in (self._stillness, self._bobbing, self._erratic, self._submersion):
            sig = fn(hist, window, body, now)
            if sig:
                signals.append(sig)
        return BehaviorAssessment(track.camera_id, track.track_id, now, tuple(signals), observed)

    # -- individual signals ----------------------------------------------
    def _stillness(self, hist, window, body, now):
        cfg = self.cfg
        span = (hist[-1].timestamp - hist[0].timestamp).total_seconds()
        if span < cfg.still_seconds * 0.9:
            return None
        xs = [d.bbox.center[0] for d in hist]
        ys = [d.bbox.center[1] for d in hist]
        spread = math.hypot(max(xs) - min(xs), max(ys) - min(ys)) / body
        if spread >= cfg.still_motion:
            return None
        conf = min(1.0, 0.5 + 0.5 * (1 - spread / cfg.still_motion))
        return DistressSignal(DistressSignalType.PROLONGED_STILLNESS, now, round(conf, 2),
                              f"moved {spread:.2f} body-heights in {span:.1f}s")

    def _bobbing(self, hist, window, body, now):
        cfg = self.cfg
        if len(window) < cfg.min_samples:
            return None
        ys = [d.bbox.center[1] / body for d in window]
        drift = abs(window[-1].bbox.center[0] - window[0].bbox.center[0]) / body
        if drift > cfg.bob_max_drift:
            return None
        reversals, direction, anchor = 0, 0, ys[0]
        for y in ys[1:]:
            delta = y - anchor
            if abs(delta) >= cfg.bob_amplitude:
                d = 1 if delta > 0 else -1
                if direction and d != direction:
                    reversals += 1
                direction, anchor = d, y
        if reversals < cfg.bob_min_reversals:
            return None
        conf = min(1.0, reversals / (2 * cfg.bob_min_reversals) + 0.4)
        return DistressSignal(DistressSignalType.VERTICAL_BOBBING, now, round(conf, 2),
                              f"{reversals} up/down reversals, drift {drift:.2f}")

    def _erratic(self, hist, window, body, now):
        cfg = self.cfg
        if len(window) < cfg.min_samples:
            return None
        vel = []
        for a, b in zip(window, window[1:]):
            dt = (b.timestamp - a.timestamp).total_seconds() or 1e-6
            vx = (b.bbox.center[0] - a.bbox.center[0]) / body / dt
            vy = (b.bbox.center[1] - a.bbox.center[1]) / body / dt
            if math.hypot(vx, vy) >= cfg.erratic_min_speed:
                vel.append(math.atan2(vy, vx))
        if len(vel) < cfg.min_samples - 1:
            return None
        sharp = sum(1 for a, b in zip(vel, vel[1:])
                    if abs((math.degrees(b - a) + 180) % 360 - 180) > cfg.erratic_turn_deg)
        share = sharp / (len(vel) - 1)
        if share < cfg.erratic_min_share:
            return None
        return DistressSignal(DistressSignalType.ERRATIC_MOVEMENT, now, round(min(1.0, share + 0.3), 2),
                              f"{share:.0%} sharp direction changes")

    def _submersion(self, hist, window, body, now):
        cfg = self.cfg
        gaps = sum(1 for a, b in zip(window, window[1:]) if (b.timestamp - a.timestamp).total_seconds() > cfg.gap_seconds)
        shrink, small = 0, False
        for d in window:
            is_small = (d.bbox.y_max - d.bbox.y_min) < cfg.shrink_ratio * body
            if is_small and not small:
                shrink += 1
            small = is_small
        count = gaps + shrink
        if count < cfg.submersion_min_count:
            return None
        return DistressSignal(DistressSignalType.REPEATED_SUBMERSION, now,
                              round(min(1.0, 0.4 + 0.2 * count), 2), f"{gaps} disappearances, {shrink} shrinks")
