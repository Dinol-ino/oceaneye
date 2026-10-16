"""Wiring and alert-path checks. ``defect`` tests are red today (see tests/hardening/conftest.py)."""
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests.conftest import LIFEGUARD, OPERATOR, SERVICE, event_body

ROOT = Path(__file__).resolve().parents[2]


# ----------------------------------------------------------------------------- defects (red)
@pytest.mark.defect
def test_D6_live_worker_can_turn_pose_on():
    """Pose carries the two highest-weighted signals (vertical_in_water 0.55, arms_raised 0.45) and is
    the only thing that separates a swimmer from a victim. app/worker/session.py::default_pipeline
    builds DefaultVisionPipeline(detector, tracker) with NO pose estimator and SessionConfig has no
    pose option, so in the product path (jobs AND cameras) those signals are unreachable.
    Only scripts/evaluate_detection.py can turn pose on."""
    from app.worker.session import SessionConfig, default_pipeline

    assert "pose" in SessionConfig.__dataclass_fields__, "SessionConfig has no pose switch"
    cfg = SessionConfig(mode="job", camera_id="c", camera_name="c", lat=0, lon=0, source="x.mp4",
                        device="cpu", model="yolov8n.pt", imgsz=640)
    cfg.pose = True
    assert default_pipeline(cfg, 6.0)._pose is not None


@pytest.mark.defect
def test_D7_job_events_are_not_dated_in_the_future(tmp_path):
    """Frame time for a file = processing-start + video time. A 5 min clip analysed in 1 min raises
    its last event ~4 min ahead of the wall clock, so the lifeguard sees an incident that 'happens' in
    the future and ack deadlines/outcome metrics are skewed."""
    pytest.importorskip("cv2")
    pytest.importorskip("imageio_ffmpeg")
    from tests.unit.test_worker_session import WHOLE_FRAME, session

    s, client, _ = session(tmp_path, WHOLE_FRAME, frames=150, fps=10)
    s.run()
    assert client.events, "need an event to inspect"
    started = datetime.fromisoformat(client.events[0]["started_at"])
    skew = (started - datetime.now(timezone.utc)).total_seconds()
    assert skew <= 1.0, f"event started_at is {skew:.1f}s in the future"


@pytest.mark.defect
def test_D8_evaluation_uses_the_same_zone_anchor_as_the_live_gate():
    """Live gate: bottom-centre of the box (PolygonZoneGate). evaluate_detection.py: box centre.
    Recall/false-alarm numbers from the script therefore do not describe live behaviour near the
    zone edge - which is exactly where a wading person sits."""
    src = (ROOT / "scripts" / "evaluate_detection.py").read_text(encoding="utf-8")
    assert not re.search(r"_point_in_polygon\(\s*cx\s*/\s*w\s*,\s*cy\s*/\s*h", src), \
        "evaluate_clip tests the box centre; the live gate tests the bottom edge"


@pytest.mark.defect
def test_D9_event_flood_is_capped_server_side(client, camera):
    """The cap (3 events/min/camera) lives only in the worker's risk engine. An ID switch storm, a
    second producer or a replayed POST sends one push per event to every lifeguard phone. Alert
    fatigue is a safety failure: expect the API to coalesce repeats for one camera+track."""
    for _ in range(8):
        r = client.post("/api/events", headers=SERVICE, json=event_body(camera["id"], track_id="C01-T17"))
        assert r.status_code == 201
    alerts = client.get("/api/alerts", headers=LIFEGUARD).json()
    assert len(alerts) <= 3, f"{len(alerts)} alerts for 8 identical events"


# ----------------------------------------------------------------------------- guards (green)
def test_G6_lifeguard_cannot_raise_events(client, camera):
    r = client.post("/api/events", headers=LIFEGUARD, json=event_body(camera["id"]))
    assert r.status_code in (401, 403)


def test_G7_alert_carries_ack_deadline_and_evidence_links(client, camera):
    client.post("/api/events", headers=SERVICE, json=event_body(camera["id"]))
    alert = client.get("/api/alerts", headers=LIFEGUARD).json()[0]
    assert alert["ack_deadline"]
    body = str(alert)
    assert "camera" in body or camera["id"] in body


def test_G8_ack_then_outcome_closes_the_loop(client, event):
    eid = event["id"]
    assert client.post(f"/api/events/{eid}/ack", headers=LIFEGUARD, json={}).status_code == 200
    r = client.post(f"/api/events/{eid}/outcome", headers=LIFEGUARD, json={"outcome": "false_alarm"})
    assert r.status_code == 200 and r.json()["status"] == "false_alarm"


def test_G9_evidence_requires_a_role(client, event):
    url = f"/api/evidence/{event['id']}/thumbnail"
    assert client.get(url).status_code in (401, 403)


def test_G10_upload_rejects_wrong_type_and_empty_file(client):
    bad = client.post("/api/uploads", headers=OPERATOR, files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    empty = client.post("/api/uploads", headers=OPERATOR, files={"file": ("x.mp4", b"", "video/mp4")})
    assert bad.status_code in (400, 422) and empty.status_code in (400, 422)


def test_G11_upload_filename_cannot_escape_upload_dir(client):
    r = client.post("/api/uploads", headers=OPERATOR,
                    files={"file": ("../../evil.mp4", b"\x00\x00\x00\x18ftypmp42", "video/mp4")})
    if r.status_code in (200, 201):
        assert ".." not in r.text.replace("../../evil.mp4", "")
