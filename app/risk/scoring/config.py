"""Rule-based risk parameters.

EXPERIMENTAL PARAMETERS - every number here is a prototype starting point chosen to make the
behaviour visible on test footage. None is a validated OceanEye threshold; tune them with labelled
footage and the event outcomes (acknowledged / false_alarm) logged by the dashboard.
Motion is measured in "body heights" (bbox height) so it is independent of camera distance.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class RiskScoringConfig:
    # behaviour analysis window
    window_seconds: float = 4.0
    #: Minimum observations in a window. This is deliberately LOW and paired with
    #: ``min_sample_rate_hz`` below: as a bare count it silently meant 0.2 s of evidence at 30 fps
    #: and 2 s at 3 fps, so the same footage produced different verdicts on a faster machine.
    min_samples: int = 4
    #: ...and the window must actually be sampled this densely. Below this the trajectory is too
    #: sparse to distinguish bobbing from frame drops, and no signal is raised at all.
    min_sample_rate_hz: float = 2.0

    # -- gates: conditions under which this analyzer declines to judge ------------------------
    #: A track must have existed this long before its behaviour is assessed. Short-lived tracks
    #: are overwhelmingly fragments - a re-identified person, a wave crest, a momentary
    #: double-detection - and judging them produced alerts about people who were never there.
    #: MEASURED: at the previous tracker settings mean track life was 1.6 s, so virtually every
    #: assessment was being made on a fragment.
    min_track_seconds: float = 2.5
    #: A person smaller than this (bbox height in pixels) carries no usable signal: sub-pixel
    #: centre jitter swamps real motion, and pose keypoints are meaningless. On a 480x360 beach
    #: webcam a swimmer at the surf line is ~8 px, which is below ANY honest detection claim -
    #: the system reports that it cannot see, rather than inventing a verdict.
    min_body_pixels: float = 40.0
    # prolonged stillness: centre moves less than `still_motion` body-heights for `still_seconds`
    still_seconds: float = 6.0
    still_motion: float = 0.25
    # vertical bobbing: >= `bob_min_reversals` up/down reversals of size >= `bob_amplitude` while
    # drifting less than `bob_max_drift` body-heights sideways
    bob_amplitude: float = 0.05
    bob_min_reversals: int = 4
    bob_max_drift: float = 0.8
    # erratic movement: share of sharp (> `erratic_turn_deg`) direction changes while moving
    erratic_turn_deg: float = 70.0
    erratic_min_speed: float = 0.3  # body-heights / s
    erratic_min_share: float = 0.45
    # repeated submersion: box shrinks below `shrink_ratio` x median height at least
    # `submersion_min_count` times in the window.
    #
    # A track *disappearing* is deliberately NOT counted. On a busy beach the commonest reason a
    # person vanishes for a few frames is that someone walked in front of them, and occlusion is
    # indistinguishable from going under if all you watch is whether the box still exists. Counting
    # it made the highest-weighted signal fire on ordinary crowding. `gap_seconds` is kept only to
    # mark a history gap as "do not trust the measurements across this discontinuity".
    gap_seconds: float = 0.4
    shrink_ratio: float = 0.6
    submersion_min_count: int = 2

    # -- pose signals (require a PoseEstimator; absent pose means the signal is simply not raised)
    #: Torso axis within this many degrees of vertical counts as upright in the water.
    vertical_max_tilt_deg: float = 35.0
    #: ...while drifting less than this many body-heights, so a treading swimmer going somewhere
    #: on purpose is not flagged.
    vertical_max_drift: float = 0.6
    #: Seconds the upright-and-static posture must hold.
    vertical_seconds: float = 3.0
    #: A wrist this many head-heights above the shoulder line counts as raised.
    arms_raised_margin: float = 0.15
    # scoring
    #: Pose signals carry the most weight because they are the only ones that distinguish a
    #: swimmer from a person in difficulty: box-trajectory signals describe a shape moving in
    #: water, which both look like. They are still only evidence, and a pose model that returns
    #: nothing (distance, glare, waterline) silently removes them - which is why the trajectory
    #: signals stay in the mix rather than being replaced.
    signal_weights: dict[str, float] = field(default_factory=lambda: {
        "vertical_in_water": 0.55, "repeated_submersion": 0.5, "arms_raised": 0.45,
        "vertical_bobbing": 0.4, "prolonged_stillness": 0.35, "erratic_movement": 0.3,
    })
    outside_zone_factor: float = 0.3  # evidence outside the danger zone counts much less
    rough_sea_wave_m: float = 1.5  # environmental context raises the score a little
    strong_wind_ms: float = 10.0
    environment_boost: float = 1.15
    alert_threshold: float = 0.5
    persistence_seconds: float = 3.0  # score must stay above threshold this long (suppresses blips)
    cooldown_seconds: float = 60.0  # at most one event per track per cooldown
    max_events_per_minute: int = 3  # per camera, protects responders from alert floods
    level_boundaries: tuple[float, float, float] = (0.3, 0.55, 0.75)  # medium / high / critical

    @classmethod
    def preset(cls, sensitivity: str = "medium") -> "RiskScoringConfig":
        base = cls()
        if sensitivity == "high":  # more alerts, more false alarms (good for demos)
            return replace(base, alert_threshold=0.35, persistence_seconds=2.0, still_seconds=4.0)
        if sensitivity == "low":
            return replace(base, alert_threshold=0.65, persistence_seconds=5.0, still_seconds=8.0)
        return base
