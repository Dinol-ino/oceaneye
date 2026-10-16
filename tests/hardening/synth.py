"""Synthetic tracks fed through the REAL RuleBasedBehaviorAnalyzer + RuleBasedRiskEngine.

No model, no video, no GPU: this isolates the behaviour layer from the detector so a failure here is
a rules/threshold problem, not a "YOLO missed the swimmer" problem. Box jitter (gaussian, in pixels)
stands in for detector noise - 1.5 px on a 120 px person is ~1%, which is mild for YOLO on 480p CCTV.
All motion is seeded, so results are reproducible.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

from app.core.domain.value_objects import BoundingBox
from app.environment.context import EnvironmentContext
from app.environment.zones.models import ZoneAssessment
from app.risk.distress.rules import RuleBasedBehaviorAnalyzer
from app.risk.engine.base import RiskInput
from app.risk.engine.rules import RuleBasedRiskEngine
from app.risk.scoring.config import RiskScoringConfig
from app.vision.detection.base import Detection
from app.vision.pose.base import PoseEstimate, PoseKeypoint
from app.vision.tracking.base import Track

T0 = datetime(2026, 10, 15, 6, 0, 0, tzinfo=timezone.utc)
H, W = 120, 50  # a person ~120 px tall: comfortably above the 40 px "can see" gate

# scenario -> (generator(t, jitter) -> (cx, cy, h, w), should_alert)
SCENARIOS = {
    "standing":      (lambda t, J: (400 + J(1.5), 300 + J(1.5), H + J(2), W + J(1)), False),
    "sunbather":     (lambda t, J: (400 + J(.5), 300 + J(.5), 50 + J(1), 140 + J(1)), False),
    "walker":        (lambda t, J: (100 + 40 * t + J(1.5), 300 + J(1.5), H + J(2), W + J(1)), False),
    "swimmer_crawl": (lambda t, J: (100 + 25 * t + J(2), 300 + 6 * math.sin(t * 3) + J(2), 40 + J(2), 110 + J(2)), False),
    "wave_play":     (lambda t, J: (400 + 8 * math.sin(t * 2.1) + J(2), 300 + 12 * math.sin(t * 3.3) + J(2),
                                    H * (1 - 0.3 * (math.sin(t * 3.3) > 0.7)) + J(2), W + J(1)), False),
    # vertical, almost motionless, head dipping now and then - the "instinctive drowning response"
    "quiet_drown":   (lambda t, J: (400 + J(2), 300 + 6 * math.sin(t * 2.5) + J(2),
                                    H * (1 - 0.35 * (math.sin(t * 1.7) > 0.8)) + J(2), W + J(1)), True),
    "thrash":        (lambda t, J: (400 + 25 * math.sin(t * 5) + J(3), 300 + 20 * math.cos(t * 7) + J(3), H + J(3), W + J(2)), True),
    "slow_sink":     (lambda t, J: (400 + J(2), 300 + (t * 4 if t < 30 else 120) + J(2),
                                    H * max(.35, 1 - t / 45) + J(2), W + J(1)), True),
}


def _kp(n, x, y):
    return PoseKeypoint(n, x, y, 0.8)


def vertical_pose(ts, cx, cy, h):
    return PoseEstimate("c-T1", ts, (
        _kp("nose", cx, cy - h * .45), _kp("left_eye", cx - 3, cy - h * .47),
        _kp("left_shoulder", cx - 10, cy - h * .3), _kp("right_shoulder", cx + 10, cy - h * .3),
        _kp("left_hip", cx - 8, cy + h * .1), _kp("right_hip", cx + 8, cy + h * .1)))


def horizontal_pose(ts, cx, cy, h):
    return PoseEstimate("c-T1", ts, (
        _kp("nose", cx - 40, cy), _kp("left_shoulder", cx - 25, cy - 5), _kp("right_shoulder", cx - 25, cy + 5),
        _kp("left_hip", cx + 10, cy - 5), _kp("right_hip", cx + 10, cy + 5)))


def first_alert(scenario: str, fps: float, seed: int, *, seconds: float = 45, sensitivity: str = "medium",
                pose=None, inside: bool | None = True, body_scale: float = 1.0) -> float | None:
    """Seconds into the clip at which the engine first says ``actionable``; None if it never does."""
    gen, _ = SCENARIOS[scenario]
    rnd = random.Random(seed)
    J = lambda s: rnd.gauss(0, s)  # noqa: E731
    cfg = RiskScoringConfig.preset(sensitivity)
    analyzer, engine = RuleBasedBehaviorAnalyzer(cfg), RuleBasedRiskEngine(cfg)
    hist: list[Detection] = []
    for i in range(int(seconds * fps)):
        t = i / fps
        ts = T0 + timedelta(seconds=t)
        cx, cy, h, w = gen(t, J)
        h, w = h * body_scale, w * body_scale
        hist.append(Detection("c", "person", 0.8, BoundingBox(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), ts))
        track = Track("c-T1", "c", tuple(hist[-300:]))
        p = pose(ts, cx, cy, h) if pose else None
        beh = analyzer.analyze(track, p, ts)
        a = engine.assess(RiskInput("c", track, ZoneAssessment("c", "c-T1", ts, inside_zone=inside),
                                    beh, EnvironmentContext(conditions=None), ts))
        if a.actionable:
            return t
    return None


def rate(scenario: str, fps: float, *, seeds: int = 20, **kw) -> tuple[float, float | None]:
    """(share of seeds that alerted, median seconds-to-alert among those that did)."""
    hits = [x for x in (first_alert(scenario, fps, s, **kw) for s in range(seeds)) if x is not None]
    med = sorted(hits)[len(hits) // 2] if hits else None
    return len(hits) / seeds, med
