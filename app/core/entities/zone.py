from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.core.domain.value_objects import Polygon
from app.core.enums import ZoneMode


@dataclass
class Zone:
    """Danger zone of a camera. STATIC polygon first; DYNAMIC is a future mode."""

    id: str
    camera_id: str
    name: str
    polygon: Polygon
    mode: ZoneMode
    updated_at: datetime
