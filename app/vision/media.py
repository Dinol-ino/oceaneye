"""Media helpers for workers: downscaling, JPEG encoding and browser-playable H.264 MP4 writing.

OpenCV's pip wheels cannot write H.264, and browsers cannot play OpenCV's default MPEG-4 Part 2, so
videos/clips are written through ``imageio-ffmpeg`` (a pip package that bundles an ffmpeg binary - works
on Windows without installing ffmpeg). Falls back to OpenCV mp4v if it is missing.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def _fourcc(code: str) -> int:
    """``cv2.VideoWriter_fourcc`` was removed in OpenCV 5 in favour of ``cv2.VideoWriter.fourcc``."""
    fn = getattr(cv2.VideoWriter, "fourcc", None) or getattr(cv2, "VideoWriter_fourcc", None)
    if fn is None:  # pragma: no cover - no known OpenCV build without either name
        raise RuntimeError("this OpenCV build exposes no fourcc helper")
    return int(fn(*code))


def downscale(image: np.ndarray, max_width: int) -> np.ndarray:
    """Shrink ``image`` to at most ``max_width`` wide, preserving aspect. Returns the input unchanged
    when it already fits, so callers must treat the result as read-only.

    Used for everything that is *stored* rather than analysed - the evidence ring buffer above all.
    Keeping 6 seconds of annotated 1080p frames per worker was what exhausted this machine's memory
    mid-demo; at 854 px the same buffer costs roughly a seventh as much.
    """
    if max_width <= 0:
        return image
    h, w = image.shape[:2]
    if w <= max_width:
        return image
    return cv2.resize(image, (max_width, max(2, int(round(h * max_width / w)))), interpolation=cv2.INTER_AREA)


def encode_jpeg(image: np.ndarray, quality: int = 75, max_width: int = 960) -> bytes:
    ok, buf = cv2.imencode(".jpg", downscale(image, max_width), [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes() if ok else b""


def _even(image: np.ndarray) -> np.ndarray:
    """H.264 needs even dimensions for yuv420p."""
    h, w = image.shape[:2]
    return image[: h - h % 2, : w - w % 2]


class H264Writer:
    def __init__(self, path: str | Path, fps: float) -> None:
        self.path = Path(path)
        self._fps = max(1.0, float(fps))
        self._gen = None
        self._cv = None
        self._opened = False
        self.codec = None  # None until the first frame; stays None if no writer could be opened

    @property
    def fps(self) -> float:
        return self._fps

    @fps.setter
    def fps(self, value: float) -> None:
        """Settable until the first frame: callers learn the real frame rate only after the source opens."""
        if self._opened:
            raise RuntimeError("fps cannot change after the first frame has been written")
        self._fps = max(1.0, float(value))

    def _open(self, frame: np.ndarray) -> None:
        self._opened = True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        h, w = frame.shape[:2]
        try:
            import imageio_ffmpeg  # noqa: PLC0415

            self._gen = imageio_ffmpeg.write_frames(
                str(self.path), (w, h), pix_fmt_in="bgr24", pix_fmt_out="yuv420p", fps=self._fps, codec="libx264",
                quality=None, bitrate=None, macro_block_size=1, ffmpeg_log_level="error",
                output_params=["-preset", "veryfast", "-crf", "26", "-movflags", "+faststart"])
            self._gen.send(None)
            self.codec = "h264"
        except Exception as exc:  # noqa: BLE001 - fall back, the video is still useful
            logger.warning("H.264 writer unavailable (%s); using OpenCV mp4v (may not play in browsers)", exc)
            self._gen = None
            try:
                self._cv = cv2.VideoWriter(str(self.path), _fourcc("mp4v"), self._fps, (w, h))
            except Exception as inner:  # noqa: BLE001 - no writer at all: keep analysing, skip the video
                logger.error("no usable video writer (%s); overlay video will not be written", inner)
                self._cv = None
                return
            self.codec = "mp4v"

    def write(self, frame: np.ndarray) -> None:
        """Write one frame. A writer that could not be opened silently drops frames: losing the
        overlay video must never stop a monitoring session."""
        frame = _even(frame)
        if not self._opened:
            self._open(frame)
        if self._gen is not None:
            self._gen.send(np.ascontiguousarray(frame))
        elif self._cv is not None:
            self._cv.write(frame)

    def close(self) -> None:
        if self._gen is not None:
            try:
                self._gen.close()
            except Exception:  # noqa: BLE001 - closing a half-written file must not mask the real error
                logger.warning("ffmpeg writer did not close cleanly")
            self._gen = None
        if self._cv is not None:
            self._cv.release()
            self._cv = None


def write_clip(path: str | Path, frames: Iterable[np.ndarray], fps: float) -> str | None:
    writer = H264Writer(path, fps)
    n = 0
    try:
        for f in frames:
            writer.write(f)
            n += 1
    finally:
        writer.close()
    return str(path) if n else None


def limit_opencv_threads(n: int) -> None:
    cv2.setNumThreads(max(1, n))
