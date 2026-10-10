from tests.conftest import ADMIN, LIFEGUARD, OPERATOR, SERVICE, hdr


def test_unauthenticated_is_401(client):
    r = client.get("/api/cameras")
    assert r.status_code == 401 and r.json()["error"]["code"] == "authentication_required"


def test_invalid_role_is_401(client):
    assert client.get("/api/cameras", headers=hdr("root")).status_code == 401


def test_role_enforcement(client):
    body = {"name": "x", "lat": 1, "lon": 1, "stream_url": "rtsp://h/x"}
    assert client.post("/api/cameras", headers=LIFEGUARD, json=body).status_code == 403
    assert client.post("/api/cameras", headers=OPERATOR, json=body).status_code == 201  # control-room in-charge
    assert client.post("/api/cameras", headers=ADMIN, json=body).status_code == 201
    assert client.post("/api/events", headers=LIFEGUARD, json={}).status_code == 403


def test_query_credentials_ignored_on_http(client):
    assert client.get("/api/cameras?dev_role=administrator").status_code == 401


def test_security_headers(client):
    assert client.get("/health").headers["x-content-type-options"] == "nosniff"


def test_production_refuses_dev_auth():
    import pytest
    from app.config.settings import Settings
    with pytest.raises(ValueError):
        Settings(_env_file=None, environment="production", auth_mode="dev", secret_key="x")
