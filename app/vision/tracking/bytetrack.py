"""ByteTrack (PDF stack) behind the Tracker interface.

Uses the standalone ``BYTETracker`` shipped with Ultralytics (Kalman filter + two-stage association),
so detection and tracking stay separate components. Track ids are camera-scoped and sequential per
camera (``cam_01-T1``, ``cam_01-T2``...); cross-camera re-identification is a later enhancement.
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Callable

import numpy as np

from app.core.domain.value_objects import BoundingBox
from app.core.exceptions import ConfigurationError
from app.vision.config import TrackerConfig
from app.vision.detection.base import Detection
from app.vision.tracking.base import Track, Tracker

logger = logging.getLogger(__name__)


class _DetectionBatch:
    """Minimal results-like object BYTETracker consumes (``conf``/``cls``/``xywh``, boolean indexing)."""

    def __init__(self, xywh: np.ndarray, conf: np.ndarray, cls: np.ndarray) -> None:
        self.xywh, self.conf, self.cls = xywh, conf, cls

    def __len__(self) -> int:
        return len(self.conf)

    def __getitem__(self, idx) -> "_DetectionBatch":
        return _DetectionBatch(self.xywh[idx], self.conf[idx], self.cls[idx])


@dataclass
class _CameraState:
    backend: Any
    frame_no: int = 0
    local_ids: dict[int, int] = field(default_factory=dict)
    histories: dict[int, deque] = field(default_factory=dict)
    last_seen: dict[int, int] = field(default_factory=dict)


def _default_backend(cfg: TrackerConfig, frame_rate: float) -> Any:
    try:
        from ultralytics.trackers.byte_tracker import BYTETracker  # noqa: PLC0415 - lazy
    except ImportError as exc:
        raise ConfigurationError(
            "ultralytics is not installed. Install the vision extras: pip install -e \".[vision]\""
        ) from exc
    import inspect  # noqa: PLC0415

    takes_frame_rate = "frame_rate" in inspect.signature(BYTETracker.__init__).parameters  # older Ultralytics
    # The buffer is configured in SECONDS and converted here against the rate frames actually
    # arrive at. Older Ultralytics divides by frame_rate internally and so expects a 30 fps-
    # equivalent count; newer versions count raw frames. Either way the track survives the same
    # real-world gap, which is what matters when a swimmer is hidden by a wave for two seconds.
    if takes_frame_rate:
        buffer = cfg.track_buffer                       # 30 fps-equivalent; backend rescales
    else:
        buffer = max(1, int(round(cfg.track_buffer_seconds * max(frame_rate, 1.0))))
    logger.info("tracker: lost-track buffer %.1fs (%d frames at %.1f fps), new-track threshold %.2f",
                cfg.track_buffer_seconds, buffer, frame_rate, cfg.new_track_thresh)
    args = SimpleNamespace(
        track_high_thresh=cfg.track_high_thresh, track_low_thresh=cfg.track_low_thresh,
        new_track_thresh=cfg.new_track_thresh, track_buffer=buffer,
        match_thresh=cfg.match_thresh, fuse_score=True,
    )
    if takes_frame_rate:
        return BYTETracker(args, frame_rate=max(1, int(round(frame_rate))))
    return BYTETracker(args)


class ByteTrackTracker(Tracker):
    def __init__(self, config: TrackerConfig | None = None, frame_rate: float = 30.0,
                 backend_factory: Callable[[TrackerConfig, float], Any] | None = None) -> None:
        self._cfg = config or TrackerConfig()
        self._frame_rate = frame_rate
        self._factory = backend_factory or _default_backend
        self._cams: dict[str, _CameraState] = {}
        self._class_ids: dict[str, int] = {}

    def _class_id(self, name: str) -> int:
        return self._class_ids.setdefault(name, len(self._class_ids))

    def update(self, camera_id: str, detections: list[Detection], timestamp: datetime) -> list[Track]:
        state = self._cams.get(camera_id)
        if state is None:
            state = self._cams[camera_id] = _CameraState(self._factory(self._cfg, self._frame_rate))
        state.frame_no += 1

        n = len(detections)
        xywh = np.zeros((n, 4), dtype=np.float32)
        conf = np.zeros((n,), dtype=np.float32)
        cls = np.zeros((n,), dtype=np.float32)
        for i, d in enumerate(detections):
            b = d.bbox
            xywh[i] = ((b.x_min + b.x_max) / 2, (b.y_min + b.y_max) / 2, b.x_max - b.x_min, b.y_max - b.y_min)
            conf[i] = d.confidence
            cls[i] = self._class_id(d.class_name)
        names = {v: k for k, v in self._class_ids.items()}

        # Called every frame even when empty, so lost tracks age out correctly.
        raw = state.backend.update(_DetectionBatch(xywh, conf, cls), None)

        arr = np.asarray(raw)
        rows = arr.reshape(-1, arr.shape[-1]) if arr.size else []
        tracks: list[Track] = []
        for row in rows:
            x1, y1, x2, y2, raw_id, score, class_id = (float(v) for v in row[:7])
            local = state.local_ids.setdefault(int(raw_id), len(state.local_ids) + 1)
            det = Detection(camera_id, names.get(int(class_id), "person"), score,
                            BoundingBox(min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)), timestamp)
            hist = state.histories.setdefault(local, deque(maxlen=self._cfg.history_len))
            hist.append(det)
            state.last_seen[local] = state.frame_no
            tracks.append(Track(f"{camera_id}-T{local}", camera_id, tuple(hist)))

        self._forget_stale(state)
        return tracks

    def _forget_stale(self, state: _CameraState) -> None:
        horizon = max(self._cfg.track_buffer * 3, 90)
        for local in [k for k, seen in state.last_seen.items() if state.frame_no - seen > horizon]:
            state.histories.pop(local, None)
            state.last_seen.pop(local, None)

    def reset(self, camera_id: str) -> None:
        self._cams.pop(camera_id, None)
