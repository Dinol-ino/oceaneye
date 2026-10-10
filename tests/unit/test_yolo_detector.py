from datetime import datetime, timezone

import pytest

np = pytest.importorskip("numpy")

from app.core.domain.frame import Frame  # noqa: E402
from app.vision.config import DetectorConfig  # noqa: E402
from app.vision.detection import yolo as yolo_module  # noqa: E402
from app.vision.detection.yolo import (  # noqa: E402
    YoloDetector,
    detections_from_arrays,
    half_precision_keyword,
    resolve_weights,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
FRAME = Frame("cam_1", NOW, 0, image=np.zeros((48, 64, 3), dtype=np.uint8))


class _T:  # mimics torch.Tensor .cpu().numpy()
    def __init__(self, a): self.a = np.array(a, dtype=np.float32)
    def cpu(self): return self
    def numpy(self): return self.a


class _Boxes:
    def __init__(self, xyxy, conf, cls):
        self.xyxy, self.conf, self.cls = _T(xyxy), _T(conf), _T(cls)
    def __len__(self): return len(self.conf.a)


class FakeModel:
    def __init__(self, boxes): self.boxes, self.calls = boxes, []
    def predict(self, **kw):
        self.calls.append(kw)
        return [type("R", (), {"boxes": self.boxes, "names": {0: "person"}})()]


def test_conversion_maps_arrays_to_domain_detections():
    dets = detections_from_arrays(FRAME, np.array([[10, 20, 30, 60]], np.float32), np.array([0.9], np.float32),
                                  np.array([0], np.float32), {0: "person"})
    assert dets[0].class_name == "person" and dets[0].bbox.center == (20.0, 40.0)
    assert dets[0].camera_id == "cam_1" and dets[0].timestamp == NOW and dets[0].confidence == pytest.approx(0.9)


def test_detector_calls_model_with_config_and_never_passes_half_on_cpu():
    model = FakeModel(_Boxes([[1, 2, 3, 4]], [0.5], [0]))
    det = YoloDetector(DetectorConfig(device="cpu", imgsz=640, conf=0.2), model=model)
    out = det.detect(FRAME)
    kw = model.calls[0]
    assert len(out) == 1 and kw["imgsz"] == 640 and kw["conf"] == 0.2 and kw["classes"] == [0]
    assert kw["device"] == "cpu" and "half" not in kw and "quantize" not in kw


def test_detector_empty_and_missing_image():
    det = YoloDetector(DetectorConfig(device="cpu"), model=FakeModel(_Boxes(np.zeros((0, 4)), [], [])))
    assert det.detect(FRAME) == []
    assert det.detect(Frame("c", NOW, 0, image=None)) == []


def test_the_fp16_keyword_is_resolved_once_not_per_frame(monkeypatch):
    """Resolving it per frame is what produced thousands of deprecation lines in the worker logs."""
    monkeypatch.setattr(yolo_module, "resolve_device", lambda _: "cuda:0")
    resolutions = []
    monkeypatch.setattr(yolo_module, "half_precision_keyword",
                        lambda: resolutions.append(1) or "quantize")
    model = FakeModel(_Boxes([[1, 2, 3, 4]], [0.5], [0]))
    det = YoloDetector(DetectorConfig(device="cuda:0"), model=model)
    for _ in range(5):
        det.detect(FRAME)
    assert len(resolutions) == 1
    assert all(call["quantize"] is True for call in model.calls)


def test_half_precision_uses_the_keyword_the_installed_ultralytics_accepts(monkeypatch):
    """Ultralytics renamed ``half`` to ``quantize``; passing the wrong one warns on every frame."""
    monkeypatch.setattr(yolo_module, "resolve_device", lambda _: "cuda:0")
    model = FakeModel(_Boxes([[1, 2, 3, 4]], [0.5], [0]))
    YoloDetector(DetectorConfig(device="cuda:0"), model=model).detect(FRAME)
    keyword = half_precision_keyword()
    assert keyword is None or model.calls[0][keyword] is True


def test_requested_cuda_falls_back_to_cpu_when_unavailable(monkeypatch):
    """An explicit cuda:0 on a machine without CUDA degrades instead of failing inside Ultralytics."""
    monkeypatch.setattr(yolo_module, "resolve_device", lambda requested: "cpu")
    det = YoloDetector(DetectorConfig(device="cuda:0"), model=FakeModel(_Boxes([[1, 2, 3, 4]], [0.5], [0])))
    assert det.device == "cpu"


def test_warmup_is_paid_once_and_never_raises():
    model = FakeModel(_Boxes(np.zeros((0, 4)), [], []))
    det = YoloDetector(DetectorConfig(device="cpu"), model=model)
    det.warmup()
    det.warmup()
    assert len(model.calls) == 1  # second call is a no-op


def test_warmup_failure_is_swallowed():
    class Broken(FakeModel):
        def predict(self, **kw):
            raise RuntimeError("no model")
    det = YoloDetector(DetectorConfig(device="cpu"), model=Broken(None))
    assert det.warmup() == 0.0  # a failed warm-up is not fatal; the first real frame reports it


@pytest.mark.parametrize("name,expected", [
    ("yolov8n.pt", "models"),                       # bare name -> weights dir
    (r"C:\models\custom.pt", r"C:\models\custom.pt"),  # explicit Windows path untouched
    ("weights/best.pt", "weights/best.pt"),
])
def test_resolve_weights(tmp_path, monkeypatch, name, expected):
    monkeypatch.chdir(tmp_path)
    out = resolve_weights(name, "models")
    assert (expected in out) if expected == "models" else out == expected
