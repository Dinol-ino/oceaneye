import json
from datetime import datetime, timezone

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from app.core.domain.value_objects import BoundingBox  # noqa: E402
from app.vision.config import OverlayConfig, PerceptionConfig  # noqa: E402
from app.vision.detection.base import Detection  # noqa: E402
from app.vision.detection.mock import MockDetector  # noqa: E402
from app.vision.pipeline.default import DefaultVisionPipeline  # noqa: E402
from app.vision.runner import PerceptionRunner  # noqa: E402
from app.vision.tracking.base import Track, Tracker  # noqa: E402
from app.vision.visualization.overlay import draw_tracks, track_color  # noqa: E402
from tests.unit.test_opencv_source import make_video  # noqa: E402

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _track(tid="cam_01-T1", n=5):
    hist = tuple(Detection("cam_01", "person", 0.8, BoundingBox(10 + 4 * i, 10, 30 + 4 * i, 40), NOW) for i in range(n))
    return Track(tid, "cam_01", hist)


class OneTrackPerFrame(Tracker):
    """Test tracker: always reports one growing track (no ML)."""
    def __init__(self): self.hist = []
    def update(self, camera_id, detections, timestamp):
        self.hist.append(Detection(camera_id, "person", 0.7, BoundingBox(5 + len(self.hist), 5, 25, 40), timestamp))
        return [Track(f"{camera_id}-T1", camera_id, tuple(self.hist))]
    def reset(self, camera_id): self.hist.clear()


def test_overlay_returns_annotated_copy_and_stable_colors():
    img = np.zeros((100, 120, 3), dtype=np.uint8)
    out = draw_tracks(img, [_track()], OverlayConfig(), frame_index=3, timestamp_s=0.2, camera_id="cam_01")
    assert out is not img and img.sum() == 0 and out.sum() > 0
    assert track_color("cam_01-T1") == track_color("cam_01-T1") != track_color("cam_01-T2")
    assert draw_tracks(img, [], OverlayConfig(show_hud=False)).sum() == 0


def test_runner_writes_video_tracks_and_summary(tmp_path):
    video = make_video(tmp_path / "in put.mp4", frames=10, size=(64, 48), fps=10)
    cfg = PerceptionConfig(output_dir=str(tmp_path / "out"))
    runner = PerceptionRunner(cfg, pipeline_factory=lambda fps: DefaultVisionPipeline(MockDetector(), OneTrackPerFrame()))
    s = runner.run(str(video))
    assert s.frames_processed == 10 and s.unique_track_ids == 1 and s.max_concurrent_tracks == 1
    assert s.source_fps == 10 and s.width == 64
    lines = [json.loads(x) for x in open(s.outputs["tracks_jsonl"], encoding="utf-8")]
    assert len(lines) == 10 and lines[0]["v"] == 1 and lines[3]["tracks"][0]["track_id"] == "cam_01-T1"
    assert lines[5]["video_time_s"] == pytest.approx(0.5)
    cap = cv2.VideoCapture(s.outputs["overlay_video"])
    assert cap.isOpened() and int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == 10
    assert json.load(open(s.outputs["summary_json"], encoding="utf-8"))["frames_processed"] == 10


def test_runner_stride_max_frames_and_callback(tmp_path):
    video = make_video(tmp_path / "v.mp4", frames=20)
    seen = []
    cfg = PerceptionConfig(output_dir=str(tmp_path / "o"), stride=2, max_frames=4, save_video=False)
    s = PerceptionRunner(cfg, lambda fps: DefaultVisionPipeline(MockDetector(), OneTrackPerFrame()),
                         on_frame=lambda f, r, a: seen.append(f.index)).run(str(video))
    assert s.frames_processed == 4 and seen == [0, 2, 4, 6] and s.effective_fps == 5 and "overlay_video" not in s.outputs
