from datetime import datetime, timedelta, timezone

import pytest

np = pytest.importorskip("numpy")

from app.core.domain.value_objects import BoundingBox  # noqa: E402
from app.vision.config import TrackerConfig  # noqa: E402
from app.vision.detection.base import Detection  # noqa: E402
from app.vision.tracking.bytetrack import ByteTrackTracker  # noqa: E402

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def det(cam, x, y, conf=0.9, w=40, h=100):
    return Detection(cam, "person", conf, BoundingBox(x, y, x + w, y + h), T0)


class FakeBackend:
    """Stands in for BYTETracker: echoes each detection as a track with a fixed raw id."""
    def __init__(self, *_): self.calls = 0
    def update(self, batch, img):
        self.calls += 1
        rows = [[*(batch.xywh[i][0] - batch.xywh[i][2] / 2, batch.xywh[i][1] - batch.xywh[i][3] / 2,
                   batch.xywh[i][0] + batch.xywh[i][2] / 2, batch.xywh[i][1] + batch.xywh[i][3] / 2),
                 100 + i, batch.conf[i], batch.cls[i], i] for i in range(len(batch))]
        return np.array(rows, dtype=np.float32).reshape(-1, 8)


def test_wrapper_ids_history_and_per_camera_numbering():
    tr = ByteTrackTracker(backend_factory=lambda c, f: FakeBackend())
    a = tr.update("camA", [det("camA", 10, 10)], T0)
    b = tr.update("camB", [det("camB", 50, 50)], T0)
    assert a[0].track_id == "camA-T1" and b[0].track_id == "camB-T1"  # sequential per camera
    a2 = tr.update("camA", [det("camA", 14, 10)], T0 + timedelta(seconds=1))
    assert len(a2[0].history) == 2 and a2[0].current_position[0] > a[0].current_position[0]
    assert tr.update("camA", [], T0) == []  # empty frames are passed through, no crash
    tr.reset("camA")
    assert tr.update("camA", [det("camA", 10, 10)], T0)[0].track_id == "camA-T1"


def test_history_is_bounded():
    tr = ByteTrackTracker(TrackerConfig(history_len=5), backend_factory=lambda c, f: FakeBackend())
    for i in range(20):
        out = tr.update("c", [det("c", i, 0)], T0)
    assert len(out[0].history) == 5


def test_real_bytetrack_keeps_identity_for_moving_people_and_ids_do_not_swap():
    pytest.importorskip("ultralytics")
    tr = ByteTrackTracker(frame_rate=15.0)
    ids = {"left": set(), "right": set()}
    for i in range(30):
        out = tr.update("cam", [det("cam", 50 + 3 * i, 100), det("cam", 400 - 3 * i, 120)], T0 + timedelta(seconds=i / 15))
        for t in out:
            ids["left" if t.current_position[0] < 225 else "right"].add(t.track_id)
    assert len(ids["left"]) == 1 and len(ids["right"]) == 1 and ids["left"] != ids["right"]


def test_real_bytetrack_survives_short_occlusion():
    pytest.importorskip("ultralytics")
    tr = ByteTrackTracker(frame_rate=15.0)
    seen = set()
    for i in range(40):
        dets = [] if 15 <= i < 20 else [det("cam", 100 + 2 * i, 100)]  # 5 missed frames
        seen.update(t.track_id for t in tr.update("cam", dets, T0 + timedelta(seconds=i / 15)))
    assert len(seen) == 1
