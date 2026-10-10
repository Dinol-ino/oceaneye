"""PROPOSED SCAFFOLD endpoints (not in the reference list): the lifeguard client needs 'active alerts'."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.alerts.api.schemas import AlertResponse
from app.alerts.services.base import AlertService
from app.security.authorization import RESPONDER_ROLES
from app.security.dependencies import require_roles
from app.security.validation import SAFE_ID_PATTERN
from app.shared.dependencies import get_alert_service

router = APIRouter(prefix="/alerts", tags=["alerts"], dependencies=[Depends(require_roles(*RESPONDER_ROLES))])


@router.get("", response_model=list[AlertResponse])
async def list_alerts(active_only: bool = True, limit: Annotated[int, Query(ge=1, le=200)] = 50,
                      service: AlertService = Depends(get_alert_service)):
    return [AlertResponse.from_domain(a, service.build_payload(a))
            for a in service.list_alerts(active_only=active_only, limit=limit)]


@router.get("/{alert_id}", response_model=AlertResponse)
async def get_alert(alert_id: Annotated[str, Path(pattern=SAFE_ID_PATTERN)],
                    service: AlertService = Depends(get_alert_service)):
    alert = service.get(alert_id)
    return AlertResponse.from_domain(alert, service.build_payload(alert))
