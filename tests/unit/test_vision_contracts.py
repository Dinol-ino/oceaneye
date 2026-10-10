import asyncio
from datetime import datetime, timezone

from app.camera.infrastructure.factory import CameraSourceFactory
from app.camera.infrastructure.mock_source import MockCameraSource
from app.core.domain.frame import Frame
from app.core.domain.value_objects import BoundingBox, GeoPoint
from app.core.entities.camera import Camera
from app.core.enums import CameraSourceType, CameraStatus
from app.persistence.repositories.in_memory import InMemoryZoneRepository
from app.shared.clock import SystemClock
from app.vision.detection.base import Detection
from app.vision.detection.mock import MockDetector
from app.vision.pipeline.default import DefaultVisionPipeline
from app.vision.pose.mock import MockPoseEstimator
from app.vision.tracking.mock import MockTracker
from app.worker.factory import build_mock_worker
from app.worker.sinks import LoggingEventSink
from app.config.settings import Settings

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
FRAME = Frame("cam_1", NOW, 0)


def test_empty_pipeline_yields_nothing():
    r = DefaultVisionPipeline(MockDetector(), MockTracker(), MockPoseEstimator()).process(FRAME)
    assert r.detections == [] and r.tracks == [] and r.poses == {}


def test_detector_swap_flows_through_pipeline():
    det = Detection("cam_1", "person", 0.8, BoundingBox(0, 0, 4, 4), NOW)
    r = DefaultVisionPipeline(MockDetector([det]), MockTracker()).process(FRAME)
    assert r.tracks[0].current_position == (2.0, 2.0)


def test_mock_source_and_real_source_creation_is_lazy():
    async def run():
        src = await MockCameraSource("cam_1", 2).open()
        frames = [await src.read(), await src.read(), await src.read()]
        return frames
    f = asyncio.run(run())
    assert f[0].index == 0 and f[1].index == 1 and f[2] is None
    cam = Camera("c", "n", GeoPoint(0, 0), "rtsp://h/x", CameraSourceType.RTSP, CameraStatus.UNKNOWN, NOW)
    src = CameraSourceFactory().create(cam)  # creating a source never connects
    assert src.camera_id == "c" and src.source_type is CameraSourceType.RTSP


def test_worker_chain_runs_with_mocks_and_raises_no_events():
    cam = Camera("cam_1", "n", GeoPoint(0, 0), "mock://", CameraSourceType.MOCK, CameraStatus.UNKNOWN, NOW)
    det = Detection("cam_1", "person", 0.8, BoundingBox(0, 0, 4, 4), NOW)
    worker = build_mock_worker(Settings(_env_file=None), InMemoryZoneRepository(), SystemClock(), LoggingEventSink())
    worker._pipeline = DefaultVisionPipeline(MockDetector([det]), MockTracker())
    out = asyncio.run(worker.process_frame(FRAME, cam))
    assert len(out) == 1 and out[0].actionable is False
