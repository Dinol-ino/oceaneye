"""PerceptionRunner: video source -> detect -> track -> overlay -> files (roadmap Stages 1-4).

Synchronous on purpose: works from a CLI, a Windows terminal, and a Colab/Jupyter cell (where
``asyncio.run`` is unusable). Outputs (per run folder):

* ``overlay.mp4``  annotated video (boxes, track ids, trajectories)
* ``tracks.jsonl`` one JSON object per processed frame - the dataset later stages (zone gate,
  behaviour features, risk) will consume
* ``summary.json`` timings, counts and the configuration used
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import cv2

from app.camera.infrastructure.opencv_source import OpenCvFrameSource
from app.camera.infrastructure.source_spec import SourceSpec, parse_source
from app.core.domain.frame import Frame
from app.core.exceptions import SourceOpenError
from app.vision.config import PerceptionConfig
from app.vision.devices import describe_device, resolve_device
from app.vision.pipeline.base import FrameResult, VisionPipeline
from app.vision.visualization.overlay import draw_tracks

logger = logging.getLogger(__name__)
SCHEMA_VERSION = 1

PipelineFactory = Callable[[float], VisionPipeline]
FrameCallback = Callable[[Frame, FrameResult, "object"], None]


@dataclass
class RunSummary:
    source: str
    run_dir: str
    frames_read: int = 0
    frames_processed: int = 0
    source_fps: float = 0.0
    effective_fps: float = 0.0
    width: int = 0
    height: int = 0
    video_duration_s: float = 0.0
    wall_time_s: float = 0.0
    avg_pipeline_ms: float = 0.0
    pipeline_fps: float = 0.0
    total_tracked_boxes: int = 0
    unique_track_ids: int = 0
    max_concurrent_tracks: int = 0
    device: str = ""
    model: str = ""
    outputs: dict[str, str] = field(default_factory=dict)
    config: dict = field(default_factory=dict)


def default_pipeline_factory(config: PerceptionConfig) -> PipelineFactory:
    """YOLO detector + ByteTrack tracker, plus YOLO-pose when ``config.pose.enabled``.

    ``fps`` is the effective (post-stride) frame rate.
    """
    def build(fps: float) -> VisionPipeline:
        from app.vision.detection.yolo import YoloDetector
        from app.vision.pipeline.default import DefaultVisionPipeline
        from app.vision.pose.yolo_pose import YoloPoseEstimator
        from app.vision.tracking.bytetrack import ByteTrackTracker

        pose_cfg = getattr(config, "pose", None)
        pose = YoloPoseEstimator(pose_cfg) if pose_cfg is not None and pose_cfg.enabled else None
        return DefaultVisionPipeline(YoloDetector(config.detector),
                                     ByteTrackTracker(config.tracker, frame_rate=fps), pose)
    return build


def _open_writer(path: Path, fps: float, size: tuple[int, int]):
    """Browser/VS Code-playable H.264 via imageio-ffmpeg; falls back to OpenCV mp4v, then MJPG/AVI."""
    from app.vision.media import H264Writer

    writer = H264Writer(path, fps)
    return writer, path


class PerceptionRunner:
    def __init__(self, config: PerceptionConfig, pipeline_factory: PipelineFactory | None = None,
                 on_frame: FrameCallback | None = None) -> None:
        self._cfg = config
        self._factory = pipeline_factory or default_pipeline_factory(config)
        self._on_frame = on_frame

    def run(self, source: "str | int | SourceSpec") -> RunSummary:
        cfg = self._cfg
        spec = source if isinstance(source, SourceSpec) else parse_source(source)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")  # local time, no ':' (Windows-safe)
        run_dir = Path(cfg.output_dir) / f"{spec.display_name}_{stamp}"
        run_dir.mkdir(parents=True, exist_ok=True)

        src = OpenCvFrameSource(cfg.camera_id, spec, stride=cfg.stride)
        info = src.open_sync()
        eff_fps = info.fps / cfg.stride
        pipeline = self._factory(eff_fps)

        device = resolve_device(cfg.detector.device)
        summary = RunSummary(
            source=spec.display_name, run_dir=str(run_dir), source_fps=info.fps, effective_fps=eff_fps,
            width=info.width, height=info.height, device=describe_device(device), model=cfg.detector.model,
            config=asdict(cfg),
        )
        writer = out_video = None
        tracks_file = (run_dir / "tracks.jsonl").open("w", encoding="utf-8") if cfg.save_tracks else None
        seen_ids: set[str] = set()
        pipeline_time = 0.0
        t0 = time.perf_counter()
        show = cfg.show
        try:
            while cfg.max_frames is None or summary.frames_processed < cfg.max_frames:
                frame = src.read_sync()
                if frame is None:
                    break
                p0 = time.perf_counter()
                result = pipeline.process(frame)
                pipeline_time += time.perf_counter() - p0

                summary.frames_processed += 1
                summary.total_tracked_boxes += len(result.tracks)
                summary.max_concurrent_tracks = max(summary.max_concurrent_tracks, len(result.tracks))
                seen_ids.update(t.track_id for t in result.tracks)
                video_t = frame.index / info.fps

                if tracks_file:
                    tracks_file.write(json.dumps({
                        "v": SCHEMA_VERSION, "camera_id": frame.camera_id, "frame_index": frame.index,
                        "video_time_s": round(video_t, 3), "timestamp": frame.captured_at.isoformat(),
                        "tracks": [{"track_id": t.track_id,
                                    "bbox": [round(t.current.bbox.x_min, 1), round(t.current.bbox.y_min, 1),
                                             round(t.current.bbox.x_max, 1), round(t.current.bbox.y_max, 1)],
                                    "conf": round(t.current.confidence, 3)} for t in result.tracks],
                    }) + "\n")

                annotated = None
                if cfg.save_video or show or self._on_frame:
                    live_fps = summary.frames_processed / pipeline_time if pipeline_time else None
                    annotated = draw_tracks(frame.image, result.tracks, cfg.overlay, frame_index=frame.index,
                                            timestamp_s=video_t, camera_id=frame.camera_id, fps=live_fps)
                if cfg.save_video:
                    if writer is None:
                        h, w = annotated.shape[:2]
                        writer, out_video = _open_writer(run_dir / "overlay.mp4", eff_fps, (w, h))
                    writer.write(annotated)
                if show:
                    try:
                        cv2.imshow("OceanEye perception (q to quit)", annotated)
                        if cv2.waitKey(1) & 0xFF == ord("q"):
                            break
                    except cv2.error:
                        logger.warning("no display available; continuing without preview")
                        show = False
                if self._on_frame:
                    self._on_frame(frame, result, annotated)
                if summary.frames_processed % 50 == 0:
                    logger.info("processed %d frames (%.1f fps pipeline)", summary.frames_processed,
                                summary.frames_processed / pipeline_time)
        finally:
            src.close_sync()
            if writer is not None:
                writer.close()
            if tracks_file:
                tracks_file.close()
            if cfg.show:
                try:
                    cv2.destroyAllWindows()
                except cv2.error:
                    pass

        summary.frames_read = summary.frames_processed * cfg.stride
        summary.wall_time_s = round(time.perf_counter() - t0, 3)
        summary.video_duration_s = round(summary.frames_read / info.fps, 3)
        n = summary.frames_processed
        summary.avg_pipeline_ms = round(1000 * pipeline_time / n, 2) if n else 0.0
        summary.pipeline_fps = round(n / pipeline_time, 2) if pipeline_time else 0.0
        summary.unique_track_ids = len(seen_ids)
        if out_video:
            summary.outputs["overlay_video"] = str(out_video)
        if cfg.save_tracks:
            summary.outputs["tracks_jsonl"] = str(run_dir / "tracks.jsonl")
        (run_dir / "summary.json").write_text(json.dumps(asdict(summary), indent=2), encoding="utf-8")
        summary.outputs["summary_json"] = str(run_dir / "summary.json")
        return summary
