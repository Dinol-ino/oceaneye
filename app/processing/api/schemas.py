from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.entities.processing import AnalysisJob, UploadedVideo
from app.core.enums import JobStatus
from app.security.validation import SAFE_ID_PATTERN


class UploadResponse(BaseModel):
    id: str
    filename: str
    size_bytes: int
    created_at: datetime

    @classmethod
    def from_domain(cls, u: UploadedVideo) -> "UploadResponse":
        return cls(id=u.id, filename=u.filename, size_bytes=u.size_bytes, created_at=u.created_at)


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    upload_id: str = Field(pattern=SAFE_ID_PATTERN)
    camera_id: str = Field(pattern=SAFE_ID_PATTERN)
    model: str | None = Field(default=None, max_length=32)
    imgsz: int | None = None
    device: str | None = Field(default=None, max_length=16)
    sensitivity: Literal["low", "medium", "high"] | None = None


class JobResponse(BaseModel):
    id: str
    upload_id: str
    camera_id: str
    status: JobStatus
    progress: float
    options: dict
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    summary: dict
    events_created: int
    video_url: str | None

    @classmethod
    def from_domain(cls, j: AnalysisJob, prefix: str) -> "JobResponse":
        return cls(id=j.id, upload_id=j.upload_id, camera_id=j.camera_id, status=j.status, progress=j.progress,
                   options=j.options, created_at=j.created_at, started_at=j.started_at, finished_at=j.finished_at,
                   error=j.error, summary=j.summary, events_created=j.events_created,
                   video_url=f"{prefix}/analysis/jobs/{j.id}/video" if j.overlay_key else None)


class JobReport(BaseModel):
    """Sent by the worker process (role 'service')."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["running", "completed", "failed"]
    progress: float | None = Field(default=None, ge=0, le=1)
    summary: dict | None = None
    error: str | None = Field(default=None, max_length=4000)
    events_created: int | None = Field(default=None, ge=0)


class FramePush(BaseModel):
    model_config = ConfigDict(extra="forbid")
    jpeg_b64: str = Field(max_length=3_000_000)
    stats: dict = Field(default_factory=dict)


class WorkerState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["starting", "running", "stopped", "error"]
    message: str | None = Field(default=None, max_length=2000)


class DemoIncident(BaseModel):
    model_config = ConfigDict(extra="forbid")
    camera_id: str = Field(pattern=SAFE_ID_PATTERN)
