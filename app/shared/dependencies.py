"""FastAPI accessors for services built by the composition root (app.main.container).

Routers import from here (not from app.main) to avoid circular imports. Types are
referenced under TYPE_CHECKING only.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:  # pragma: no cover
    from app.alerts.services.base import AlertService
    from app.camera.services.camera_service import CameraService
    from app.core.interfaces.repositories import PushSubscriptionRepository
    from app.environment.beaches.service import BeachService
    from app.environment.external_data.base import EnvironmentalDataProvider
    from app.environment.zones.service import ZoneService
    from app.events.services.event_service import EventService
    from app.evidence.storage import EvidenceStorage
    from app.main.container import Container


def get_container(request: Request) -> "Container":
    return request.app.state.container


def get_camera_service(request: Request) -> "CameraService":
    return request.app.state.container.camera_service


def get_beach_service(request: Request) -> "BeachService":
    return request.app.state.container.beach_service


def get_zone_service(request: Request) -> "ZoneService":
    return request.app.state.container.zone_service


def get_event_service(request: Request) -> "EventService":
    return request.app.state.container.event_service


def get_alert_service(request: Request) -> "AlertService":
    return request.app.state.container.alert_service


def get_env_provider(request: Request) -> "EnvironmentalDataProvider":
    return request.app.state.container.env_provider


def get_place_directory(request: Request):
    return request.app.state.container.place_directory


def get_tile_proxy(request: Request):
    return request.app.state.container.tile_proxy


def get_push_repository(request: Request) -> "PushSubscriptionRepository":
    return request.app.state.container.push_repository


def get_processing_service(request: Request):
    return request.app.state.container.processing_service


def get_metrics_service(request: Request):
    return request.app.state.container.metrics_service


def get_evidence_storage(request: Request) -> "EvidenceStorage":
    return request.app.state.container.evidence_storage


def get_api_prefix(request: Request) -> str:
    return request.app.state.container.settings.api_prefix
