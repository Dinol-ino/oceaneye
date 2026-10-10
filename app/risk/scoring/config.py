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
    min_samples: int = 6
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
    # repeated submersion: track disappears (gap > `gap_seconds`) or box shrinks below
    # `shrink_ratio` x median height, at least `submersion_min_count` times in the window
    gap_seconds: float = 0.4
    shrink_ratio: float = 0.6
    submersion_min_count: int = 2
    # scoring
    signal_weights: dict[str, float] = field(default_factory=lambda: {
        "repeated_submersion": 0.5, "vertical_bobbing": 0.4, "prolonged_stillness": 0.35, "erratic_movement": 0.3,
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
