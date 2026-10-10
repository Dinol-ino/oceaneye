"""Protected evidence access. Evidence is never served from a public static path."""
from __future__ import annotations

import mimetypes
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path
from fastapi.responses import Response

from app.core.exceptions import NotFoundError
from app.events.services.event_service import EventService
from app.evidence.storage import EvidenceStorage
from app.security.authorization import RESPONDER_ROLES
from app.security.dependencies import require_roles
from app.security.validation import SAFE_ID_PATTERN
from app.shared.dependencies import get_event_service, get_evidence_storage

router = APIRouter(prefix="/evidence", tags=["evidence"], dependencies=[Depends(require_roles(*RESPONDER_ROLES))])


@router.get("/{event_id}/{kind}")
async def get_evidence(
    event_id: Annotated[str, Path(pattern=SAFE_ID_PATTERN)],
    kind: Literal["clip", "thumbnail"],
    events: EventService = Depends(get_event_service),
    storage: EvidenceStorage = Depends(get_evidence_storage),
):
    event = events.get(event_id)
    key = None
    if event.evidence:
        key = event.evidence.clip_key if kind == "clip" else event.evidence.thumbnail_key
    data = storage.read(key) if key else None
    if data is None:
        raise NotFoundError("Evidence", f"{event_id}/{kind}")
    media_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
    return Response(content=data, media_type=media_type)
