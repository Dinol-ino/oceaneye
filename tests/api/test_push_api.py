"""Push subscription endpoints, including the behaviour when background push is switched off."""
from __future__ import annotations

import pytest

from app.config.settings import Settings
from app.main.factory import create_app
from fastapi.testclient import TestClient
from tests.conftest import ADMIN, LIFEGUARD, OPERATOR

SUB = {"endpoint": "https://push.example.com/send/abc123", "keys": {"p256dh": "p" * 24, "auth": "a" * 16},
       "label": "Lifeguard Ravi - Tower 2"}


@pytest.fixture
def push_client(tmp_path, clock, launcher):
    """An app with background push enabled, so the subscribe path can be exercised."""
    settings = Settings(
        _env_file=None, environment="test", database_url="sqlite://", evidence_dir=tmp_path / "evidence",
        escalation_monitor_enabled=False, weather_provider="mock", beaches_provider="mock",
        upload_dir=tmp_path / "up", jobs_dir=tmp_path / "jobs", logs_dir=tmp_path / "logs", max_workers=2,
        notification_channels=["websocket", "web_push"],
        vapid_public_key="BPublicKeyForTests", vapid_private_key="private-key-for-tests",
    )
    with TestClient(create_app(settings, clock, launcher)) as c:
        yield c


def test_push_is_advertised_as_unavailable_when_not_configured(client):
    """The lifeguard app asks before offering a button that cannot work."""
    assert client.get("/api/push/public-key", headers=LIFEGUARD).status_code == 404
    assert client.get("/api/config/public", headers=LIFEGUARD).json()["capabilities"]["web_push"] is False
    # 501, not 500: an installation without push is not a broken installation.
    assert client.post("/api/push/subscribe", headers=LIFEGUARD, json=SUB).status_code == 501


def test_public_key_is_served_when_configured(push_client):
    body = push_client.get("/api/push/public-key", headers=LIFEGUARD).json()
    assert body["public_key"] == "BPublicKeyForTests" and body["subject"].startswith("mailto:")
    assert push_client.get("/api/config/public", headers=LIFEGUARD).json()["capabilities"]["web_push"] is True


def test_subscribe_then_list_never_exposes_the_endpoint_url(push_client):
    created = push_client.post("/api/push/subscribe", headers=LIFEGUARD, json=SUB)
    assert created.status_code == 201
    body = created.json()
    assert body["role"] == "lifeguard" and body["label"] == SUB["label"]
    assert SUB["endpoint"] not in created.text

    devices = push_client.get("/api/push/devices", headers=ADMIN)
    assert devices.status_code == 200 and len(devices.json()) == 1
    assert SUB["endpoint"] not in devices.text and "push.example.com" not in devices.text


def test_resubscribing_the_same_browser_does_not_duplicate_it(push_client):
    push_client.post("/api/push/subscribe", headers=LIFEGUARD, json=SUB)
    push_client.post("/api/push/subscribe", headers=LIFEGUARD, json={**SUB, "label": "Tower 3"})
    devices = push_client.get("/api/push/devices", headers=ADMIN).json()
    assert len(devices) == 1 and devices[0]["label"] == "Tower 3"


def test_unsubscribe_removes_the_device(push_client):
    push_client.post("/api/push/subscribe", headers=LIFEGUARD, json=SUB)
    assert push_client.post("/api/push/unsubscribe", headers=LIFEGUARD, json=SUB).status_code == 204
    assert push_client.get("/api/push/devices", headers=ADMIN).json() == []


def test_device_list_is_readable_by_responders_but_not_by_services(push_client):
    """An operator about to rely on phone alerts must be able to see a phone is registered.
    A hash and a label reveal nothing, so this is widened to responders deliberately."""
    assert push_client.get("/api/push/devices", headers=LIFEGUARD).status_code == 200
    assert push_client.get("/api/push/devices", headers=OPERATOR).status_code == 200
    assert push_client.get("/api/push/devices", headers={"X-Dev-Role": "service"}).status_code == 403
    assert push_client.get("/api/push/devices").status_code == 401


def test_only_https_endpoints_are_accepted(push_client):
    bad = push_client.post("/api/push/subscribe", headers=LIFEGUARD,
                           json={**SUB, "endpoint": "http://push.example.com/send/abc"})
    assert bad.status_code == 422


def test_subscribing_requires_a_responder_role(push_client):
    assert push_client.post("/api/push/subscribe", headers={"X-Dev-Role": "service"}, json=SUB).status_code == 403
    assert push_client.post("/api/push/subscribe", json=SUB).status_code == 401


def test_enabling_push_without_keys_is_refused_at_startup(tmp_path):
    """A silent 'push enabled but never delivers' is worse than refusing to start."""
    with pytest.raises(ValueError, match="VAPID"):
        Settings(_env_file=None, environment="test", database_url="sqlite://",
                 evidence_dir=tmp_path / "e", notification_channels=["websocket", "web_push"])
