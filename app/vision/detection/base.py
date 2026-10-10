"""Detection contract. The YOLO (Ultralytics) implementation lives in ``yolo.py``."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from app.core.domain.frame import Frame
from app.core.domain.value_objects import BoundingBox


@dataclass(frozen=True)
class Detection:
    camera_id: str
    class_name: str  # e.g. "person"
    confidence: float
    bbox: BoundingBox
    timestamp: datetime


class Detector(ABC):
    @abstractmethod
    def detect(self, frame: Frame) -> list[Detection]: ...

    def warmup(self) -> float:
        """Load and exercise the model now; return the seconds it took.

        A real model's first inference is far slower than the rest (weights load, CUDA kernels
        compile). Doing it up front keeps the first analysed frame from stalling the pipeline and
        keeps reported frame rates honest. Default: nothing to warm up.
        """
        return 0.0
