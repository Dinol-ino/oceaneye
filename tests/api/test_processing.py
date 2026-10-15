import base64
import io

from tests.conftest import ADMIN, LIFEGUARD, OPERATOR, SERVICE, event_body

VIDEO = ("beach.mp4", io.BytesIO(b"\x00\x00\x00\x18ftypmp42 fake video bytes"), "video/mp4")


def upload(client, name="beach.mp4"):
    r = client.post("/api/uploads", headers=OPERATOR, files={"file": (name, io.BytesIO(b"fake-mp4-bytes"), "video/mp4")})
    assert r.status_code == 201, r.text
    return r.json()


def test_upload_validation_and_listing(client):
    u = upload(client)
    assert u["id"].startswith("vid_") and u["size_bytes"] == 14
    assert client.post("/api/uploads", headers=OPERATOR, files={"file": ("x.exe", io.BytesIO(b"MZ"), "x")}).status_code == 422
    assert client.post("/api/uploads", headers=LIFEGUARD, files={"file": VIDEO}).status_code == 403
    assert [x["id"] for x in client.get("/api/uploads", headers=OPERATOR).json()] == [u["id"]]


def test_job_lifecycle_with_worker_callbacks(client, camera, launcher):
    u = upload(client)
    job = client.post("/api/analysis/jobs", headers=OPERATOR,
                      json={"upload_id": u["id"], "camera_id": camera["id"], "model": "yolov8s.pt", "imgsz": 960}).json()
    assert job["status"] == "queued" and launcher.running[f"job:{job['id']}"] == ["job", "--job-id", job["id"]]
    cfg = client.get(f"/api/processing/jobs/{job['id']}/worker-config", headers=SERVICE).json()
    assert cfg["source"].endswith(".mp4") and cfg["options"]["model"] == "yolov8s.pt" and cfg["zone"]["polygon"][0] == [0, 0.5]
    assert client.get(f"/api/processing/jobs/{job['id']}/worker-config", headers=OPERATOR).status_code == 403
    client.post(f"/api/processing/jobs/{job['id']}/report", headers=SERVICE, json={"status": "running", "progress": 0.5})
    assert client.get(f"/api/analysis/jobs/{job['id']}", headers=OPERATOR).json()["progress"] == 0.5
    launcher.stop(f"job:{job['id']}")
    done = client.post(f"/api/processing/jobs/{job['id']}/report", headers=SERVICE,
                       json={"status": "completed", "summary": {"pipeline_fps": 7.5, "frames_processed": 90}, "events_created": 2})
    assert done.json()["status"] == "completed"
    j = client.get(f"/api/analysis/jobs/{job['id']}", headers=OPERATOR).json()
    assert j["progress"] == 1 and j["events_created"] == 2 and j["video_url"] is None  # no overlay file written
    assert client.get(f"/api/analysis/jobs/{job['id']}/video", headers=OPERATOR).status_code == 404


def test_job_options_validated_and_crashed_worker_reported(client, camera, launcher):
    u = upload(client)
    bad = client.post("/api/analysis/jobs", headers=OPERATOR, json={"upload_id": u["id"], "camera_id": camera["id"], "model": "../evil.pt"})
    assert bad.status_code == 422
    job = client.post("/api/analysis/jobs", headers=OPERATOR, json={"upload_id": u["id"], "camera_id": camera["id"]}).json()
    launcher.crash(f"job:{job['id']}", 3)
    j = client.get(f"/api/analysis/jobs/{job['id']}", headers=OPERATOR).json()
    assert j["status"] == "failed" and "code 3" in j["error"]


def test_worker_limit_is_enforced(client, camera, launcher):
    launcher.max = 0
    u = upload(client)
    r = client.post("/api/analysis/jobs", headers=OPERATOR, json={"upload_id": u["id"], "camera_id": camera["id"]})
    assert r.status_code == 409 and "limit" in r.json()["error"]["message"]


def test_simulated_cctv_camera_monitoring_and_live_frames(client, launcher):
    u = upload(client)
    cam = client.post("/api/cameras", headers=OPERATOR, json={"name": "Sim CCTV", "lat": 12.8, "lon": 74.8, "video_upload_id": u["id"]}).json()
    assert cam["source_type"] == "video_file" and "stream_url" not in cam
    assert client.post("/api/cameras", headers=OPERATOR, json={"name": "x", "lat": 1, "lon": 1}).status_code == 422
    assert client.post("/api/cameras", headers=OPERATOR, json={"name": "x", "lat": 1, "lon": 1, "stream_url": "rtsp://h/x",
                                                               "source_type": "video_file"}).status_code == 422
    assert client.post(f"/api/cameras/{cam['id']}/monitoring/start", headers=OPERATOR).status_code == 202
    assert f"cam:{cam['id']}" in launcher.running
    cfg = client.get(f"/api/processing/cameras/{cam['id']}/worker-config", headers=SERVICE).json()
    assert cfg["loop"] is True and cfg["source"].endswith(".mp4")
    jpeg = base64.b64encode(b"\xff\xd8fakejpeg").decode()
    assert client.post(f"/api/processing/cameras/{cam['id']}/frame", headers=SERVICE,
                       json={"jpeg_b64": jpeg, "stats": {"people": 3, "fps": 6.1}}).status_code == 204
    live = {x["camera_id"]: x for x in client.get("/api/live/cameras", headers=LIFEGUARD).json()}[cam["id"]]
    assert live["online"] and live["monitoring"] and live["stats"]["people"] == 3
    f = client.get(f"/api/live/cameras/{cam['id']}/frame", headers=LIFEGUARD)
    assert f.status_code == 200 and f.content == b"\xff\xd8fakejpeg" and f.headers["content-type"] == "image/jpeg"
    client.post(f"/api/cameras/{cam['id']}/monitoring/stop", headers=OPERATOR)
    assert f"cam:{cam['id']}" not in launcher.running
    assert client.post(f"/api/processing/cameras/{cam['id']}/frame", headers=SERVICE, json={"jpeg_b64": "@@@"}).status_code == 422


def test_zone_editing_requires_normalised_points(client, camera):
    ok = client.put(f"/api/zones/{camera['id']}", headers=OPERATOR, json={"name": "Rip area", "polygon": [[0.1, 0.5], [0.9, 0.5], [0.5, 0.95]]})
    assert ok.status_code == 200 and ok.json()["name"] == "Rip area"
    assert client.put(f"/api/zones/{camera['id']}", headers=OPERATOR, json={"polygon": [[0, 0], [100, 0], [5, 50]]}).status_code == 422
    assert client.put(f"/api/zones/{camera['id']}", headers=LIFEGUARD, json={"polygon": [[0, 0], [1, 0], [1, 1]]}).status_code == 403


def test_metrics_demo_incident_and_public_config(client, camera, clock):
    cfg = client.get("/api/config/public", headers=LIFEGUARD).json()
    assert cfg["lat"] == 12.8406 and cfg["max_workers"] == 2
    demo = client.post("/api/demo/incident", headers=OPERATOR, json={"camera_id": camera["id"]}).json()
    assert demo["reason"].startswith("DEMO") and demo["distress_signals"] == []
    ev = client.post("/api/events", headers=SERVICE, json=event_body(camera["id"])).json()
    clock.advance(12)
    client.post(f"/api/events/{ev['id']}/ack", headers=LIFEGUARD)
    client.post(f"/api/events/{ev['id']}/outcome", headers=LIFEGUARD, json={"outcome": "false_alarm"})
    m = client.get("/api/metrics", headers=OPERATOR).json()
    assert m["events"]["total"] == 2 and m["events"]["demo_events"] == 1 and m["events"]["false_alarm_rate"] == 1.0
    assert m["response"]["time_to_ack"]["median_s"] == 12.0 and m["events"]["signals"] == {"vertical_bobbing": 1}


def test_places_and_weather_endpoints_with_mock_providers(client):
    """Both degrade to "nothing, and here is why" rather than failing the page."""
    body = client.get("/api/places/beaches-near?lat=12.8&lon=74.8", headers=OPERATOR).json()
    assert body["results"] == [] and body["available"] is False and body["error"]
    w = client.get("/api/weather?lat=12.8&lon=74.8", headers=SERVICE).json()
    assert w["status"] == "unavailable" and w["forecast"] == []


def test_web_ui_is_served(client):
    assert client.get("/", follow_redirects=False).status_code == 307
    for page in ("index", "control", "lifeguard", "analysis"):
        r = client.get(f"/ui/{page}.html")
        assert r.status_code == 200 and "OceanEye" in r.text
    assert client.get("/ui/js/api.js").status_code == 200


# ---- removing test material -----------------------------------------------------------------
# Analysis is how the pipeline is exercised, so failed runs and stale clips pile up faster than
# anything else. These routes exist so an operator can clear them without resetting the database.

def test_a_finished_job_can_be_removed(client, camera, launcher):
    u = upload(client)
    job = client.post("/api/analysis/jobs", headers=OPERATOR,
                      json={"upload_id": u["id"], "camera_id": camera["id"]}).json()
    launcher.stop(f"job:{job['id']}")
    client.post(f"/api/processing/jobs/{job['id']}/report", headers=SERVICE, json={"status": "failed"})
    assert client.delete(f"/api/analysis/jobs/{job['id']}", headers=OPERATOR).status_code == 204
    assert client.get(f"/api/analysis/jobs/{job['id']}", headers=OPERATOR).status_code == 404


def test_a_running_job_is_not_removed_by_accident(client, camera):
    """Killing a worker is a different decision from tidying up after one."""
    u = upload(client)
    job = client.post("/api/analysis/jobs", headers=OPERATOR,
                      json={"upload_id": u["id"], "camera_id": camera["id"]}).json()
    r = client.delete(f"/api/analysis/jobs/{job['id']}", headers=OPERATOR)
    assert r.status_code == 409
    assert client.get(f"/api/analysis/jobs/{job['id']}", headers=OPERATOR).status_code == 200


def test_clear_finished_removes_only_terminal_jobs(client, camera, launcher):
    u = upload(client)
    done = client.post("/api/analysis/jobs", headers=OPERATOR,
                       json={"upload_id": u["id"], "camera_id": camera["id"]}).json()
    launcher.stop(f"job:{done['id']}")
    client.post(f"/api/processing/jobs/{done['id']}/report", headers=SERVICE, json={"status": "completed"})
    running = client.post("/api/analysis/jobs", headers=OPERATOR,
                          json={"upload_id": u["id"], "camera_id": camera["id"]}).json()

    assert client.post("/api/analysis/jobs/clear-finished", headers=OPERATOR).json()["removed"] == 1
    left = [j["id"] for j in client.get("/api/analysis/jobs", headers=OPERATOR).json()]
    assert left == [running["id"]]


def test_an_unused_upload_can_be_deleted(client):
    u = upload(client)
    assert client.delete(f"/api/uploads/{u['id']}", headers=OPERATOR).status_code == 204
    assert client.get("/api/uploads", headers=OPERATOR).json() == []


def test_an_upload_feeding_a_camera_is_not_deleted(client):
    """Deleting the file under a live simulated feed turns a working camera into an unexplained
    read failure minutes later, far from the click that caused it."""
    u = upload(client)
    cam = client.post("/api/cameras", headers=OPERATOR,
                      json={"name": "Sim CCTV", "lat": 12.9, "lon": 74.8,
                            "video_upload_id": u["id"], "source_type": "video_file"})
    assert cam.status_code in (200, 201), cam.text
    r = client.delete(f"/api/uploads/{u['id']}", headers=OPERATOR)
    assert r.status_code == 409
    assert "Sim CCTV" in r.text


def test_an_upload_under_analysis_is_not_deleted(client, camera):
    u = upload(client)
    client.post("/api/analysis/jobs", headers=OPERATOR,
                json={"upload_id": u["id"], "camera_id": camera["id"]})
    assert client.delete(f"/api/uploads/{u['id']}", headers=OPERATOR).status_code == 409


def test_a_lifeguard_cannot_remove_test_material(client, camera, launcher):
    """Removal is a management action: the lifeguard app is read-and-acknowledge only."""
    u = upload(client)
    assert client.delete(f"/api/uploads/{u['id']}", headers=LIFEGUARD).status_code == 403
    assert client.post("/api/analysis/jobs/clear-finished", headers=LIFEGUARD).status_code == 403


def test_an_uploaded_clip_camera_is_stored_as_a_file_not_a_stream(client):
    """Regression: the UI could create a camera whose stream_url was a local path but whose
    source_type was the schema default (rtsp). The worker then never looped or opened it, and the
    camera sat 'offline' with nothing explaining why."""
    u = upload(client)
    cam = client.post("/api/cameras", headers=OPERATOR,
                      json={"name": "Sim feed", "lat": 12.9, "lon": 74.8,
                            "video_upload_id": u["id"]}).json()   # no source_type sent at all
    assert cam["source_type"] == "video_file"
