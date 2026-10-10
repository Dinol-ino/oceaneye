"""YOLO (Ultralytics) person detector behind the Detector interface.

Replaces MockDetector with no other change. Weights are NOT bundled: Ultralytics downloads a bare
model name (e.g. ``yolov8n.pt``) on first use into ``weights_dir``.

What it detects: COCO "person" boxes. What it does NOT: swimmers' distress, submersion state, or water
zones - and a generic COCO model may miss partially submerged / very small people. That is expected at
this stage and is what the later stages (and eventually fine-tuning) address.

Two things here are about *measurement* rather than accuracy:

* **Warm-up.** The first CUDA inference costs seconds (kernel load, cuDNN autotuning). Without a
  warm-up pass the first frame stalls the pipeline and short runs report a nonsense frame rate - a
  24-frame job on an RTX 2050 measured 498 ms/frame when the steady-state cost was a fraction of that.
  :meth:`YoloDetector.warmup` pays that cost once, before the clock starts.
* **Half precision.** Ultralytics renamed ``half`` to ``quantize``; passing the old name on a current
  version logs a deprecation warning *per frame* (thousands of lines in the worker logs). The correct
  keyword is resolved once from the installed version's own config schema.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from app.core.domain.frame import Frame
from app.core.domain.value_objects import BoundingBox
from app.core.exceptions import ConfigurationError
from app.vision.config import DetectorConfig
from app.vision.detection.base import Detection, Detector
from app.vision.devices import describe_device, resolve_device

logger = logging.getLogger(__name__)


def resolve_weights(model: str, weights_dir: str | None) -> str:
    """Bare names go to ``weights_dir``; explicit paths (any separator, Windows included) are kept."""
    if weights_dir and not any(sep in model for sep in ("/", "\\")) and not Path(model).exists():
        Path(weights_dir).mkdir(parents=True, exist_ok=True)
        return str(Path(weights_dir) / model)
    return model


def half_precision_keyword() -> str | None:
    """Name the installed Ultralytics uses for fp16 inference: ``quantize``, ``half``, or neither.

    Resolved from the package's own default-config schema rather than a version number, so it keeps
    working across renames in either direction.
    """
    try:
        from ultralytics.cfg import DEFAULT_CFG_DICT  # noqa: PLC0415
    except Exception:  # noqa: BLE001 - older/newer layouts: fall back to the long-standing name
        return "half"
    for name in ("quantize", "half"):
        if name in DEFAULT_CFG_DICT:
            return name
    return None


def detections_from_arrays(frame: Frame, xyxy: np.ndarray, conf: np.ndarray, cls: np.ndarray,
                           names: dict[int, str]) -> list[Detection]:
    """Pure conversion of model output arrays to domain Detections (unit-testable without a model)."""
    out: list[Detection] = []
    for box, score, class_id in zip(xyxy.tolist(), conf.tolist(), cls.tolist()):
        x1, y1, x2, y2 = box
        out.append(Detection(
            camera_id=frame.camera_id, class_name=str(names.get(int(class_id), int(class_id))),
            confidence=float(score), bbox=BoundingBox(min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)),
            timestamp=frame.captured_at,
        ))
    return out


class YoloDetector(Detector):
    def __init__(self, config: DetectorConfig | None = None, model: Any = None) -> None:
        self._cfg = config or DetectorConfig()
        self._device = resolve_device(self._cfg.device)
        self._half = self._cfg.half if self._cfg.half is not None else self._device.startswith("cuda")
        self._model = model  # injectable for tests
        self._predict_kwargs: dict[str, Any] | None = None
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
                    "ultralytics is not installed. Install the vision extras: pip install -e \".[vision]\""
                ) from exc
            weights = resolve_weights(self._cfg.model, self._cfg.weights_dir)
            logger.info("loading detector %s on %s", weights, describe_device(self._device))
            self._model = YOLO(weights)
        return self._model

    def _kwargs(self) -> dict[str, Any]:
        """Build the per-call keyword set once (resolving the fp16 keyword exactly once)."""
        if self._predict_kwargs is None:
            kwargs: dict[str, Any] = {
                "imgsz": self._cfg.imgsz, "conf": self._cfg.conf, "iou": self._cfg.iou,
                "classes": list(self._cfg.classes) or None, "device": self._device,
                "max_det": self._cfg.max_det, "verbose": False,
            }
            if self._half:
                keyword = half_precision_keyword()
                if keyword:
                    kwargs[keyword] = True
                else:
                    logger.debug("installed ultralytics exposes no fp16 flag; running fp32")
            self._predict_kwargs = kwargs
        return self._predict_kwargs

    def warmup(self, width: int = 640, height: int = 384) -> float:
        """Run one throwaway inference so the first real frame is not 100x slower. Returns seconds.

        Safe to call more than once (only the first call does work) and never raises: a machine that
        cannot warm up will fail loudly on the first real frame instead, with the same error.
        """
        if self._warm:
            return 0.0
        self._warm = True
        import time  # noqa: PLC0415

        started = time.perf_counter()
        try:
            blank = np.zeros((max(32, height), max(32, width), 3), dtype=np.uint8)
            self._ensure_model().predict(source=blank, **self._kwargs())
        except Exception as exc:  # noqa: BLE001 - warm-up is an optimisation, not a requirement
            logger.warning("detector warm-up failed (%s); continuing", type(exc).__name__)
            return 0.0
        elapsed = time.perf_counter() - started
        logger.info("detector warm-up took %.2fs on %s", elapsed, describe_device(self._device))
        return elapsed

    def detect(self, frame: Frame) -> list[Detection]:
        if frame.image is None:
            return []
        model = self._ensure_model()
        results = model.predict(source=frame.image, **self._kwargs())
        result = results[0]
        boxes = result.boxes
        if boxes is None or len(boxes) == 0:
            return []
        return detections_from_arrays(
            frame, boxes.xyxy.cpu().numpy(), boxes.conf.cpu().numpy(), boxes.cls.cpu().numpy(), result.names
        )
