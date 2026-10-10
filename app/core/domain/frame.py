from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Frame:
    """One video frame. ``image`` is opaque here (a numpy array once OpenCV is introduced),
    which keeps core free of CV dependencies."""

    camera_id: str
    captured_at: datetime
    index: int
    image: Any = None
