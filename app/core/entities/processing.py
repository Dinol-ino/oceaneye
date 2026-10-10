"""Uploaded videos and analysis jobs (prototype video-analysis path; reference PDF section 9 test path)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.core.enums import JobStatus


@dataclass
class UploadedVideo:
    id: str
    filename: str  # original (display) name
    stored_name: str  # safe name inside the upload dir (never a client-supplied path)
    size_bytes: int
    created_at: datetime


@dataclass
class AnalysisJob:
    id: str
    upload_id: str
    camera_id: str
    status: JobStatus
    created_at: datetime
    options: dict = field(default_factory=dict)
    progress: float = 0.0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    summary: dict = field(default_factory=dict)
    overlay_key: str | None = None
    events_created: int = 0
