from tests.conftest import ADMIN, LIFEGUARD, OPERATOR


def test_register_and_list_hides_stream_url(client, camera):
    assert camera["id"].startswith("cam_") and camera["status"] == "unknown"
    assert "stream_url" not in camera
    listed = client.get("/api/cameras", headers=OPERATOR).json()
    assert [c["id"] for c in listed] == [camera["id"]]
    assert "stream_url" not in listed[0] and "rtsp://" not in str(listed)


def test_rejects_bad_stream_scheme(client):
    r = client.post("/api/cameras", headers=ADMIN,
                    json={"name": "x", "lat": 1, "lon": 1, "stream_url": "file:///etc/passwd"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "request_validation_error"
    assert "file:///etc/passwd" not in r.text  # submitted value is not echoed


def test_zone_endpoint(client, camera):
    z = client.get(f"/api/zones/{camera['id']}", headers=LIFEGUARD).json()
    assert z["mode"] == "static" and len(z["polygon"]) == 3


def test_zone_not_found(client):
    assert client.get("/api/zones/cam_missing", headers=OPERATOR).status_code == 404


def test_weather_is_mock(client):
    r = client.get("/api/weather?lat=12.8&lon=74.8", headers=OPERATOR).json()
    assert r["source"] == "mock" and r["wind_speed_ms"] is None and "MOCK" in r["note"]
