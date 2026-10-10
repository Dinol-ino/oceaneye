from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.core.enums import ZoneMode


@dataclass(frozen=True)
class ZoneAssessment:
    """Zone gate result for one track. ``inside_zone=None`` means 'not evaluated'."""

    camera_id: str
    track_id: str
    evaluated_at: datetime
    inside_zone: bool | None
    zone_mode: ZoneMode | None = None
    breach_since: datetime | None = None
