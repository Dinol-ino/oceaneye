"""Repository contract: the SAME tests run against SQLite and the in-memory adapter,
which is what makes a future PostgreSQL adapter a drop-in."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.domain.value_objects import GeoPoint, Polygon
from app.core.entities.alert import Alert, DeliveryRecord
from app.core.entities.camera import Camera
from app.core.entities.event import Event, EventLocation, EvidenceRef
from app.core.entities.zone import Zone
from app.core.enums import (CameraSourceType, CameraStatus, DeliveryStatus, DistressSignalType, EventStatus,
                            NotificationChannel, RiskLevel, ZoneMode)
from app.core.interfaces.repositories import EventFilter
from app.persistence.database import Database
from app.persistence.repositories import in_memory as mem
from app.persistence.repositories import sqlalchemy_repos as sql

T0 = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


@pytest.fixture(params=["sqlite", "memory"])
def repos(request):
    if request.param == "memory":
        return mem.InMemoryCameraRepository(), mem.InMemoryZoneRepository(), \
            mem.InMemoryEventRepository(), mem.InMemoryAlertRepository()
    db = Database("sqlite://")
    db.create_schema()
    sf = db.session_factory
    return sql.SqlCameraRepository(sf), sql.SqlZoneRepository(sf), sql.SqlEventRepository(sf), sql.SqlAlertRepository(sf)


def _camera(i=1) -> Camera:
    return Camera(f"cam_{i}", "c", GeoPoint(1, 2), "rtsp://h/x", CameraSourceType.RTSP, CameraStatus.UNKNOWN, T0)


def _event(i=1, cam="cam_1", at=T0) -> Event:
    return Event(f"evt_{i}", cam, "C01-T1", at, 0.4, EventStatus.PENDING, EventLocation(1, 2, "z"), at, at,
                 risk_level=RiskLevel.LOW, distress_signals=[DistressSignalType.ARMS_RAISED],
                 evidence=EvidenceRef("a/clip.mp4", None))


def test_camera_roundtrip(repos):
    cams = repos[0]
    cams.save(_camera())
    got = cams.get("cam_1")
    assert got == _camera() and cams.get("nope") is None and len(cams.list()) == 1


def test_zone_roundtrip_and_upsert(repos):
    cams, zones, *_ = repos
    cams.save(_camera())
    z = Zone("zone_1", "cam_1", "default", Polygon(((0, 0), (1, 0), (1, 1))), ZoneMode.STATIC, T0)
    zones.save(z)
    assert zones.get_by_camera("cam_1") == z
    zones.save(Zone("zone_1", "cam_1", "renamed", z.polygon, ZoneMode.STATIC, T0))
    assert zones.get_by_camera("cam_1").name == "renamed"


def test_event_roundtrip_update_and_filter(repos):
    cams, _, events, _ = repos
    cams.save(_camera())
    e1, e2 = _event(1), _event(2, at=T0 + timedelta(minutes=5))
    events.save(e1); events.save(e2)
    assert events.get("evt_1") == e1
    assert [e.id for e in events.list(EventFilter())] == ["evt_2", "evt_1"]  # newest first
    e1.acknowledge("bob", T0 + timedelta(minutes=1), "n")
    events.save(e1)
    assert events.get("evt_1").acknowledgement.by == "bob"
    assert [e.id for e in events.list(EventFilter(status=EventStatus.ACKNOWLEDGED))] == ["evt_1"]
    assert [e.id for e in events.list(EventFilter(started_after=T0 + timedelta(minutes=1)))] == ["evt_2"]
    assert len(events.list(EventFilter(limit=1))) == 1 and events.list(EventFilter(camera_id="x")) == []


def test_alert_roundtrip_and_overdue(repos):
    cams, _, events, alerts = repos
    cams.save(_camera()); events.save(_event(1)); events.save(_event(2))
    a = Alert("alt_1", "evt_1", T0, T0 + timedelta(seconds=30),
              deliveries=[DeliveryRecord(NotificationChannel.MOCK, DeliveryStatus.SENT, T0, "d")])
    alerts.save(a)
    alerts.save(Alert("alt_2", "evt_2", T0, T0 + timedelta(seconds=300)))
    assert alerts.get("alt_1") == a and alerts.get_by_event("evt_1").id == "alt_1"
    assert alerts.list_overdue(T0 + timedelta(seconds=10)) == []
    assert [x.id for x in alerts.list_overdue(T0 + timedelta(seconds=31))] == ["alt_1"]
    a.closed_at = T0
    alerts.save(a)
    assert [x.id for x in alerts.list(active_only=True)] == ["alt_2"] and len(alerts.list(active_only=False)) == 2
