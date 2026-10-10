from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.core.interfaces.clock import Clock
from app.main.factory import create_app


class FakeClock(Clock):
    def __init__(self) -> None:
        self._now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


def hdr(role: str, user: str = "tester") -> dict[str, str]:
    return {"X-Dev-Role": role, "X-Dev-User": user}


ADMIN, OPERATOR, LIFEGUARD, SERVICE = (hdr("administrator"), hdr("operator"), hdr("lifeguard"), hdr("service"))


class FakeLauncher:
    """Records worker starts instead of spawning processes."""

    def __init__(self):
        self.running: dict[str, list[str]] = {}
        self.exit_codes: dict[str, int] = {}
        self.max = 2

    def start(self, key, args):
        from app.core.exceptions import ConflictError
        if key in self.running:
            raise ConflictError(f"worker '{key}' is already running")
        if len(self.running) >= self.max:
            raise ConflictError("worker limit reached")
        self.running[key] = args

    def stop(self, key):
        self.running.pop(key, None)

    def is_running(self, key):
        return key in self.running

    def exit_code(self, key):
        return self.exit_codes.get(key)

    def stop_all(self):
        self.running.clear()

    def log_path(self, key):
        return f"logs/{key}.log"

    def crash(self, key, code=1):
        self.running.pop(key, None)
        self.exit_codes[key] = code


@pytest.fixture
def launcher() -> FakeLauncher:
    return FakeLauncher()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def settings(tmp_path) -> Settings:
    # max_workers is pinned: it is auto-sized from the host's memory in production, and the suite must
    # not change behaviour depending on the machine it runs on.
    return Settings(
        _env_file=None, environment="test", database_url="sqlite://", evidence_dir=tmp_path / "evidence",
        escalation_monitor_enabled=False, ack_timeout_seconds=30, weather_provider="mock",
        places_provider="mock", upload_dir=tmp_path / "uploads", jobs_dir=tmp_path / "jobs",
        logs_dir=tmp_path / "logs", max_workers=2,
    )


@pytest.fixture
def app(settings, clock, launcher):
    return create_app(settings, clock, launcher)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def beach(client) -> dict:
    """The beach seeded from settings on startup - this installation's deployment site."""
    r = client.get("/api/beaches/active", headers=OPERATOR)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def camera(client) -> dict:
    r = client.post("/api/cameras", headers=ADMIN, json={
        "name": "MOCK test camera", "lat": 12.84, "lon": 74.80, "stream_url": "rtsp://192.168.1.20:8080/live",
        "source_type": "rtsp", "zone_polygon": [[0, 0.5], [1, 0.5], [1, 1]],
    })
    assert r.status_code == 201, r.text
    return r.json()


def event_body(camera_id: str, **over) -> dict:
    body = {"camera_id": camera_id, "track_id": "C01-T17", "risk_score": 0.5,
            "distress_signals": ["vertical_bobbing"], "reason": "MOCK/DEMO test fixture, not model output"}
    body.update(over)
    return body


@pytest.fixture
def event(client, camera) -> dict:
    r = client.post("/api/events", headers=SERVICE, json=event_body(camera["id"]))
    assert r.status_code == 201, r.text
    return r.json()
