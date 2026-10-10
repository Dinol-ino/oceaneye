import asyncio

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from app.camera.infrastructure.factory import CameraSourceFactory  # noqa: E402
from app.camera.infrastructure.opencv_source import OpenCvCameraSource, OpenCvFrameSource  # noqa: E402
from app.camera.infrastructure.source_spec import SourceKind, SourceSpec  # noqa: E402
from app.core.domain.value_objects import GeoPoint  # noqa: E402
from app.core.entities.camera import Camera  # noqa: E402
from app.core.enums import CameraSourceType, CameraStatus  # noqa: E402
from app.core.exceptions import DomainValidationError, SourceOpenError  # noqa: E402
from app.vision.media import _fourcc  # noqa: E402
from tests.conftest import FakeClock  # noqa: E402


def make_video(path, frames=12, size=(64, 48), fps=10):
    # _fourcc, not cv2.VideoWriter_fourcc: that name was removed in OpenCV 5.
    writer = cv2.VideoWriter(str(path), _fourcc("mp4v"), fps, size)
    assert writer.isOpened()
    for i in range(frames):
        img = np.full((size[1], size[0], 3), (i * 10) % 250, dtype=np.uint8)
        writer.write(img)
    writer.release()
    return path


@pytest.fixture
def video(tmp_path):
    d = tmp_path / "my videos"  # a space in the path, as on Windows
    d.mkdir()
    return make_video(d / "beach 01.mp4")


def test_reads_all_frames_with_video_time(video):
    src = OpenCvFrameSource("cam_t", str(video))
    info = src.open_sync()
    assert (info.width, info.height, info.frame_count, info.is_live) == (64, 48, 12, False)
    frames = []
    while (f := src.read_sync()) is not None:
        frames.append(f)
    src.close_sync()
    assert [f.index for f in frames] == list(range(12))
    assert frames[0].image.shape == (48, 64, 3)
    dt = (frames[5].captured_at - frames[0].captured_at).total_seconds()
    assert abs(dt - 5 / info.fps) < 1e-6


def test_stride_skips_frames_but_keeps_original_indices(video):
    src = OpenCvFrameSource("cam_t", str(video), stride=3)
    src.open_sync()
    assert [f.index for f in iter(src.read_sync, None)] == [0, 3, 6, 9]


def test_stride_can_be_set_after_opening(video):
    """The worker learns the source's real FPS only after opening it, and must not reopen a stream."""
    src = OpenCvFrameSource("cam_t", str(video))
    src.open_sync()
    src.set_stride(4)
    assert [f.index for f in iter(src.read_sync, None)] == [0, 4, 8]
    with pytest.raises(ValueError):
        src.set_stride(0)


def test_missing_file_and_unopened_source(tmp_path):
    with pytest.raises(SourceOpenError):
        OpenCvFrameSource("c", str(tmp_path / "nope.mp4")).open_sync()
    with pytest.raises(SourceOpenError):
        OpenCvFrameSource("c", "x.mp4").read_sync()


def test_file_end_is_not_treated_as_a_dropped_stream(video):
    """A file that ends is finished; only a live source is worth reconnecting."""
    src = OpenCvFrameSource("cam_t", str(video), reconnect_attempts=3, sleep=lambda _: None)
    src.open_sync()
    while src.read_sync() is not None:
        pass
    assert src.reconnects == 0


class _FlakyCapture:
    """Yields ``good`` frames, then fails - standing in for an RTSP stream that drops."""

    def __init__(self, good: int) -> None:
        self.good, self.n, self.released = good, 0, False

    def read(self):
        if self.n >= self.good:
            return False, None
        self.n += 1
        return True, np.zeros((8, 8, 3), dtype=np.uint8)

    def grab(self):
        return False

    def isOpened(self):  # noqa: N802 - OpenCV's name
        return True

    def release(self):
        self.released = True

    def get(self, _prop):
        return 0.0

    def set(self, _prop, _value):
        return True


def test_live_stream_reconnects_then_gives_up(monkeypatch):
    """A dropped live stream is reopened with back-off, so a session survives a Wi-Fi hiccup -
    and ends cleanly once the camera is really gone instead of looping forever."""
    captures: list[_FlakyCapture] = []
    reopens_allowed = 3  # the original open plus two successful reconnects

    def fake_capture(self):
        if len(captures) >= reopens_allowed:
            raise SourceOpenError("camera unreachable")
        cap = _FlakyCapture(good=2)
        captures.append(cap)
        return cap

    monkeypatch.setattr(OpenCvFrameSource, "_capture", fake_capture)
    src = OpenCvFrameSource("cam_live", SourceSpec(SourceKind.STREAM, "rtsp://host/live"),
                            reconnect_attempts=2, sleep=lambda _: None)
    src.open_sync()
    read = 0
    while src.read_sync() is not None:
        read += 1
        if read > 20:  # guard against an accidental infinite loop in the test
            pytest.fail("source never reported end of stream")
    assert read == 6 and src.reconnects == 2 and len(captures) == reopens_allowed
    assert all(c.released for c in captures[:-1])  # dropped captures are not leaked


def test_async_read_wrapper(video):
    async def run():
        src = OpenCvFrameSource("cam_t", str(video))
        src.open_sync()
        first = await src.read()
        await src.close()
        return first
    assert asyncio.run(run()).index == 0


def _camera(source_type, url):
    return Camera("cam_1", "n", GeoPoint(0, 0), url, source_type, CameraStatus.UNKNOWN, FakeClock().now())


def test_factory_creates_without_connecting_and_checks_kind():
    f = CameraSourceFactory()
    src = f.create(_camera(CameraSourceType.RTSP, "rtsp://10.0.0.1/live"))
    assert isinstance(src, OpenCvCameraSource)  # no network happened
    assert isinstance(f.create(_camera(CameraSourceType.VIDEO_FILE, r"C:\clips\a.mp4")), OpenCvCameraSource)
    with pytest.raises(DomainValidationError):
        f.create(_camera(CameraSourceType.RTSP, r"C:\clips\a.mp4"))
