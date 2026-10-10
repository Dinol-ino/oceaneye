import asyncio

from tests.conftest import ADMIN, LIFEGUARD, SERVICE, event_body


def test_unacknowledged_alert_escalates_after_deadline(client, app, clock, camera):
    container = app.state.container
    ev = client.post("/api/events", headers=SERVICE, json=event_body(camera["id"])).json()
    clock.advance(10)
    assert asyncio.run(container.escalation_service.process_timeouts()) == []   # before deadline
    clock.advance(25)                                                           # 35 s > 30 s deadline
    assert asyncio.run(container.escalation_service.process_timeouts()) == [ev["id"]]
    got = client.get(f"/api/events/{ev['id']}", headers=LIFEGUARD).json()
    assert got["status"] == "escalated" and got["escalation_level"] == 1
    alert = client.get("/api/alerts", headers=LIFEGUARD).json()[0]
    assert alert["escalation_level"] == 1
    assert asyncio.run(container.escalation_service.process_timeouts()) == []   # not re-escalated


def test_acknowledged_alert_not_escalated(client, app, clock, camera):
    ev = client.post("/api/events", headers=SERVICE, json=event_body(camera["id"])).json()
    client.post(f"/api/events/{ev['id']}/ack", headers=LIFEGUARD)
    clock.advance(120)
    assert asyncio.run(app.state.container.escalation_service.process_timeouts()) == []
