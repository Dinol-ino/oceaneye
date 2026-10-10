"""Cross-cutting API schemas."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class NotImplementedNotice(BaseModel):
    implemented: bool = False
    note: str
