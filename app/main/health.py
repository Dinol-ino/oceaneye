from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.shared.dependencies import get_container

router = APIRouter(tags=["system"])


@router.get("/health")
async def health():
    """Liveness: process is up. No dependencies checked."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(container=Depends(get_container)):
    """Readiness: dependencies (database, evidence storage) reachable."""
    checks = {name: bool(check()) for name, check in container.readiness_checks.items()}
    ok = all(checks.values())
    return JSONResponse(status_code=200 if ok else 503,
                        content={"status": "ready" if ok else "not_ready", "checks": checks})
