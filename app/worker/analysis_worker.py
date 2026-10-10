"""Frame -> perception -> zone gate -> behaviour -> risk -> sink. Orchestration only: every
stage is an injected interface, so YOLO/ByteTrack/real risk logic replace mocks without edits here."""
from __future__ import annotations

from app.core.domain.frame import Frame
from app.core.entities.camera import Camera
from app.environment.context import EnvironmentContext
from app.environment.external_data.base import EnvironmentalDataProvider
from app.environment.water_motion.base import WaterMotionAnalyzer
from app.environment.zones.service import ZoneGate, ZoneService
from app.risk.distress.base import BehaviorAnalyzer
from app.risk.engine.base import RiskAssessment, RiskInput
from app.risk.engine.service import RiskService
from app.vision.pipeline.base import VisionPipeline
from app.worker.sinks import EventSink


class AnalysisWorker:
    def __init__(self, pipeline: VisionPipeline, zones: ZoneService, zone_gate: ZoneGate,
                 behavior: BehaviorAnalyzer, water_motion: WaterMotionAnalyzer,
                 env: EnvironmentalDataProvider, risk: RiskService, sink: EventSink) -> None:
        self._pipeline, self._zones, self._gate = pipeline, zones, zone_gate
        self._behavior, self._water, self._env = behavior, water_motion, env
        self._risk, self._sink = risk, sink

    async def process_frame(self, frame: Frame, camera: Camera) -> list[RiskAssessment]:
        # TODO: run CPU-bound vision stages in an executor once real models exist.
        result = self._pipeline.process(frame)
        zone = self._zones.get_zone(camera.id)
        environment = EnvironmentContext(
            water_motion=self._water.analyze(frame, zone),
            conditions=await self._env.get_conditions(camera.location.lat, camera.location.lon),
        )
        assessments: list[RiskAssessment] = []
        size = (frame.image.shape[1], frame.image.shape[0]) if getattr(frame.image, "shape", None) is not None else None
        for track in result.tracks:
            zone_assessment = self._gate.evaluate(track, zone, frame.captured_at, size)
            behavior = self._behavior.analyze(track, result.poses.get(track.track_id), frame.captured_at)
            assessment = self._risk.assess(RiskInput(camera.id, track, zone_assessment, behavior,
                                                     environment, frame.captured_at))
            assessments.append(assessment)
            if assessment.actionable:
                await self._sink.submit(assessment)
        return assessments
