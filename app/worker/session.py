"""One monitoring session = one video source analysed end to end (roadmap Stages 1-10):

frames -> YOLO + ByteTrack -> zone gate -> behaviour signals -> rule-based risk (+ weather context)
       -> candidate event with evidence (thumbnail + H.264 clip) -> POST /api/events -> alerts / WebSocket

Modes
* ``job``    - an uploaded video, processed once; writes overlay.mp4 + tracks.jsonl, reports progress.
* ``camera`` - a CCTV / RTSP / phone / simulated (looped file) feed; pushes the latest annotated frame to the
               dashboard ~2x per second and runs until stopped.

Three decisions here are about keeping a laptop alive for a whole demo:

* **The evidence ring buffer is downscaled.** It holds the last few seconds of *annotated* frames so an
  event can ship a clip. At full 1080p that is ~220 MB per worker, and two workers plus the API ran this
  machine out of memory (``cv2.error ... Insufficient memory``). Clip frames are stored at
  ``clip_max_width`` instead; the event thumbnail still comes from the full-resolution frame.
* **Risk state outlives a loop restart.** A simulated CCTV camera replays the same clip forever. Rebuilding
  the risk engine on each replay reset its per-track cooldown and per-camera rate limit, so the same
  swimmer raised the same alert on every lap. The engine, analyser and zone gate are now built once per
  session.
* **The model is warmed up before the clock starts.** The first CUDA inference costs seconds; measuring it
  as if it were a normal frame is what made a healthy GPU report 2 fps.
"""
from __future__ import annotations

import base64
import json
import logging
import tempfile
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app.camera.infrastructure.opencv_source import OpenCvFrameSource
from app.core.domain.ids import new_id
from app.core.domain.value_objects import Polygon
from app.core.entities.zone import Zone
from app.core.enums import ZoneMode
from app.environment.context import EnvironmentContext
from app.environment.external_data.base import EnvironmentalConditions
from app.environment.zones.service import PolygonZoneGate
from app.evidence.storage import EvidenceStorage
from app.risk.distress.rules import RuleBasedBehaviorAnalyzer
from app.risk.engine.base import RiskAssessment, RiskInput
from app.risk.engine.rules import RuleBasedRiskEngine
from app.risk.scoring.config import RiskScoringConfig
from app.shared.hardware import probe as probe_hardware
from app.vision.config import DetectorConfig, OverlayConfig, TrackerConfig
from app.vision.devices import release_cuda_cache, resolve_device
from app.vision.media import H264Writer, downscale, encode_jpeg, write_clip
from app.vision.pipeline.base import VisionPipeline
from app.vision.profiles import PerceptionProfile, choose_profile
from app.vision.visualization.overlay import draw_risk, draw_tracks, draw_zone
from app.worker.api_client import ApiClient, ApiError

logger = logging.getLogger(__name__)

WEATHER_REFRESH_S = 600.0
PROGRESS_REPORT_S = 2.0
#: Values meaning "decide from the hardware" (see app.vision.profiles).
AUTO_MODEL = "auto"


@dataclass
class SessionConfig:
    mode: str  # job | camera
    camera_id: str
    camera_name: str
    lat: float
    lon: float
    source: str
    loop: bool = False
    zone_polygon: list | None = None
    zone_name: str | None = None
    model: str = AUTO_MODEL  # "auto" or an Ultralytics model name / path
    imgsz: int = 0  # 0 = auto
    device: str = "auto"
    target_fps: float = 0.0  # 0 = auto
    sensitivity: str = "medium"
    job_id: str | None = None
    output_dir: str | None = None
    weights_dir: str = "models"
    clip_seconds: float = 6.0
    clip_max_width: int = 0  # 0 = auto (from available RAM)
    push_fps: float = 2.0
    max_frames: int | None = None
    workers_sharing: int = 1  # how many workers the API expects to run at once

    @classmethod
    def from_worker_config(cls, mode: str, cfg: dict, **extra) -> "SessionConfig":
        cam, zone, opt = cfg["camera"], cfg.get("zone") or {}, cfg.get("options") or {}
        return cls(mode=mode, camera_id=cam["id"], camera_name=cam["name"], lat=cam["lat"], lon=cam["lon"],
                   source=cfg["source"], loop=bool(cfg.get("loop")), zone_polygon=zone.get("polygon"),
                   zone_name=zone.get("name"), model=opt.get("model", AUTO_MODEL),
                   imgsz=int(opt.get("imgsz", 0) or 0), device=opt.get("device", "auto"),
                   target_fps=float(opt.get("target_fps", 0) or 0), sensitivity=opt.get("sensitivity", "medium"),
                   workers_sharing=int(opt.get("workers_sharing", 1) or 1), job_id=cfg.get("job_id"),
                   output_dir=cfg.get("output_dir"), **extra)


PipelineFactory = Callable[["SessionConfig", float], VisionPipeline]


def resolve_profile(cfg: SessionConfig, device: str) -> PerceptionProfile:
    """Turn the ``auto`` placeholders in ``cfg`` into concrete values for this machine."""
    hw = probe_hardware()
    profile = choose_profile(
        device, vram_gb=hw.vram_gb, ram_gb=hw.ram_gb, cpu_count=hw.cpu_count,
        workers_sharing=cfg.workers_sharing,
        model=None if cfg.model in (AUTO_MODEL, "", None) else cfg.model,
        imgsz=cfg.imgsz or None, target_fps=cfg.target_fps or None,
    )
    if cfg.clip_max_width:  # explicit override wins
        profile = PerceptionProfile(profile.model, profile.imgsz, profile.target_fps, profile.half,
                                    cfg.clip_max_width, profile.reason + "; clip width from config")
    return profile


def default_pipeline(cfg: SessionConfig, fps: float) -> VisionPipeline:
    """Built from the *already resolved* cfg (see :meth:`MonitoringSession._prepare`)."""
    from app.vision.detection.yolo import YoloDetector
    from app.vision.pipeline.default import DefaultVisionPipeline
    from app.vision.tracking.bytetrack import ByteTrackTracker

    det = DetectorConfig(model=cfg.model, weights_dir=cfg.weights_dir, device=cfg.device, imgsz=cfg.imgsz)
    return DefaultVisionPipeline(YoloDetector(det), ByteTrackTracker(TrackerConfig(), frame_rate=fps))


@dataclass
class SessionStats:
    frames: int = 0
    pipeline_time: float = 0.0
    events: int = 0
    ids: set = field(default_factory=set)
    max_people: int = 0
    max_risk: float = 0.0
    warmup_s: float = 0.0
    laps: int = 0  # how many times a looping source replayed
    reconnects: int = 0
    wall_start: float = field(default_factory=time.monotonic)

    @property
    def wall_time(self) -> float:
        return max(1e-6, time.monotonic() - self.wall_start)


class MonitoringSession:
    def __init__(self, cfg: SessionConfig, client: ApiClient, evidence: EvidenceStorage,
                 pipeline_factory: PipelineFactory = default_pipeline, sleep=time.sleep) -> None:
        self.cfg, self.client, self.evidence = cfg, client, evidence
        self._factory, self._sleep = pipeline_factory, sleep
        self.stats = SessionStats()
        self.profile: PerceptionProfile | None = None
        self._zone = (Zone("zone", cfg.camera_id, cfg.zone_name or "Danger zone",
                           Polygon(tuple(tuple(p) for p in cfg.zone_polygon)), ZoneMode.STATIC, datetime.now(timezone.utc))
                      if cfg.zone_polygon else None)
        self._pipeline: VisionPipeline | None = None
        self._conditions: EnvironmentalConditions | None = None
        self._conditions_at: float | None = None
        # Built once per session so cooldowns and rate limits survive a looping source (see module docstring).
        self._risk_cfg = RiskScoringConfig.preset(cfg.sensitivity)
        self._gate = PolygonZoneGate()
        self._analyzer = RuleBasedBehaviorAnalyzer(self._risk_cfg)
        self._engine = RuleBasedRiskEngine(self._risk_cfg)

    # -- setup ----------------------------------------------------------------
    def _prepare(self) -> None:
        """Resolve the device and the auto profile, then write the choices back onto cfg.

        Done once, before the first frame, so the whole session (and the summary the dashboard shows)
        reports the values actually in use rather than the word "auto".
        """
        if self.profile is not None:
            return
        self.cfg.device = resolve_device(self.cfg.device)
        self.profile = resolve_profile(self.cfg, self.cfg.device)
        self.cfg.model = self.profile.model
        self.cfg.imgsz = self.profile.imgsz
        self.cfg.target_fps = self.profile.target_fps
        self.cfg.clip_max_width = self.profile.clip_max_width
        logger.info("perception profile: %s on %s", self.profile.describe(), self.cfg.device)

    # -- environment ----------------------------------------------------------
    def _environment(self) -> EnvironmentContext:
        now = time.monotonic()
        if self._conditions_at is None or now - self._conditions_at > WEATHER_REFRESH_S:
            self._conditions_at = now
            try:
                w = self.client.get("/weather", lat=self.cfg.lat, lon=self.cfg.lon)
                if w and w.get("status") != "unavailable":
                    self._conditions = EnvironmentalConditions(
                        lat=w["lat"], lon=w["lon"], fetched_at=datetime.now(timezone.utc), source=w["source"],
                        wind_speed_ms=w.get("wind_speed_ms"), wave_height_m=w.get("wave_height_m"),
                        swell_height_m=w.get("swell_height_m"), tide_height_m=w.get("tide_height_m"))
            except ApiError as exc:
                logger.warning("weather unavailable: %s", exc)
        return EnvironmentContext(conditions=self._conditions)

    # -- events -----------------------------------------------------------------
    def _raise_event(self, a: RiskAssessment, frame_image, ring: deque, fps: float, started_at: datetime) -> None:
        folder = f"{self.cfg.camera_id}/{new_id('ev')}"
        thumb_key, clip_key = f"{folder}/thumb.jpg", f"{folder}/clip.mp4"
        self.evidence.save(thumb_key, encode_jpeg(frame_image, quality=85, max_width=1280), "image/jpeg")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_clip = Path(tmp) / "clip.mp4"
                if write_clip(tmp_clip, list(ring), fps):
                    self.evidence.save(clip_key, tmp_clip.read_bytes(), "video/mp4")
                else:
                    clip_key = None
        except Exception as exc:  # noqa: BLE001 - an event without a clip is still an event
            logger.warning("clip not written: %s", exc)
            clip_key = None
        payload = {
            "camera_id": self.cfg.camera_id, "track_id": a.track_id[:64], "risk_score": a.risk_score,
            "risk_level": a.risk_level.value if a.risk_level else None,
            "started_at": started_at.isoformat(), "distress_signals": [s.value for s in a.contributing_signals],
            "reason": (f"[{self.cfg.mode}] {a.reason}")[:500],
            "evidence": {"thumbnail_key": thumb_key, **({"clip_key": clip_key} if clip_key else {})},
            "location": {"lat": self.cfg.lat, "lon": self.cfg.lon, "zone_name": self.cfg.zone_name},
        }
        self.client.post("/events", payload, retries=3)
        self.stats.events += 1
        logger.info("candidate event raised", extra={"track_id": a.track_id, "score": a.risk_score})

    # -- main loop ----------------------------------------------------------------
    def run(self) -> dict:
        cfg = self.cfg
        self._prepare()
        writer = tracks_file = None
        if cfg.mode == "job" and cfg.output_dir:
            out = Path(cfg.output_dir)
            out.mkdir(parents=True, exist_ok=True)
            writer = H264Writer(out / "overlay.mp4", 1.0)  # real fps set once the source opens
            tracks_file = (out / "tracks.jsonl").open("w", encoding="utf-8")
        try:
            while True:
                finished = self._run_once(writer, tracks_file)
                if finished or not cfg.loop or cfg.mode != "camera":
                    break
                self.stats.laps += 1
                logger.info("source ended; replaying (lap %d)", self.stats.laps + 1)
        finally:
            if writer:
                writer.close()
            if tracks_file:
                tracks_file.close()
            release_cuda_cache(cfg.device)  # let the next worker have the VRAM back
        return self.summary()

    def summary(self) -> dict:
        s = self.stats
        return {
            "frames_processed": s.frames,
            "pipeline_fps": round(s.frames / s.pipeline_time, 2) if s.pipeline_time else 0,
            "avg_pipeline_ms": round(1000 * s.pipeline_time / s.frames, 1) if s.frames else 0,
            "throughput_fps": round(s.frames / s.wall_time, 2),  # includes I/O, encoding and pacing
            "warmup_s": round(s.warmup_s, 2),
            "unique_track_ids": len(s.ids), "max_concurrent_people": s.max_people, "events_created": s.events,
            "max_risk_score": round(s.max_risk, 3), "model": self.cfg.model, "imgsz": self.cfg.imgsz,
            "device": self.cfg.device, "target_fps": self.cfg.target_fps,
            "profile": self.profile.reason if self.profile else None,
            "sensitivity": self.cfg.sensitivity, "zone": self.cfg.zone_name if self._zone else None,
            "laps": s.laps, "reconnects": s.reconnects,
        }

    def _warmup(self) -> None:
        """Pay the first-inference cost before the measured loop starts (see module docstring)."""
        if self._pipeline is not None:
            self.stats.warmup_s += self._pipeline.warmup()

    def _run_once(self, writer, tracks_file) -> bool:
        """Process the source once. Returns True when the session must end (max_frames reached)."""
        cfg = self.cfg
        src = OpenCvFrameSource(cfg.camera_id, cfg.source, start_time=datetime.now(timezone.utc))
        info = src.open_sync()
        # One open, not two: probing with a throwaway capture doubled connection cost on RTSP and
        # could drop the first second of a live stream.
        stride = max(1, round(info.fps / max(0.5, cfg.target_fps)))
        src.set_stride(stride)
        eff_fps = info.fps / stride
        if writer is not None and self.stats.frames == 0:
            writer.fps = eff_fps  # settable only before the first frame
        if self._pipeline is None:  # load the model once per session, not once per loop
            self._pipeline = self._factory(cfg, eff_fps)
            self._warmup()
        else:
            self._pipeline.reset(cfg.camera_id)
        pipeline = self._pipeline
        ring: deque = deque(maxlen=max(2, int(cfg.clip_seconds * eff_fps)))
        overlay_cfg = OverlayConfig(trail_length=max(10, int(eff_fps * 6)))
        total = info.frame_count or 0
        last_push = last_report = 0.0
        wall0 = time.monotonic()
        try:
            while True:
                if cfg.max_frames is not None and self.stats.frames >= cfg.max_frames:
                    return True
                frame = src.read_sync()
                if frame is None:
                    return False
                t0 = time.perf_counter()
                result = pipeline.process(frame)
                env = self._environment()
                size = (frame.image.shape[1], frame.image.shape[0])
                risks: dict[str, tuple[str, float]] = {}
                actionable: list[RiskAssessment] = []
                for track in result.tracks:
                    zone_a = self._gate.evaluate(track, self._zone, frame.captured_at, size)
                    beh = self._analyzer.analyze(track, result.poses.get(track.track_id), frame.captured_at)
                    a = self._engine.assess(RiskInput(cfg.camera_id, track, zone_a, beh, env, frame.captured_at))
                    risks[track.track_id] = (a.risk_level.value if a.risk_level else "low", a.risk_score)
                    self.stats.max_risk = max(self.stats.max_risk, a.risk_score)
                    if a.actionable:
                        actionable.append(a)
                elapsed = time.perf_counter() - t0
                self.stats.pipeline_time += elapsed
                self.stats.frames += 1
                self.stats.ids.update(t.track_id for t in result.tracks)
                self.stats.max_people = max(self.stats.max_people, len(result.tracks))

                annotated = draw_tracks(frame.image, result.tracks, overlay_cfg, frame_index=frame.index,
                                        timestamp_s=frame.index / info.fps, camera_id=cfg.camera_name,
                                        fps=self.stats.frames / self.stats.pipeline_time)
                draw_zone(annotated, cfg.zone_polygon, cfg.zone_name)
                draw_risk(annotated, result.tracks, risks)
                # Clip frames are stored small; the event thumbnail still uses `annotated` at full size.
                clip_frame = downscale(annotated, cfg.clip_max_width)
                ring.append(clip_frame if clip_frame is not annotated else annotated.copy())
                for a in actionable:
                    try:
                        self._raise_event(a, annotated, ring, eff_fps, frame.captured_at)
                    except ApiError as exc:
                        logger.error("event not delivered: %s", exc)

                if writer is not None:
                    writer.write(annotated)
                if tracks_file is not None:
                    tracks_file.write(json.dumps({
                        "v": 1, "frame_index": frame.index, "video_time_s": round(frame.index / info.fps, 3),
                        "tracks": [{"track_id": t.track_id, "bbox": [round(v, 1) for v in (
                            t.current.bbox.x_min, t.current.bbox.y_min, t.current.bbox.x_max, t.current.bbox.y_max)],
                            "conf": round(t.current.confidence, 3), "risk": risks.get(t.track_id, ("low", 0))[1]}
                            for t in result.tracks]}) + "\n")

                now = time.monotonic()
                if cfg.mode == "camera" and now - last_push >= 1.0 / cfg.push_fps:
                    last_push = now
                    self._push_frame(annotated, result, risks, frame, elapsed, src)
                if cfg.mode == "job" and now - last_report >= PROGRESS_REPORT_S:
                    last_report = now
                    progress = min(0.99, frame.index / total) if total else None
                    try:
                        self.client.post(f"/processing/jobs/{cfg.job_id}/report",
                                         {"status": "running", "progress": progress,
                                          "events_created": self.stats.events}, retries=0)
                    except ApiError as exc:
                        logger.warning("progress report failed: %s", exc)
                if cfg.mode == "camera" and cfg.loop:  # simulated CCTV: replay at real-time speed
                    lag = (frame.index / info.fps) - (time.monotonic() - wall0)
                    if lag > 0:
                        self._sleep(min(lag, 1.0))
        finally:
            self.stats.reconnects += src.reconnects
            src.close_sync()

    def _push_frame(self, annotated, result, risks, frame, elapsed, src) -> None:
        """Send the latest annotated frame + live stats to the dashboard. Never fatal."""
        stats = {"fps": round(self.stats.frames / self.stats.pipeline_time, 1) if self.stats.pipeline_time else 0,
                 "throughput_fps": round(self.stats.frames / self.stats.wall_time, 1),
                 "pipeline_ms": round(elapsed * 1000, 1), "people": len(result.tracks),
                 "frame_index": frame.index, "events": self.stats.events,
                 "model": self.cfg.model, "imgsz": self.cfg.imgsz, "device": self.cfg.device,
                 "reconnects": self.stats.reconnects + src.reconnects, "laps": self.stats.laps,
                 "risks": sorted(({"track_id": k, "level": v[0], "score": v[1]} for k, v in risks.items()
                                  if v[0] != "low"), key=lambda r: -r["score"])[:10]}
        try:
            self.client.post(f"/processing/cameras/{self.cfg.camera_id}/frame",
                             {"jpeg_b64": base64.b64encode(encode_jpeg(annotated)).decode(), "stats": stats},
                             retries=0)
        except ApiError as exc:
            logger.warning("frame push failed: %s", exc)
