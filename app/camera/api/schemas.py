"""Camera API schemas (scaffold contracts). stream_url is accepted but NEVER returned."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.domain.geometry import is_normalized
from app.core.entities.camera import Camera
from app.core.enums import CameraSourceType, CameraStatus
from app.security.validation import SAFE_ID_PATTERN, validate_stream_url


class CameraCreate(BaseModel):
    """Either a network ``stream_url`` (RTSP/HTTP CCTV, phone camera) or ``video_upload_id`` (an uploaded
    clip replayed in a loop as a *simulated CCTV feed* for the prototype). Local file paths are never
    accepted from clients.

    ``beach_id`` defaults to the beach this installation is deployed at, which is what an operator
    adding a camera in the Control Room always means.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    stream_url: str | None = Field(default=None, min_length=1, max_length=2048)
    video_upload_id: str | None = Field(default=None, pattern=SAFE_ID_PATTERN)
    source_type: CameraSourceType = CameraSourceType.RTSP
    zone_polygon: list[tuple[float, float]] | None = Field(default=None, min_length=3, max_length=200)
    beach_id: str | None = Field(default=None, pattern=SAFE_ID_PATTERN)

    @field_validator("stream_url")
    @classmethod
    def _check_url(cls, v: str | None) -> str | None:
        return validate_stream_url(v) if v is not None else v

    @field_validator("zone_polygon")
    @classmethod
    def _normalised(cls, v):
        if v is not None and not is_normalized(v):
            raise ValueError("zone_polygon points must be normalised to 0..1")
        return v

    @model_validator(mode="after")
    def _one_source(self) -> "CameraCreate":
        if (self.stream_url is None) == (self.video_upload_id is None):
            raise ValueError("provide exactly one of stream_url or video_upload_id")
        if self.video_upload_id is not None:
            self.source_type = CameraSourceType.VIDEO_FILE
        elif self.source_type in (CameraSourceType.VIDEO_FILE, CameraSourceType.WEBCAM):
            raise ValueError("video_file/webcam sources are not accepted as URLs; upload the video instead")
        return self


class CameraResponse(BaseModel):
    id: str
    name: str
    lat: float
    lon: float
    source_type: CameraSourceType
    status: CameraStatus
    created_at: datetime
    beach_id: str | None = None

    @classmethod
    def from_domain(cls, c: Camera) -> "CameraResponse":
        return cls(
            id=c.id, name=c.name, lat=c.location.lat, lon=c.location.lon,
            source_type=c.source_type, status=c.status, created_at=c.created_at, beach_id=c.beach_id,
        )
