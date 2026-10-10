from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.core.domain.value_objects import GeoPoint
from app.core.enums import CameraSourceType, CameraStatus


@dataclass
class Camera:
    """Camera model (reference section 7). Zone polygon lives in :class:`Zone`.

    ``beach_id`` ties the camera to the deployment site it belongs to (see
    :class:`app.core.entities.beach.Beach`). It is optional so that cameras created before beaches
    existed - and quick throwaway test cameras - remain valid.
    """

    id: str
    name: str
    location: GeoPoint
    stream_url: str  # SENSITIVE: never serialised to API clients
    source_type: CameraSourceType
    status: CameraStatus
    created_at: datetime
    beach_id: str | None = None
