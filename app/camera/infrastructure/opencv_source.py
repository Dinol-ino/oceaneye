"""OpenCV-backed video source: recorded files, webcams, RTSP/HTTP streams (reference roadmap
Stage 1 / testing path: recorded video -> phone RTSP -> real CCTV, same code path).

OpenCV is imported lazily so the API process and the test-suite run without it
(``pip install -e ".[vision]"`` to enable).

Live sources differ from files in two ways this class handles explicitly:

* **Staying current.** A 30 fps camera analysed at 6 fps must *discard* the frames in between, not
  queue them, or the analysis drifts further behind real time every second. ``stride`` does that with
  ``grab()`` (no decode), and the capture buffer is pinned to one frame where the backend allows it.
* **Surviving a drop.** Wi-Fi hiccups and camera reboots end the stream. Rather than ending the
  monitoring session, a live source reconnects with a bounded back-off and keeps going.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.camera.domain.sources import CameraSource, FrameSource
from app.camera.infrastructure.source_spec import SourceKind, SourceSpec, parse_source
from app.core.domain.frame import Frame
from app.core.enums import CameraSourceType
from app.core.exceptions import SourceOpenError

logger = logging.getLogger(__name__)
DEFAULT_FPS = 30.0
RECONNECT_ATTEMPTS = 5
RECONNECT_BASE_DELAY_S = 1.0
RECONNECT_MAX_DELAY_S = 15.0


@dataclass(frozen=True)
class SourceInfo:
    fps: float
    width: int
    height: int
    frame_count: int | None  # None for live sources
    is_live: bool


def _import_cv2():
    try:
        import cv2  # noqa: PLC0415 - intentionally lazy
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise SourceOpenError(
            "OpenCV is not installed. Install the vision extras: pip install -e \".[vision]\""
        ) from exc
    return cv2


class OpenCvFrameSource(FrameSource):
    """Synchronous API (``open_sync``/``read_sync``) for CLIs and notebooks (Jupyter already runs an
    event loop, so ``asyncio.run`` is unusable there); async ``read`` wraps it for the worker."""

    def __init__(self, camera_id: str, spec: "SourceSpec | str | int", *, stride: int = 1,
                 start_time: datetime | None = None, reconnect_attempts: int = RECONNECT_ATTEMPTS,
                 sleep=time.sleep) -> None:
        if stride < 1:
            raise ValueError("stride must be >= 1")
        self._camera_id = camera_id
        self._spec = spec if isinstance(spec, SourceSpec) else parse_source(spec)
        self._stride = stride
        self._start_time = start_time or datetime.now(timezone.utc)
        self._reconnect_attempts = max(0, reconnect_attempts)
        self._sleep = sleep
        self._cap = None
        self._info: SourceInfo | None = None
        self._next_index = 0
        self.reconnects = 0  # observability: how often this stream dropped

    # -- lifecycle -----------------------------------------------------
    @property
    def info(self) -> SourceInfo:
        if self._info is None:
            raise SourceOpenError("source is not open")
        return self._info

    def _capture(self):
        """Open the underlying VideoCapture (no SourceInfo probing). Raises SourceOpenError."""
        cv2 = _import_cv2()
        spec = self._spec
        if spec.kind is SourceKind.FILE:
            if not os.path.isfile(spec.value):
                raise SourceOpenError(f"video file not found: {spec.value}")
            cap = cv2.VideoCapture(spec.value)
        elif spec.kind is SourceKind.WEBCAM:
            backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY  # DirectShow is the reliable one on Windows
            cap = cv2.VideoCapture(spec.webcam_index, backend)
        else:  # network stream
            os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")  # TCP is more robust than UDP on Wi-Fi
            cap = cv2.VideoCapture(spec.value, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            cap.release()
            hint = ""
            if spec.kind is SourceKind.FILE and sys.platform == "win32" and not spec.value.isascii():
                hint = " (non-ASCII characters in the path can break OpenCV on Windows; try an ASCII path)"
            raise SourceOpenError(f"could not open video source '{spec.display_name}'{hint}")
        if spec.is_live:
            try:  # keep only the newest frame where the backend supports it; harmless if ignored
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:  # noqa: BLE001 - an advisory hint, never fatal
                pass
        return cap

    def open_sync(self) -> SourceInfo:
        cv2 = _import_cv2()
        cap = self._capture()
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        if not math.isfinite(fps) or fps <= 0 or fps > 1000:
            logger.warning("source reports no valid FPS; assuming %.0f", DEFAULT_FPS)
            fps = DEFAULT_FPS
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self._cap = cap
        self._info = SourceInfo(
            fps=fps, width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0),
            height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0),
            frame_count=count if (self._spec.kind is SourceKind.FILE and count > 0) else None,
            is_live=self._spec.is_live,
        )
        return self._info

    def set_stride(self, stride: int) -> None:
        """Change how many frames are skipped per analysed frame (used to hit a target frame rate
        once the real source FPS is known, without reopening the stream)."""
        if stride < 1:
            raise ValueError("stride must be >= 1")
        self._stride = stride

    def close_sync(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    # -- reading -------------------------------------------------------
    def _reconnect(self) -> bool:
        """Reopen a dropped live stream with bounded exponential back-off. True when reconnected."""
        for attempt in range(1, self._reconnect_attempts + 1):
            delay = min(RECONNECT_BASE_DELAY_S * 2 ** (attempt - 1), RECONNECT_MAX_DELAY_S)
            logger.warning("stream '%s' lost; reconnect attempt %d/%d in %.0fs",
                           self._spec.display_name, attempt, self._reconnect_attempts, delay)
            self._sleep(delay)
            if self._cap is not None:
                self._cap.release()
                self._cap = None
            try:
                self._cap = self._capture()
            except SourceOpenError as exc:
                logger.warning("reconnect failed: %s", exc.message if hasattr(exc, "message") else exc)
                continue
            self.reconnects += 1
            logger.info("stream '%s' reconnected after %d attempt(s)", self._spec.display_name, attempt)
            return True
        logger.error("stream '%s' could not be reconnected after %d attempts",
                     self._spec.display_name, self._reconnect_attempts)
        return False

    def read_sync(self) -> Frame | None:
        """Next frame (every ``stride``-th), or None at end of file / unrecoverable stream loss.

        A live stream that drops is reconnected first; a file simply ends.
        """
        if self._cap is None:
            raise SourceOpenError("source is not open")
        cv2 = _import_cv2()
        try:
            ok, image = self._cap.read()
        except cv2.error as exc:
            if "Insufficient memory" in str(exc) or "OutOfMemory" in str(exc):
                import gc
                gc.collect()
                try:
                    ok, image = self._cap.read()
                except cv2.error:
                    return None
            else:
                raise
        if not ok or image is None:
            if not (self._info and self._info.is_live) or not self._reconnect():
                return None
            try:
                ok, image = self._cap.read()
            except cv2.error:
                return None
            if not ok or image is None:
                return None
        if image.shape[1] > 1920:
            scale = 1920 / image.shape[1]
            image = cv2.resize(image, (1920, int(image.shape[0] * scale)), interpolation=cv2.INTER_AREA)
        index = self._next_index
        self._next_index += 1
        for _ in range(self._stride - 1):  # grab() skips decoding work for the frames we drop
            if not self._cap.grab():
                break
            self._next_index += 1
        if self._info and not self._info.is_live:
            captured_at = self._start_time + timedelta(seconds=index / self._info.fps)  # video time, reproducible
        else:
            captured_at = datetime.now(timezone.utc)
        return Frame(camera_id=self._camera_id, captured_at=captured_at, index=index, image=image)

    async def read(self) -> Frame | None:
        return await asyncio.to_thread(self.read_sync)

    async def close(self) -> None:
        self.close_sync()


class OpenCvCameraSource(CameraSource):
    def __init__(self, camera_id: str, source_type: CameraSourceType, spec: SourceSpec, stride: int = 1) -> None:
        self.camera_id = camera_id
        self.source_type = source_type
        self._spec = spec
        self._stride = stride

    async def open(self) -> FrameSource:
        source = OpenCvFrameSource(self.camera_id, self._spec, stride=self._stride)
        await asyncio.to_thread(source.open_sync)
        return source
