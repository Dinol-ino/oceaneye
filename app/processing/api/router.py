"""Prototype video endpoints: uploads, analysis jobs, live camera monitoring, metrics, demo incident.
PROPOSED SCAFFOLD - not in the reference endpoint list; needed for the upload / multi-CCTV prototype."""
from __future__ import annotations

import base64
import binascii
from typing import Annotated

from fastapi import APIRouter, Depends, File, Path, Query, UploadFile
from fastapi.responses import FileResponse, Response

from app.core.entities.event import EvidenceRef
from app.core.enums import JobStatus, RiskLevel
from app.core.exceptions import DomainValidationError, NotFoundError
from app.events.api.schemas import EventResponse
from app.events.domain.commands import NewEventCommand
from app.processing.api.schemas import (
    DemoIncident,
    FramePush,
    JobCreate,
    JobReport,
    JobResponse,
    UploadResponse,
    WorkerState,
)
from app.processing.service import JobOptions
from app.security.authorization import EVENT_PRODUCER_ROLES, MANAGEMENT_ROLES, RESPONDER_ROLES
from app.security.dependencies import require_roles
from app.security.principal import Principal
from app.security.validation import SAFE_ID_PATTERN
from app.shared.dependencies import (
    get_api_prefix,
    get_container,
    get_metrics_service,
    get_processing_service,
)
from app.environment.external_data.geoapify import ATTRIBUTION as GEOAPIFY_ATTRIBUTION
from app.shared.hardware import probe as probe_hardware

router = APIRouter(tags=["processing"])
Id = Annotated[str, Path(pattern=SAFE_ID_PATTERN)]
manage = [Depends(require_roles(*MANAGEMENT_ROLES))]
respond = [Depends(require_roles(*RESPONDER_ROLES))]
service = [Depends(require_roles(*EVENT_PRODUCER_ROLES))]


# ---- uploads & analysis jobs --------------------------------------------------
@router.post("/uploads", response_model=UploadResponse, status_code=201, dependencies=manage)
def upload_video(file: UploadFile = File(...), svc=Depends(get_processing_service)):
    return UploadResponse.from_domain(svc.save_upload(file.filename or "", file.file))


@router.get("/uploads", response_model=list[UploadResponse], dependencies=manage)
def list_uploads(svc=Depends(get_processing_service)):
    return [UploadResponse.from_domain(u) for u in svc.list_uploads()]


@router.post("/analysis/jobs", response_model=JobResponse, status_code=201, dependencies=manage)
def create_job(body: JobCreate, svc=Depends(get_processing_service), prefix: str = Depends(get_api_prefix)):
    opts = JobOptions(model=body.model, imgsz=body.imgsz, device=body.device, sensitivity=body.sensitivity)
    return JobResponse.from_domain(svc.create_job(body.upload_id, body.camera_id, opts), prefix)


@router.get("/analysis/jobs", response_model=list[JobResponse], dependencies=manage)
def list_jobs(limit: Annotated[int, Query(ge=1, le=200)] = 30, svc=Depends(get_processing_service),
              prefix: str = Depends(get_api_prefix)):
    return [JobResponse.from_domain(j, prefix) for j in svc.list_jobs(limit)]


@router.get("/analysis/jobs/{job_id}", response_model=JobResponse, dependencies=manage)
def get_job(job_id: Id, svc=Depends(get_processing_service), prefix: str = Depends(get_api_prefix)):
    return JobResponse.from_domain(svc.get_job(job_id), prefix)


@router.post("/analysis/jobs/{job_id}/cancel", response_model=JobResponse, dependencies=manage)
def cancel_job(job_id: Id, svc=Depends(get_processing_service), prefix: str = Depends(get_api_prefix)):
    return JobResponse.from_domain(svc.cancel_job(job_id), prefix)


# Removals below clear *test material* only - uploaded clips and analysis-job records. Events,
# evidence and alerts are the audit trail of a safety system and have no delete route by design.
@router.delete("/analysis/jobs/{job_id}", status_code=204, dependencies=manage)
def delete_job(job_id: Id, svc=Depends(get_processing_service)):
    """Remove one finished job. A running job must be cancelled first (409)."""
    svc.delete_job(job_id)
    return Response(status_code=204)


@router.post("/analysis/jobs/clear-finished", dependencies=manage)
def clear_finished_jobs(svc=Depends(get_processing_service)):
    """Remove every completed, failed and cancelled job. Running jobs are left alone."""
    return {"removed": svc.clear_finished_jobs()}


@router.delete("/uploads/{upload_id}", status_code=204, dependencies=manage)
def delete_upload(upload_id: Id, svc=Depends(get_processing_service)):
    """Remove an uploaded clip and its file. Refused (409) while a job or camera still uses it."""
    svc.delete_upload(upload_id)
    return Response(status_code=204)


@router.get("/analysis/jobs/{job_id}/video", dependencies=respond)
def job_video(job_id: Id, svc=Depends(get_processing_service)):
    return FileResponse(svc.job_overlay_path(job_id), media_type="video/mp4")


# ---- live cameras -----------------------------------------------------------------
@router.post("/cameras/{camera_id}/monitoring/start", status_code=202, dependencies=manage)
def start_monitoring(camera_id: Id, svc=Depends(get_processing_service)):
    svc.start_monitoring(camera_id)
    return {"camera_id": camera_id, "monitoring": True}


@router.post("/cameras/{camera_id}/monitoring/stop", dependencies=manage)
def stop_monitoring(camera_id: Id, svc=Depends(get_processing_service)):
    svc.stop_monitoring(camera_id)
    return {"camera_id": camera_id, "monitoring": False}


@router.get("/live/cameras", dependencies=respond)
def live_overview(svc=Depends(get_processing_service)):
    return svc.live_overview()


@router.get("/live/cameras/{camera_id}/frame", dependencies=respond)
def live_frame(camera_id: Id, svc=Depends(get_processing_service)):
    state = svc.live.state(camera_id)
    if not state.jpeg:
        raise NotFoundError("Live frame for camera", camera_id)
    return Response(state.jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


# ---- public config ------------------------------------------------------------------
@router.get("/config/public", dependencies=respond)
def public_config(container=Depends(get_container)):
    """Non-secret settings the web interfaces need: the deployment beach, capabilities, worker defaults.

    The interfaces use ``capabilities`` to decide what to offer rather than guessing: background push
    only works on a secure origin with VAPID keys configured, so the lifeguard app asks here instead
    of showing a button that cannot work.
    """
    s = container.settings
    beach = container.beach_service.active()
    hw = probe_hardware()
    return {
        "app_version": s.app_version,
        "beach": ({"id": beach.id, "name": beach.name, "region": beach.region, "label": beach.label,
                   "lat": beach.location.lat, "lon": beach.location.lon,
                   "authority_name": beach.authority_name, "authority_phone": beach.authority_phone,
                   "lifeguard_count": beach.lifeguard_count} if beach else None),
        # Kept for compatibility with existing clients and as a fallback before a beach is configured.
        "location_name": beach.label if beach else s.default_location_name,
        "lat": beach.location.lat if beach else s.default_lat,
        "lon": beach.location.lon if beach else s.default_lon,
        "emergency_phone": s.emergency_phone,
        "ack_timeout_seconds": s.ack_timeout_seconds,
        "auth_mode": s.auth_mode,
        "max_workers": s.max_workers,
        "capabilities": {"secure_context": s.tls_enabled, "web_push": s.push_enabled,
                         "weather": s.weather_provider != "mock",
                         "place_search": s.places_enabled, "map_tiles": s.map_tiles_enabled},
        # Tiles come through this application, not straight from the provider: the API key stays on
        # the server. The browser only ever sees this path.
        "map": {"tile_url": f"{s.api_prefix}/map/tiles/{s.map_style}/{{z}}/{{x}}/{{y}}.png",
                "attribution": GEOAPIFY_ATTRIBUTION,
                "satellite_url": s.map_satellite_url,
                "satellite_attribution": s.map_satellite_attribution,
                "max_zoom": s.map_max_zoom},
        "hardware": {"gpu": hw.gpu_name, "vram_gb": round(hw.vram_gb, 1) if hw.vram_gb else None,
                     "cpu_count": hw.cpu_count, "ram_gb": round(hw.ram_gb, 1) if hw.ram_gb else None},
        "worker": {"model": s.worker_model, "imgsz": s.worker_imgsz, "device": s.worker_device,
                   "target_fps": s.worker_target_fps, "sensitivity": s.worker_sensitivity},
        "weather_provider": s.weather_provider,
    }


# ---- metrics & demo -----------------------------------------------------------------
@router.get("/metrics", dependencies=respond)
def metrics(m=Depends(get_metrics_service)):
    return m.snapshot()


@router.post("/demo/incident", response_model=EventResponse, status_code=201)
async def demo_incident(body: DemoIncident, principal: Principal = Depends(require_roles(*MANAGEMENT_ROLES)),
                        container=Depends(get_container), prefix: str = Depends(get_api_prefix)):
    """Inject a clearly labelled DEMO alert to rehearse the lifeguard / escalation flow. Not AI output."""
    evidence = None
    jpeg = container.processing_service.live.state(body.camera_id).jpeg
    if jpeg:
        key = f"demo/{body.camera_id}_{int(container.clock.now().timestamp())}.jpg"
        container.evidence_storage.save(key, jpeg, "image/jpeg")
        evidence = EvidenceRef(thumbnail_key=key)
    event = await container.event_service.create_candidate(NewEventCommand(
        camera_id=body.camera_id, track_id="DEMO", risk_score=0.8, risk_level=RiskLevel.HIGH,
        reason=f"DEMO / TEST ALERT triggered by {principal.subject} - not produced by the AI pipeline",
        evidence=evidence))
    return EventResponse.from_domain(event, prefix)


# ---- worker callbacks (role: service) ----------------------------------------------
@router.get("/processing/jobs/{job_id}/worker-config", dependencies=service)
def job_worker_config(job_id: Id, svc=Depends(get_processing_service)):
    return svc.job_worker_config(job_id)


@router.post("/processing/jobs/{job_id}/report", dependencies=service)
def report_job(job_id: Id, body: JobReport, svc=Depends(get_processing_service)):
    job = svc.report_job(job_id, JobStatus(body.status), body.progress, body.summary, body.error, body.events_created)
    return {"id": job.id, "status": job.status.value}


@router.get("/processing/cameras/{camera_id}/worker-config", dependencies=service)
def camera_worker_config(camera_id: Id, svc=Depends(get_processing_service)):
    return svc.camera_worker_config(camera_id)


@router.post("/processing/cameras/{camera_id}/frame", status_code=204, dependencies=service)
def push_frame(camera_id: Id, body: FramePush, svc=Depends(get_processing_service), container=Depends(get_container)):
    try:
        jpeg = base64.b64decode(body.jpeg_b64, validate=True)
    except (binascii.Error, ValueError):
        raise DomainValidationError("jpeg_b64 is not valid base64") from None
    svc.live.put_frame(camera_id, jpeg, body.stats, container.clock.now())
    return Response(status_code=204)


@router.post("/processing/cameras/{camera_id}/state", status_code=204, dependencies=service)
def worker_state(camera_id: Id, body: WorkerState, svc=Depends(get_processing_service)):
    svc.live.set_worker_state(camera_id, body.state, body.message)
    return Response(status_code=204)
