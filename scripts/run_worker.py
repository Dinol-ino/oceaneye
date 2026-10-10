"""Worker skeleton demo: pushes 3 MOCK frames through the all-mock analysis chain.
It detects nothing and raises no events - it only proves the wiring. Run: python scripts/run_worker.py"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # allow running without installing
import logging
from datetime import datetime, timezone

from app.camera.infrastructure.mock_source import MockCameraSource
from app.config.settings import get_settings
from app.core.domain.value_objects import GeoPoint
from app.core.entities.camera import Camera
from app.core.enums import CameraSourceType, CameraStatus
from app.persistence.repositories.in_memory import InMemoryZoneRepository
from app.shared.clock import SystemClock
from app.shared.logging_setup import configure_logging
from app.worker.factory import build_mock_worker
from app.worker.sinks import LoggingEventSink


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    camera = Camera("cam_mock", "MOCK camera", GeoPoint(0.0, 0.0), "mock://", CameraSourceType.MOCK,
                    CameraStatus.UNKNOWN, datetime.now(timezone.utc))
    worker = build_mock_worker(settings, InMemoryZoneRepository(), SystemClock(), LoggingEventSink())
    source = await MockCameraSource(camera.id).open()
    count = 0
    while (frame := await source.read()) is not None:
        count += len(await worker.process_frame(frame, camera))
    logging.getLogger("worker").info("processed mock frames; assessments=%d (skeleton: no real analysis)", count)
    await source.close()


if __name__ == "__main__":
    asyncio.run(main())
