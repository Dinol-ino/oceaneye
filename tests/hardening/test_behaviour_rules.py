"""Behaviour layer: what the rules say about synthetic people at the frame rates the machine profiles
actually produce (2 fps CPU-small, 3-4 CPU, 6-8 GPU, 12-15 evaluate_detection.py default stride 2).

Green tests are guards. Tests marked ``defect`` assert desired behaviour and are red today.
"""
import pytest

from tests.hardening.synth import SCENARIOS, first_alert, horizontal_pose, rate, vertical_pose

FPS_ALL = (2, 3, 6, 12)


# ----------------------------------------------------------------------------- guards (green)
@pytest.mark.parametrize("fps", FPS_ALL)
@pytest.mark.parametrize("scenario", ["walker", "swimmer_crawl"])
def test_G1_travelling_people_never_alert(scenario, fps):
    share, _ = rate(scenario, fps)
    assert share == 0.0, f"{scenario} @ {fps} fps alerted in {share:.0%} of seeds"


@pytest.mark.parametrize("fps", FPS_ALL)
def test_G2_outside_zone_suppresses_even_real_distress(fps):
    share, _ = rate("thrash", fps, inside=False)
    assert share == 0.0


def test_G3_person_too_small_is_not_judged():
    """40 px gate: a 30 px swimmer yields no verdict at all (and therefore no alert, and no miss
    can be claimed either - see plan F7)."""
    assert first_alert("thrash", 3, 1, body_scale=0.25) is None


def test_G4_one_event_per_track_per_cooldown():
    """A 50 s thrash must raise one candidate event, not one per persistence window."""
    import random
    from datetime import timedelta

    from app.core.domain.value_objects import BoundingBox
    from app.environment.context import EnvironmentContext
    from app.environment.zones.models import ZoneAssessment
    from app.risk.distress.rules import RuleBasedBehaviorAnalyzer
    from app.risk.engine.base import RiskInput
    from app.risk.engine.rules import RuleBasedRiskEngine
    from app.risk.scoring.config import RiskScoringConfig
    from app.vision.detection.base import Detection
    from app.vision.tracking.base import Track
    from tests.hardening.synth import T0

    cfg = RiskScoringConfig.preset("high")
    an, eng = RuleBasedBehaviorAnalyzer(cfg), RuleBasedRiskEngine(cfg)
    rnd, hist, fired = random.Random(3), [], 0
    for i in range(50 * 3):
        t = i / 3
        ts = T0 + timedelta(seconds=t)
        cx, cy, h, w = SCENARIOS["thrash"][0](t, lambda s: rnd.gauss(0, s))
        hist.append(Detection("c", "person", .8, BoundingBox(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), ts))
        trk = Track("c-T1", "c", tuple(hist[-300:]))
        a = eng.assess(RiskInput("c", trk, ZoneAssessment("c", "c-T1", ts, True), an.analyze(trk, None, ts),
                                 EnvironmentContext(None), ts))
        fired += a.actionable
    assert fired <= 1


def test_G5_pose_separates_swimmer_from_upright_victim():
    """With pose, an upright motionless person alerts and a horizontal swimmer never does."""
    victim, _ = rate("quiet_drown", 6, pose=vertical_pose)
    swimmer, _ = rate("swimmer_crawl", 6, pose=horizontal_pose)
    assert victim >= 0.9 and swimmer == 0.0


# ----------------------------------------------------------------------------- defects (red)
@pytest.mark.defect
def test_D1_motionless_person_verdict_must_not_depend_on_frame_rate():
    """A person standing still must be equally (non-)alarming at 2 and 12 fps.

    Measured today (20 seeds): 0% at 2-3 fps, ~10% at 6 fps, 100% at 12 fps. Cause: erratic/bobbing
    are computed from frame-to-frame deltas, so box jitter becomes 'speed' that grows with fps.
    """
    shares = {fps: rate("standing", fps)[0] for fps in FPS_ALL}
    assert max(shares.values()) <= 0.10, f"false-alarm rate by fps: {shares}"


@pytest.mark.defect
def test_D2_quiet_drowning_must_alert_on_the_cpu_profile():
    """The 2-3 fps profile is what a laptop without a GPU gets (see profiles.choose_profile).

    Measured today: 0% of seeds alert at 2 fps and at 3 fps, in 45 s of vertical, almost motionless
    box. Stillness alone is capped at 0.35 x confidence < alert_threshold 0.5, so without pose the
    quiet drowner can never reach the threshold on its own.
    """
    shares = {fps: rate("quiet_drown", fps)[0] for fps in (2, 3)}
    assert min(shares.values()) >= 0.8, f"detection rate by fps: {shares}"


@pytest.mark.defect
def test_D3_thrashing_must_alert_at_every_frame_rate():
    """Measured today: 100% at 2-3 fps, ~3% at 6 fps, 0% at 12 fps (smooth flailing never makes
    enough >70 degree turns at higher fps, and the signals flicker so persistence never holds)."""
    shares = {fps: rate("thrash", fps)[0] for fps in FPS_ALL}
    assert min(shares.values()) >= 0.8, f"detection rate by fps: {shares}"


@pytest.mark.defect
def test_D4_slow_sink_alerts_within_30s_at_cpu_fps():
    share, med = rate("slow_sink", 2)
    assert share >= 0.8 and (med or 99) <= 30, f"rate={share:.0%}, median={med}s"


@pytest.mark.defect
def test_D5_time_to_alert_budget():
    """Product target (yours to set): <= 15 s from onset for a victim the system can see.
    Measured: median 12 s only at 6 fps; slower or never elsewhere."""
    for fps in (3, 6):
        share, med = rate("quiet_drown", fps)
        assert share >= 0.8 and med is not None and med <= 15, f"{fps} fps: rate={share:.0%} median={med}"
