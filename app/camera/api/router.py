from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.camera.api.schemas import CameraCreate, CameraResponse
from app.core.enums import CameraSourceType
from app.camera.services.camera_service import CameraService, NewCameraCommand
from app.security.authorization import MANAGEMENT_ROLES, RESPONDER_ROLES
from app.security.dependencies import require_roles
from app.security.validation import SAFE_ID_PATTERN
from app.shared.dependencies import get_beach_service, get_camera_service, get_processing_service

router = APIRouter(prefix="/cameras", tags=["cameras"])


@router.post("", response_model=CameraResponse, status_code=201,
             dependencies=[Depends(require_roles(*MANAGEMENT_ROLES))])
def register_camera(body: CameraCreate, service: CameraService = Depends(get_camera_service),
                    beaches=Depends(get_beach_service), processing=Depends(get_processing_service)):
    stream = body.stream_url
    source_type = body.source_type
    if body.video_upload_id:  # simulated CCTV: server-side path of an uploaded clip
        stream = str(processing.upload_path(body.video_upload_id))
        # An uploaded clip is a file whatever the client said. source_type drives whether the
        # worker loops the source and how it opens it, so a clip mislabelled as RTSP produces a
        # camera that never opens - and the failure surfaces minutes later as a silent "offline".
        source_type = CameraSourceType.VIDEO_FILE
    beach_id = body.beach_id
    if beach_id:
        beaches.get(beach_id)  # 404 rather than a dangling reference
    else:
        active = beaches.active()
        beach_id = active.id if active else None
    camera = service.register(
        NewCameraCommand(
            name=body.name, lat=body.lat, lon=body.lon, stream_url=stream, source_type=source_type,
            zone_polygon=tuple(tuple(p) for p in body.zone_polygon) if body.zone_polygon else None,
            beach_id=beach_id,
        )
    )
    return CameraResponse.from_domain(camera)


@router.get("", response_model=list[CameraResponse],
            dependencies=[Depends(require_roles(*RESPONDER_ROLES))])
def list_cameras(beach_id: Annotated[str | None, Query(pattern=SAFE_ID_PATTERN)] = None,
                 service: CameraService = Depends(get_camera_service)):
    """All cameras, or - with ``beach_id`` - only one deployment site's."""
    return [CameraResponse.from_domain(c) for c in service.list(beach_id)]
