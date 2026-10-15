"""Perception configuration. Plain dataclasses (no pydantic) so notebooks/CLIs stay lightweight.

EXPERIMENTAL PARAMETERS: every numeric default below is a starting point to be tuned on real beach
footage; none is an OceanEye requirement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.vision.pose.yolo_pose import PoseConfig


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
    """Association thresholds.

    MEASURED PROBLEM these defaults address: on a 9.5 s crowded-beach clip the previous settings
    produced 157 distinct track ids for at most 32 people on screen - a mean track life of 1.6 s.
    Every distress signal is temporal (stillness needs 6 s, bobbing needs 4 s), so on 1.6 s
    fragments the slow signals could never fire at all and the fast ones fired on noise. Tracking
    continuity is not a tuning detail here; it is the precondition for the behaviour layer
    meaning anything.

    The split between the three confidence thresholds is what ByteTrack exists for:
    ``track_low_thresh`` stays low so a weak detection can *continue* a track through spray and
    partial occlusion, while ``new_track_thresh`` is high so that same weak box cannot *create* a
    track. Previously both were 0.25, so every flicker of foam started a new identity.
    """

    track_high_thresh: float = 0.25   # first association pass: confident detections
    track_low_thresh: float = 0.10    # second pass: keep existing tracks alive on weak evidence
    new_track_thresh: float = 0.55    # birth of a NEW identity needs real confidence
    #: Seconds a lost track is remembered before its identity is retired. Expressed in SECONDS, not
    #: frames: the old frame count meant 1 s at 30 fps but 10 s at 3 fps, so the tracker behaved
    #: like a different algorithm depending on how fast the machine happened to be.
    track_buffer_seconds: float = 2.5
    match_thresh: float = 0.8
    history_len: int = 300  # detections kept per track; must cover the longest behaviour window

    @property
    def track_buffer(self) -> int:
        """Backwards-compatible frame count at the 30 fps ByteTrack assumes internally."""
        return max(1, int(round(self.track_buffer_seconds * 30.0)))


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
    #: Off by default: a second model on the same GPU roughly halves throughput. Turn it on to get
    #: the posture signals that separate swimming from distress (app.vision.pose.yolo_pose).
    pose: "PoseConfig" = field(default_factory=lambda: PoseConfig())
    overlay: OverlayConfig = field(default_factory=OverlayConfig)
    stride: int = 1  # process every Nth frame
    max_frames: int | None = None
    output_dir: str = "outputs/perception"
    save_video: bool = True
    save_tracks: bool = True
    show: bool = False  # live preview window (local desktop only; never in Colab)
