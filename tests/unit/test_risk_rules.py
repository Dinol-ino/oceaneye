import math
from datetime import datetime, timedelta, timezone

from app.core.domain.geometry import is_normalized, point_in_polygon
from app.core.domain.value_objects import BoundingBox, Polygon
from app.core.entities.zone import Zone
from app.core.enums import DistressSignalType as S, RiskLevel, ZoneMode
from app.environment.context import EnvironmentContext
from app.environment.external_data.base import EnvironmentalConditions
from app.environment.zones.models import ZoneAssessment
from app.environment.zones.service import PolygonZoneGate
from app.risk.distress.base import BehaviorAssessment, DistressSignal
from app.risk.distress.rules import RuleBasedBehaviorAnalyzer
from app.risk.engine.base import RiskInput
from app.risk.engine.rules import RuleBasedRiskEngine
from app.risk.scoring.config import RiskScoringConfig
from app.vision.detection.base import Detection
from app.vision.tracking.base import Track

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
SQUARE = ((0, 0), (1, 0), (1, 1), (0, 1))


def track(points, h=100.0, dt=0.2, sizes=None, times=None):
    dets = []
    for i, (x, y) in enumerate(points):
        hh = sizes[i] if sizes else h
        t = times[i] if times else T0 + timedelta(seconds=i * dt)
        dets.append(Detection("cam", "person", 0.8, BoundingBox(x - 20, y - hh / 2, x + 20, y + hh / 2), t))
    return Track("cam-T1", "cam", tuple(dets))


def signals(tr):
    a = RuleBasedBehaviorAnalyzer().analyze(tr, None, tr.last_seen)
    return {s.type for s in a.signals}


def test_geometry():
    assert point_in_polygon(0.5, 0.5, SQUARE) and not point_in_polygon(1.5, 0.5, SQUARE)
    assert point_in_polygon(0.2, 0.8, [(0, 0.5), (1, 0.5), (1, 1), (0, 1)])
    assert is_normalized(SQUARE) and not is_normalized([(0, 0), (10, 0), (5, 5)])


def test_polygon_gate_inside_outside_and_dwell():
    zone = Zone("z", "cam", "water", Polygon(((0, 0.5), (1, 0.5), (1, 1), (0, 1))), ZoneMode.STATIC, T0)
    gate = PolygonZoneGate()
    inside = track([(100, 400)])  # bottom y = 450 of 500 -> 0.9
    a1 = gate.evaluate(inside, zone, T0, (1000, 500))
    a2 = gate.evaluate(inside, zone, T0 + timedelta(seconds=5), (1000, 500))
    assert a1.inside_zone and a2.breach_since == T0
    assert gate.evaluate(track([(100, 60)]), zone, T0, (1000, 500)).inside_zone is False
    assert gate.evaluate(inside, None, T0, (1000, 500)).inside_zone is None


def test_stillness_detected_only_after_enough_time():
    assert S.PROLONGED_STILLNESS in signals(track([(500, 300)] * 35))       # 6.8 s still
    assert S.PROLONGED_STILLNESS not in signals(track([(500, 300)] * 10))   # 1.8 s: too short
    assert not signals(track([(500 + 30 * i, 300) for i in range(35)]))     # swimming steadily


def test_bobbing_erratic_and_submersion():
    bob = [(500, 300 + (12 if i % 2 else -12)) for i in range(20)]
    assert S.VERTICAL_BOBBING in signals(track(bob))
    zig = [(500 + (60 if i % 2 else 0), 300 + 40 * (i % 3)) for i in range(20)]
    assert S.ERRATIC_MOVEMENT in signals(track(zig))
    sizes = [100] * 6 + [100, 100, 40, 100, 100, 40, 100, 100, 100, 100]
    assert S.REPEATED_SUBMERSION in signals(track([(500, 300)] * len(sizes), sizes=sizes))


def _input(engine_now, inside=True, conf=1.0, sig=S.REPEATED_SUBMERSION, waves=None, tid="cam-T1"):
    tr = Track(tid, "cam", (Detection("cam", "person", 0.9, BoundingBox(0, 0, 10, 10), engine_now),))
    beh = BehaviorAssessment("cam", tid, engine_now, (DistressSignal(sig, engine_now, conf, "test"),))
    env = EnvironmentContext(conditions=EnvironmentalConditions(0, 0, engine_now, "test", wave_height_m=waves) if waves else None)
    return RiskInput("cam", tr, ZoneAssessment("cam", tid, engine_now, inside), beh, env, engine_now)


def test_engine_requires_persistence_then_fires_once_with_cooldown():
    e = RuleBasedRiskEngine(RiskScoringConfig(persistence_seconds=3, cooldown_seconds=60))
    fired = [e.assess(_input(T0 + timedelta(seconds=s))).actionable for s in (0, 1, 2, 3, 4, 10)]
    assert fired == [False, False, False, True, False, False]
    assert e.assess(_input(T0 + timedelta(seconds=70))).actionable  # after cooldown


def test_engine_outside_zone_never_fires_and_scores_lower():
    e = RuleBasedRiskEngine(RiskScoringConfig(persistence_seconds=0))
    a = e.assess(_input(T0, inside=False))
    assert not a.actionable and a.risk_score == 0.15 and "outside danger zone" in a.reason


def test_engine_environment_boost_levels_and_rate_limit():
    e = RuleBasedRiskEngine(RiskScoringConfig(persistence_seconds=0, max_events_per_minute=2))
    calm = e.assess(_input(T0, waves=0.5, tid="a")).risk_score
    rough = e.assess(_input(T0, waves=2.0, tid="b")).risk_score
    assert math.isclose(rough, round(calm * 1.15, 3)) and "rough conditions" in e.assess(_input(T0, waves=2.0, tid="c")).reason
    assert sum(e.assess(_input(T0, tid=f"x{i}")).actionable for i in range(5)) == 0  # 2/min already used by a, b
    assert e.level(0.1) is RiskLevel.LOW and e.level(0.6) is RiskLevel.HIGH and e.level(0.9) is RiskLevel.CRITICAL


def test_presets_change_thresholds():
    assert RiskScoringConfig.preset("high").alert_threshold < RiskScoringConfig.preset("low").alert_threshold


# ---- pose-driven signals ----------------------------------------------------------------------
# These are the only signals that can separate a swimmer from someone in difficulty: a bounding box
# drifting in water looks the same either way. They run entirely on keypoint geometry, so they are
# testable with no model, no GPU and no footage.

from app.vision.pose.base import PoseEstimate, PoseKeypoint  # noqa: E402


def pose_at(*, shoulder_y, hip_y, shoulder_x=100.0, hip_x=100.0, wrist_y=None, nose_y=None,
            t=T0, track_id="cam-T1"):
    """A COCO-17 pose with only the keypoints a signal needs; the rest are absent, which is
    exactly what a real pose model returns for a half-submerged person."""
    kp = [
        PoseKeypoint("left_shoulder", shoulder_x - 10, shoulder_y, 0.9),
        PoseKeypoint("right_shoulder", shoulder_x + 10, shoulder_y, 0.9),
        PoseKeypoint("left_hip", hip_x - 8, hip_y, 0.8),
        PoseKeypoint("right_hip", hip_x + 8, hip_y, 0.8),
    ]
    if nose_y is not None:
        kp.append(PoseKeypoint("nose", shoulder_x, nose_y, 0.9))
    if wrist_y is not None:
        kp.append(PoseKeypoint("left_wrist", shoulder_x - 15, wrist_y, 0.8))
    return PoseEstimate(track_id, t, tuple(kp))


def pose_signals(tr, pose):
    a = RuleBasedBehaviorAnalyzer().analyze(tr, pose, tr.last_seen)
    return {s.type for s in a.signals}


def still_track(n=40):
    """Long enough to satisfy the vertical signal's observation window, barely moving."""
    return track([(100 + (i % 2), 200) for i in range(n)])


def test_vertical_torso_while_going_nowhere_is_flagged():
    """Upright in the water with no headway: the posture half of the instinctive drowning
    response. Shoulders above hips in image coordinates means a vertical body."""
    tr = still_track()
    assert S.VERTICAL_IN_WATER in pose_signals(tr, pose_at(shoulder_y=180, hip_y=240, t=tr.last_seen))


def test_a_horizontal_swimmer_is_not_flagged():
    """Front crawl, breaststroke, floating: the torso lies across the image. This is the case the
    whole signal exists to exclude, so it matters more than the positive."""
    tr = still_track()
    pose = PoseEstimate("cam-T1", tr.last_seen, (
        PoseKeypoint("left_shoulder", 100, 200, 0.9), PoseKeypoint("right_shoulder", 110, 200, 0.9),
        PoseKeypoint("left_hip", 170, 203, 0.8), PoseKeypoint("right_hip", 170, 207, 0.8),
    ))
    assert S.VERTICAL_IN_WATER not in pose_signals(tr, pose)


def test_vertical_but_travelling_is_not_flagged():
    """Someone wading ashore is upright and perfectly fine. Without the drift test this signal
    would fire on every person standing in the shallows."""
    tr = track([(100 + i * 12, 200) for i in range(40)])
    assert S.VERTICAL_IN_WATER not in pose_signals(tr, pose_at(shoulder_y=180, hip_y=240, t=tr.last_seen))


def test_missing_torso_keypoints_raise_nothing():
    """A pose the model could not resolve means UNKNOWN, never safe and never dangerous."""
    tr = still_track()
    empty = PoseEstimate("cam-T1", tr.last_seen, ())
    assert pose_signals(tr, empty) == signals(tr)


def test_a_wrist_above_the_shoulders_raises_arms_raised():
    tr = still_track()
    pose = pose_at(shoulder_y=200, hip_y=260, nose_y=170, wrist_y=150, t=tr.last_seen)
    assert S.ARMS_RAISED in pose_signals(tr, pose)


def test_arms_down_do_not_raise_it():
    tr = still_track()
    pose = pose_at(shoulder_y=200, hip_y=260, nose_y=170, wrist_y=250, t=tr.last_seen)
    assert S.ARMS_RAISED not in pose_signals(tr, pose)


def test_occlusion_alone_is_not_counted_as_submersion():
    """Regression. A track vanishing for a few frames used to count as going under, so the
    highest-weighted signal fired whenever one beachgoer walked in front of another. Only the box
    collapsing while the track survives counts now."""
    times = [T0 + timedelta(seconds=s) for s in (0.0, 0.2, 0.4, 1.4, 1.6, 1.8, 2.8, 3.0, 3.2)]
    gappy = track([(100, 200)] * len(times), times=times)
    assert S.REPEATED_SUBMERSION not in signals(gappy)


def test_a_body_repeatedly_sinking_is_still_counted():
    """The real thing must survive the occlusion fix: the box collapses and recovers, with the
    track held continuously throughout."""
    sizes = [100] * 6 + [100, 100, 40, 100, 100, 40, 100, 100, 40, 100]
    sinking = track([(100, 200)] * len(sizes), sizes=sizes, dt=0.2)
    assert S.REPEATED_SUBMERSION in signals(sinking)
