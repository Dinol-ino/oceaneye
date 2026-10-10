from tests.conftest import LIFEGUARD, OPERATOR, SERVICE, event_body


def test_create_event_defaults_location_and_status(client, camera, event):
    assert event["status"] == "pending" and event["location"]["lat"] == 12.84
    assert event["location"]["zone_name"] == "default"
    assert event["id"].startswith("evt_")


def test_unknown_camera_404(client):
    r = client.post("/api/events", headers=SERVICE, json=event_body("cam_missing"))
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_risk_score_validated(client, camera):
    assert client.post("/api/events", headers=SERVICE, json=event_body(camera["id"], risk_score=1.5)).status_code == 422


def test_list_filter_and_get(client, camera, event):
    assert len(client.get("/api/events", headers=OPERATOR).json()) == 1
    assert client.get("/api/events?status=resolved", headers=OPERATOR).json() == []
    assert client.get(f"/api/events?camera_id={camera['id']}", headers=OPERATOR).json()[0]["id"] == event["id"]
    assert client.get(f"/api/events/{event['id']}", headers=LIFEGUARD).json()["id"] == event["id"]
    assert client.get("/api/events/evt_missing", headers=LIFEGUARD).status_code == 404


def test_acknowledge_flow(client, event):
    r = client.post(f"/api/events/{event['id']}/ack", headers=LIFEGUARD, json={"note": "on it"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "acknowledged" and body["acknowledgement"]["by"] == "tester"
    again = client.post(f"/api/events/{event['id']}/ack", headers=LIFEGUARD)
    assert again.status_code == 409 and again.json()["error"]["code"] == "invalid_state_transition"


def test_escalate_flow(client, event):
    r = client.post(f"/api/events/{event['id']}/escalate", headers=OPERATOR, json={"reason": "no response"})
    assert r.status_code == 200 and r.json()["status"] == "escalated" and r.json()["escalation_level"] == 1
    assert client.post(f"/api/events/{event['id']}/escalate", headers=OPERATOR).status_code == 409


def test_outcome_closes_loop(client, event):
    r = client.post(f"/api/events/{event['id']}/outcome", headers=LIFEGUARD, json={"outcome": "false_alarm"})
    assert r.json()["status"] == "false_alarm" and r.json()["closed_at"]
    assert client.post(f"/api/events/{event['id']}/ack", headers=LIFEGUARD).status_code == 409
    assert client.get("/api/alerts", headers=LIFEGUARD).json() == []  # alert closed


def test_alert_created_for_event(client, event):
    alerts = client.get("/api/alerts", headers=LIFEGUARD).json()
    assert len(alerts) == 1 and alerts[0]["event_id"] == event["id"]
    assert alerts[0]["payload"]["event_status"] == "pending"
    channels = {d["channel"] for d in alerts[0]["deliveries"]}
    assert channels == {"websocket", "mock"}


def test_evidence_protected_and_served(client, camera, app):
    app.state.container.evidence_storage.save("evt/clip.mp4", b"MOCKBYTES")
    r = client.post("/api/events", headers=SERVICE,
                    json=event_body(camera["id"], evidence={"clip_key": "evt/clip.mp4"}))
    ev = r.json()
    assert ev["evidence_clip_url"].endswith(f"/evidence/{ev['id']}/clip")
    assert client.get(ev["evidence_clip_url"]).status_code == 401
    got = client.get(ev["evidence_clip_url"], headers=LIFEGUARD)
    assert got.status_code == 200 and got.content == b"MOCKBYTES"
    assert client.get(f"/api/evidence/{ev['id']}/thumbnail", headers=LIFEGUARD).status_code == 404


def test_evidence_key_traversal_rejected(client, camera):
    r = client.post("/api/events", headers=SERVICE,
                    json=event_body(camera["id"], evidence={"clip_key": "../../etc/passwd"}))
    assert r.status_code == 422
