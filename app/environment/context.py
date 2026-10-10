from __future__ import annotations

from dataclasses import dataclass

from app.environment.external_data.base import EnvironmentalConditions
from app.environment.water_motion.base import WaterMotionEstimate


@dataclass(frozen=True)
class EnvironmentContext:
    """Visual (water motion) and external (wind/tide/waves) context, kept as separate inputs."""

    water_motion: WaterMotionEstimate | None = None
    conditions: EnvironmentalConditions | None = None
