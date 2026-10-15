import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")
pytest.importorskip("imageio_ffmpeg")

from app.core.domain.value_objects import BoundingBox  # noqa: E402
from app.evidence.local import LocalEvidenceStorage  # noqa: E402
from app.vision.detection.base import Detection, Detector  # noqa: E402
from app.vision.pipeline.default import DefaultVisionPipeline  # noqa: E402
from app.vision.tracking.base import Track, Tracker  # noqa: E402
from app.worker.offline import OfflineClient  # noqa: E402
from app.worker.session import MonitoringSession, SessionConfig  # noqa: E402
from tests.unit.test_opencv_source import make_video  # noqa: E402

WHOLE_FRAME = [[0, 0], [1, 0], [1, 1], [0, 1]]


class StillPerson(Detector):
    def detect(self, frame):
        h, w = frame.image.shape[:2]
        # A box scaled to the frame, so the behaviour rules see the same motion at any resolution.
        return [Detection(frame.camera_id, "person", 0.9,
                          BoundingBox(0.3 * w, 0.5 * h, 0.6 * w, 0.95 * h), frame.captured_at)]


class OneTrack(Tracker):
    def __init__(self): self.hist = []
    def update(self, camera_id, detections, timestamp):
        self.hist += detections
        return [Track(f"{camera_id}-T1", camera_id, tuple(self.hist[-150:]))] if detections else []
    def reset(self, camera_id): self.hist.clear()


def session(tmp_path, zone, *, sensitivity="high", frames=120, size=(160, 120), fps=10, mode="job",
            loop=False, max_frames=None, clip_max_width=0):
    video = make_video(tmp_path / "v.mp4", frames=frames, size=size, fps=fps)
    cfg = SessionConfig(mode=mode, camera_id="cam_t", camera_name="test", lat=1, lon=2, source=str(video),
                        zone_polygon=zone, zone_name="water" if zone else None, target_fps=fps,
                        sensitivity=sensitivity, job_id="job_t", loop=loop, max_frames=max_frames,
                        clip_max_width=clip_max_width, device="cpu", model="yolov8n.pt", imgsz=640,
                        output_dir=str(tmp_path / "out") if mode == "job" else None)
    client = OfflineClient()
    store = LocalEvidenceStorage(tmp_path / "evidence")
    s = MonitoringSession(cfg, client, store, sleep=lambda _: None,
                          pipeline_factory=lambda c, f: DefaultVisionPipeline(StillPerson(), OneTrack()))
    return s, client, store


def run(tmp_path, zone, **kw):
    s, client, store = session(tmp_path, zone, **kw)
    return s.run(), client, store, tmp_path


def test_still_person_in_zone_raises_event_with_evidence(tmp_path):
    summary, client, store, tmp = run(tmp_path, WHOLE_FRAME)
    assert summary["frames_processed"] == 120 and summary["events_created"] >= 1
    ev = client.events[0]
    assert ev["distress_signals"] == ["prolonged_stillness"] and ev["track_id"] == "cam_t-T1"
    assert "inside danger zone" in ev["reason"] and ev["location"]["zone_name"] == "water"
    assert store.exists(ev["evidence"]["thumbnail_key"]) and store.exists(ev["evidence"]["clip_key"])
    assert (tmp / "out" / "overlay.mp4").stat().st_size > 0
    assert (tmp / "out" / "tracks.jsonl").read_text().count("\n") == 120


def test_same_person_outside_zone_raises_nothing(tmp_path):
    summary, client, *_ = run(tmp_path, [[0, 0], [1, 0], [1, 0.2], [0, 0.2]])
    assert summary["events_created"] == 0 and client.events == []


def test_summary_reports_the_resolved_profile_not_the_word_auto(tmp_path):
    """The dashboard shows what actually ran, so 'auto' must be resolved before the first frame."""
    s, *_ = session(tmp_path, None, frames=12)
    s.cfg.model, s.cfg.imgsz, s.cfg.target_fps = "auto", 0, 0.0
    summary = s.run()
    assert summary["model"] != "auto" and summary["imgsz"] > 0 and summary["target_fps"] > 0
    assert summary["device"] in ("cpu", "mps") or summary["device"].startswith("cuda")
    assert summary["profile"] and "throughput_fps" in summary and "warmup_s" in summary


def test_evidence_clip_frames_are_downscaled(tmp_path):
    """Regression: full-resolution frames in the evidence ring buffer exhausted this machine's
    memory mid-demo (two workers, 1080p, OpenCV 'Insufficient memory'). Clips are stored small;
    the thumbnail still comes from the full-resolution frame."""
    s, client, _store = session(tmp_path, WHOLE_FRAME, frames=90, size=(1280, 720), clip_max_width=320)
    s.run()
    assert client.events, "expected a candidate event to produce a clip"
    clip = tmp_path / "evidence" / client.events[0]["evidence"]["clip_key"]
    cap = cv2.VideoCapture(str(clip))
    try:
        assert cap.isOpened()
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    finally:
        cap.release()
    assert 0 < width <= 320, f"clip stored at {width}px; the ring buffer was not downscaled"


def test_cooldown_survives_a_looping_source(tmp_path):
    """Regression: a simulated CCTV camera replays the same clip forever. Rebuilding the risk engine
    on each lap reset its per-track cooldown, so the same swimmer alerted once per lap."""
    s, client, _ = session(tmp_path, WHOLE_FRAME, frames=60, mode="camera", loop=True, max_frames=240)
    summary = s.run()
    assert summary["laps"] >= 2, "the test must actually replay the source"
    assert len(client.events) == 1, f"cooldown did not survive {summary['laps']} laps"


def test_perception_state_objects_are_not_rebuilt_per_lap(tmp_path):
    s, *_ = session(tmp_path, WHOLE_FRAME, frames=30, mode="camera", loop=True, max_frames=90)
    engine, analyzer, gate = s._engine, s._analyzer, s._gate
    s.run()
    assert (s._engine, s._analyzer, s._gate) == (engine, analyzer, gate)
