"""Perception configuration. Plain dataclasses (no pydantic) so notebooks/CLIs stay lightweight.

EXPERIMENTAL PARAMETERS: every numeric default below is a starting point to be tuned on real beach
footage; none is an OceanEye requirement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class DetectorConfig:
    model: str = "yolov8n.pt"  # PDF stack: YOLOv8 (Ultralytics). Any Ultralytics model name/path works.
    weights_dir: str | None = "models"  # bare model names are looked up / downloaded here
    device: str = "auto"  # auto | cpu | cuda:0 | mps
    imgsz: int = 960  # larger input helps small, distant swimmers (slower)
    conf: float = 0.10  # deliberately low: ByteTrack uses low-confidence boxes to keep tracks alive
    iou: float = 0.7
    max_det: int = 300
    classes: tuple[int, ...] = (0,)  # COCO class 0 = person
    half: bool | None = None  # None = FP16 on CUDA only


@dataclass(frozen=True)
class TrackerConfig:
    track_high_thresh: float = 0.25
    track_low_thresh: float = 0.10
    new_track_thresh: float = 0.25
    track_buffer: int = 30  # frames (at 30 fps) a lost track is kept
    match_thresh: float = 0.8
    history_len: int = 150  # detections kept per track (feeds trajectories / future behaviour features)


@dataclass(frozen=True)
class OverlayConfig:
    trail_length: int = 60
    thickness: int = 2
    show_hud: bool = True
    trail_anchor: str = "center"  # center | bottom


@dataclass(frozen=True)
class PerceptionConfig:
    camera_id: str = "cam_01"
    detector: DetectorConfig = field(default_factory=DetectorConfig)
    tracker: TrackerConfig = field(default_factory=TrackerConfig)
    overlay: OverlayConfig = field(default_factory=OverlayConfig)
    stride: int = 1  # process every Nth frame
    max_frames: int | None = None
    output_dir: str = "outputs/perception"
    save_video: bool = True
    save_tracks: bool = True
    show: bool = False  # live preview window (local desktop only; never in Colab)
