"""Real pose estimation with an Ultralytics YOLO-pose model.

WHY THIS EXISTS
---------------
Until now ``PoseEstimator`` had only :class:`~app.vision.pose.mock.MockPoseEstimator`, which
returns nothing, so every pose-dependent distress signal was unreachable. That left the behaviour
analyzer reasoning purely about where a *bounding box* moved - which cannot tell a swimmer from a
person in difficulty, because both are a box drifting in water.

Keypoints change that. A COCO-17 pose model is pretrained and needs no training data of our own,
and two of its outputs map directly onto the recognised signs of the instinctive drowning response:

* the body goes **vertical** in the water (swimming is horizontal), and
* the arms come **up and out** to press down on the surface.

Neither is proof. Both are evidence the box-trajectory heuristics simply cannot see.

LIMITS, STATED PLAINLY
----------------------
* COCO pose is trained on land photographs of whole people. A torso cropped by the waterline, in
  glare, at 40 m, is out of distribution: expect low keypoint confidence and dropped poses. Every
  consumer must treat a missing pose as "unknown", never as "fine".
* This is a second model on the same GPU. On a 4 GB laptop card it roughly halves throughput, so
  it is **off by default** and enabled explicitly (``PoseConfig.enabled``).
* Nothing here is validated. The angle and ratio thresholds are starting points to be tuned
  against labelled footage with ``scripts/evaluate_detection.py``.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from app.core.exceptions import ConfigurationError
from app.core.domain.frame import Frame
from app.vision.devices import describe_device, resolve_device
from app.vision.pose.base import PoseEstimate, PoseKeypoint, PoseEstimator
from app.vision.tracking.base import Track

logger = logging.getLogger(__name__)

#: COCO-17 keypoint order, exactly as Ultralytics emits it.
COCO_KEYPOINTS: tuple[str, ...] = (
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
)


@dataclass(frozen=True)
class PoseConfig:
    """EXPERIMENTAL PARAMETERS - starting points, not validated thresholds."""

    enabled: bool = False          # a second model on the same GPU; opt in deliberately
    model: str = "yolov8n-pose.pt"  # smallest pose model; -s and -m also work
    weights_dir: str | None = "models"
    device: str = "auto"
    imgsz: int = 640
    conf: float = 0.25
    #: A keypoint below this confidence is treated as absent rather than believed.
    keypoint_conf: float = 0.30
    #: Minimum IoU for a detected pose to be considered the same person as a track's box.
    match_iou: float = 0.45


def _iou(a, b) -> float:
    """Intersection-over-union of two BoundingBox-like objects."""
    ix1, iy1 = max(a.x_min, b.x_min), max(a.y_min, b.y_min)
    ix2, iy2 = min(a.x_max, b.x_max), min(a.y_max, b.y_max)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = (a.x_max - a.x_min) * (a.y_max - a.y_min)
    area_b = (b.x_max - b.x_min) * (b.y_max - b.y_min)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


class _Box:
    """Minimal box so IoU matching needs no domain import gymnastics."""

    __slots__ = ("x_min", "y_min", "x_max", "y_max")

    def __init__(self, x1: float, y1: float, x2: float, y2: float) -> None:
        self.x_min, self.y_min, self.x_max, self.y_max = x1, y1, x2, y2


class YoloPoseEstimator(PoseEstimator):
    """Keypoints per track, matched to the tracker's boxes by IoU.

    The pose model runs its own person detector, so its boxes are not the tracker's boxes. Matching
    by IoU keeps the track id as the single identity across the whole pipeline: an unmatched pose is
    dropped rather than invented onto the nearest track, because a pose attached to the wrong person
    is worse than no pose at all - it would put one swimmer's posture in another's risk score.
    """

    def __init__(self, config: PoseConfig | None = None, model: Any = None) -> None:
        self._cfg = config or PoseConfig()
        self._device = resolve_device(self._cfg.device)
        self._model = model  # injectable for tests
        self._warm = False

    @property
    def device(self) -> str:
        return self._device

    def _ensure_model(self) -> Any:
        if self._model is None:
            try:
                from ultralytics import YOLO  # noqa: PLC0415 - heavy, lazy
            except ImportError as exc:
                raise ConfigurationError(
                    'ultralytics is not installed. Install the vision extras: pip install -e ".[vision]"'
                ) from exc
            from app.vision.detection.yolo import resolve_weights  # noqa: PLC0415 - shared resolver

            weights = resolve_weights(self._cfg.model, self._cfg.weights_dir)
            logger.info("loading pose model %s on %s", weights, describe_device(self._device))
            self._model = YOLO(weights)
        return self._model

    def estimate(self, frame: Frame, tracks: list[Track]) -> dict[str, PoseEstimate]:
        if not self._cfg.enabled or frame.image is None or not tracks:
            return {}
        model = self._ensure_model()
        results = model.predict(frame.image, imgsz=self._cfg.imgsz, conf=self._cfg.conf,
                                device=self._device, verbose=False)
        if not results:
            return {}
        result = results[0]
        keypoints = getattr(result, "keypoints", None)
        boxes = getattr(result, "boxes", None)
        if keypoints is None or boxes is None or keypoints.data is None:
            return {}

        kp_data = keypoints.data.cpu().numpy()        # (n, 17, 3) -> x, y, confidence
        box_data = boxes.xyxy.cpu().numpy()           # (n, 4)
        poses: dict[str, PoseEstimate] = {}
        used: set[int] = set()

        for track in tracks:
            tb = track.current.bbox
            best, best_iou = -1, self._cfg.match_iou
            for i, (x1, y1, x2, y2) in enumerate(box_data):
                if i in used:
                    continue
                score = _iou(tb, _Box(float(x1), float(y1), float(x2), float(y2)))
                if score >= best_iou:
                    best, best_iou = i, score
            if best < 0:
                continue  # no confident match: this track has no pose this frame, and says so
            used.add(best)
            points = tuple(
                PoseKeypoint(name=COCO_KEYPOINTS[j], x=float(x), y=float(y), confidence=float(c))
                for j, (x, y, c) in enumerate(kp_data[best])
                if c >= self._cfg.keypoint_conf
            )
            if not points:
                continue
            poses[track.track_id] = PoseEstimate(track.track_id, frame.captured_at, points)
        return poses

    def warmup(self) -> float:
        """Load and exercise the model now, so the first real frame is not the slow one."""
        if not self._cfg.enabled or self._warm:
            return 0.0
        started = time.perf_counter()
        try:
            import numpy as np  # noqa: PLC0415

            model = self._ensure_model()
            blank = np.zeros((self._cfg.imgsz, self._cfg.imgsz, 3), dtype=np.uint8)
            model.predict(blank, imgsz=self._cfg.imgsz, device=self._device, verbose=False)
        except Exception as exc:  # a failed warm-up must not stop monitoring
            logger.warning("pose warm-up failed (%s); continuing without a warmed pose model", exc)
            return 0.0
        self._warm = True
        elapsed = time.perf_counter() - started
        logger.info("pose warm-up took %.2fs on %s", elapsed, describe_device(self._device))
        return elapsed
