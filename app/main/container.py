"""Composition root for the API process. The ONLY place concrete implementations are chosen.

Wiring order mirrors the startup flow: settings -> persistence -> repositories -> services ->
alert manager -> websocket manager -> (routers registered by the factory).
The vision/risk pipeline is deliberately NOT part of this process (see app.worker).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from app.alerts.escalation.base import EscalationService
from app.alerts.escalation.monitor import EscalationMonitor
from app.alerts.escalation.service import DefaultEscalationService
from app.alerts.handlers import register_alert_handlers
from app.alerts.notifications.base import NotificationProvider
from app.alerts.notifications.composite import CompositeNotificationProvider
from app.alerts.notifications.mock import MockNotificationProvider
from app.alerts.notifications.web_push import WebPushNotificationProvider
from app.alerts.notifications.websocket import WebSocketNotificationProvider
from app.alerts.services.alert_service import DefaultAlertService
from app.alerts.services.base import AlertService
from app.camera.infrastructure.stub_stream_manager import StubStreamManager
from app.camera.services.camera_service import CameraService
from app.config.settings import Settings
from app.core.exceptions import ConfigurationError
from app.core.interfaces.clock import Clock
from app.core.interfaces.event_bus import DomainEventBus
from app.core.interfaces.repositories import PushSubscriptionRepository
from app.environment.beaches.service import BeachSeed, BeachService
from app.environment.external_data.base import EnvironmentalDataProvider, PlaceDirectory
from app.environment.external_data.geoapify import GeoapifyPlaceDirectory, TileProxy
from app.environment.external_data.mock import MockEnvironmentalDataProvider, MockPlaceDirectory
from app.environment.external_data.open_meteo import OpenMeteoProvider
from app.environment.zones.service import RepositoryZoneService, ZoneService
from app.events.services.event_service import EventService
from app.evidence.local import LocalEvidenceStorage
from app.evidence.storage import EvidenceStorage
from app.persistence.database import Database
from app.persistence.repositories.sqlalchemy_repos import (
    SqlAlertRepository,
    SqlBeachRepository,
    SqlCameraRepository,
    SqlEventRepository,
    SqlJobRepository,
    SqlPushSubscriptionRepository,
    SqlUploadRepository,
    SqlZoneRepository,
)
from app.processing.live import LiveFrameStore
from app.processing.metrics import MetricsService
from app.processing.service import ProcessingPaths, ProcessingService, WorkerDefaults
from app.processing.supervisor import SubprocessWorkerLauncher, WorkerLauncher
from app.security.authentication import Authenticator, DevHeaderAuthenticator, TokenAuthenticator
from app.shared.clock import SystemClock
from app.shared.event_bus import InProcessEventBus
from app.shared.hardware import probe as probe_hardware
from app.shared.hardware import recommend_worker_slots
from app.websocket.manager import ConnectionManager

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Container:
    settings: Settings
    clock: Clock
    database: Database
    bus: DomainEventBus
    authenticator: Authenticator
    evidence_storage: EvidenceStorage
    zone_service: ZoneService
    beach_service: BeachService
    camera_service: CameraService
    event_service: EventService
    alert_service: AlertService
    escalation_service: EscalationService
    escalation_monitor: EscalationMonitor
    notification_provider: NotificationProvider
    push_repository: PushSubscriptionRepository
    ws_manager: ConnectionManager
    stream_manager: StubStreamManager
    env_provider: EnvironmentalDataProvider
    place_directory: PlaceDirectory
    tile_proxy: TileProxy
    processing_service: ProcessingService
    metrics_service: MetricsService
    launcher: WorkerLauncher
    readiness_checks: dict[str, Callable[[], bool]] = field(default_factory=dict)

    async def start(self) -> None:
        self.database.create_schema()  # additive schema sync; see Database._add_missing_columns
        s = self.settings
        beach = self.beach_service.ensure_seeded(BeachSeed(
            name=s.default_location_name, region=s.default_region, lat=s.default_lat, lon=s.default_lon,
            authority_name=s.beach_authority_name, authority_phone=s.beach_authority_phone))
        logger.info("deployment beach: %s", beach.label)
        if s.escalation_monitor_enabled:
            await self.escalation_monitor.start()
        hw = probe_hardware()
        logger.info("container started (hardware: %s, worker slots: %d)", hw.describe(), s.max_workers)
        self._warn_if_oversubscribed(hw)

    def _warn_if_oversubscribed(self, hw) -> None:
        """Say so when OCEANEYE_MAX_WORKERS asks for more than this machine can hold.

        An explicit value always wins over the auto policy - an operator may know something we do
        not - but running more workers than the memory supports is exactly what killed an earlier
        demo mid-run, and a silent misconfiguration is worse than a noisy one. Each worker loads its
        own model.
        """
        recommended = recommend_worker_slots(hw)
        if self.settings.max_workers > recommended:
            logger.warning(
                "OCEANEYE_MAX_WORKERS=%d, but this machine (%s) is sized for %d worker(s). "
                "Each worker loads its own model; running more can exhaust memory mid-session "
                "(the symptom is a worker dying with 'Insufficient memory'). "
                "Set OCEANEYE_MAX_WORKERS=0 to let OceanEye size itself.",
                self.settings.max_workers, hw.describe(), recommended)

    async def stop(self) -> None:
        await self.escalation_monitor.stop()
        self.launcher.stop_all()  # never leave worker processes behind
        await self.ws_manager.close_all()
        await self.stream_manager.stop_all()
        self.database.dispose()
        logger.info("container stopped")


def _build_notifier(settings: Settings, ws_manager: ConnectionManager,
                    push_repo: PushSubscriptionRepository, clock: Clock) -> NotificationProvider:
    providers: list[NotificationProvider] = []
    for channel in settings.notification_channels:
        if channel == "websocket":
            providers.append(WebSocketNotificationProvider(ws_manager))
        elif channel == "mock":
            providers.append(MockNotificationProvider())
        elif channel == "web_push":
            providers.append(WebPushNotificationProvider(
                push_repo, clock,
                vapid_private_key=settings.vapid_private_key.get_secret_value() if settings.vapid_private_key else "",
                vapid_subject=settings.vapid_subject, ttl_seconds=settings.push_ttl_seconds))
        else:  # sms is a boundary only at this stage
            raise ConfigurationError(f"Notification channel '{channel}' is not implemented yet")
    return CompositeNotificationProvider(providers)


def build_container(settings: Settings, clock: Clock | None = None,
                    launcher: WorkerLauncher | None = None) -> Container:
    clock = clock or SystemClock()

    if settings.weather_provider == "open_meteo":
        env_provider: EnvironmentalDataProvider = OpenMeteoProvider(
            clock, settings.open_meteo_forecast_url, settings.open_meteo_marine_url,
            settings.external_cache_ttl_seconds, settings.external_timeout_seconds)
    else:
        env_provider = MockEnvironmentalDataProvider(clock)
    api_key = settings.geoapify_api_key.get_secret_value() if settings.geoapify_api_key else None
    places: PlaceDirectory = (
        GeoapifyPlaceDirectory(api_key, ttl_seconds=settings.external_cache_ttl_seconds,
                               timeout=settings.external_timeout_seconds)
        if settings.places_provider == "geoapify" else MockPlaceDirectory())
    tiles = TileProxy(api_key, style=settings.map_style,
                      cache_entries=settings.map_tile_cache_entries)
    if settings.places_provider == "geoapify" and not api_key:
        logger.warning("place search and map tiles need OCEANEYE_GEOAPIFY_API_KEY; "
                       "the beach picker will fall back to typing a place in by hand")

    database = Database(settings.database_url)
    sf = database.session_factory
    beach_repo, camera_repo, zone_repo = SqlBeachRepository(sf), SqlCameraRepository(sf), SqlZoneRepository(sf)
    event_repo, alert_repo = SqlEventRepository(sf), SqlAlertRepository(sf)
    push_repo: PushSubscriptionRepository = SqlPushSubscriptionRepository(sf)

    bus = InProcessEventBus()
    evidence = LocalEvidenceStorage(settings.evidence_dir)
    authenticator: Authenticator = (
        DevHeaderAuthenticator() if settings.auth_mode == "dev" else TokenAuthenticator()
    )

    zone_service = RepositoryZoneService(zone_repo, clock)
    beach_service = BeachService(beach_repo, camera_repo, places, clock)
    camera_service = CameraService(camera_repo, zone_service, clock)
    event_service = EventService(event_repo, camera_repo, zone_repo, bus, clock)

    ws_manager = ConnectionManager()
    notifier = _build_notifier(settings, ws_manager, push_repo, clock)
    alert_service = DefaultAlertService(alert_repo, event_repo, notifier, clock,
                                        settings.ack_timeout_seconds, settings.api_prefix)
    escalation_service = DefaultEscalationService(alert_repo, event_service, notifier, clock, settings.api_prefix)
    register_alert_handlers(bus, alert_service, escalation_service)
    monitor = EscalationMonitor(escalation_service, settings.escalation_check_interval_seconds)

    live = LiveFrameStore()
    launcher = launcher or SubprocessWorkerLauncher(PROJECT_ROOT, settings.logs_dir, settings.worker_api_url,
                                                    settings.max_workers, settings.worker_threads)
    job_repo = SqlJobRepository(sf)
    processing = ProcessingService(
        SqlUploadRepository(sf), job_repo, camera_repo, zone_service, launcher, live, clock,
        ProcessingPaths(settings.upload_dir, settings.jobs_dir),
        WorkerDefaults(settings.worker_model, settings.worker_imgsz, settings.worker_device,
                       settings.worker_target_fps, settings.worker_sensitivity,
                       settings.worker_clip_max_width, settings.max_workers),
        settings.max_upload_mb)
    metrics = MetricsService(event_repo, job_repo, live, clock)

    return Container(
        settings=settings, clock=clock, database=database, bus=bus, authenticator=authenticator,
        evidence_storage=evidence, zone_service=zone_service, beach_service=beach_service,
        camera_service=camera_service, event_service=event_service, alert_service=alert_service,
        escalation_service=escalation_service, escalation_monitor=monitor, notification_provider=notifier,
        push_repository=push_repo, ws_manager=ws_manager, stream_manager=StubStreamManager(),
        env_provider=env_provider, place_directory=places, tile_proxy=tiles,
        processing_service=processing, metrics_service=metrics, launcher=launcher,
        readiness_checks={"database": database.ping, "evidence_storage": evidence.healthcheck},
    )
