from __future__ import annotations

from app.config.settings import Settings
from app.core.interfaces.clock import Clock
from app.core.interfaces.repositories import ZoneRepository
from app.environment.external_data.mock import MockEnvironmentalDataProvider
from app.environment.water_motion.mock import MockWaterMotionAnalyzer
from app.environment.zones.service import MockZoneGate, RepositoryZoneService
from app.risk.distress.mock import MockBehaviorAnalyzer
from app.risk.engine.mock import MockRiskEngine
from app.risk.engine.service import RiskService
from app.vision.detection.mock import MockDetector
from app.vision.pipeline.default import DefaultVisionPipeline
from app.vision.pose.mock import MockPoseEstimator
from app.vision.tracking.mock import MockTracker
from app.worker.analysis_worker import AnalysisWorker
from app.worker.sinks import EventSink


def build_mock_worker(settings: Settings, zone_repo: ZoneRepository, clock: Clock, sink: EventSink) -> AnalysisWorker:
    """Every stage is a MOCK. Swap individual lines for real implementations later."""
    return AnalysisWorker(
        pipeline=DefaultVisionPipeline(MockDetector(), MockTracker(), MockPoseEstimator()),
        zones=RepositoryZoneService(zone_repo, clock), zone_gate=MockZoneGate(),
        behavior=MockBehaviorAnalyzer(), water_motion=MockWaterMotionAnalyzer(),
        env=MockEnvironmentalDataProvider(clock), risk=RiskService(MockRiskEngine()), sink=sink,
    )


def build_perception_pipeline(config, fps: float = 30.0):
    """Real perception chain (YOLO + ByteTrack). Needs the ``vision`` extras; imports are lazy."""
    from app.vision.detection.yolo import YoloDetector
    from app.vision.pipeline.default import DefaultVisionPipeline
    from app.vision.tracking.bytetrack import ByteTrackTracker

    return DefaultVisionPipeline(YoloDetector(config.detector), ByteTrackTracker(config.tracker, frame_rate=fps))
