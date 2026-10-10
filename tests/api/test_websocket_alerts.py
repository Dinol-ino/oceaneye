import pytest
from starlette.websockets import WebSocketDisconnect

from tests.conftest import LIFEGUARD, SERVICE, event_body


def test_ws_requires_auth(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/alerts"):
            pass


def test_ws_alert_flow(client, camera):
    with client.websocket_connect("/ws/alerts?dev_role=lifeguard") as ws:
        assert ws.receive_json()["type"] == "connection.ready"
        ev = client.post("/api/events", headers=SERVICE, json=event_body(camera["id"])).json()
        msg = ws.receive_json()
        assert msg["type"] == "alert.created" and msg["payload"]["event_id"] == ev["id"]
        client.post(f"/api/events/{ev['id']}/ack", headers=LIFEGUARD)
        assert ws.receive_json()["type"] == "alert.acknowledged"
        client.post(f"/api/events/{ev['id']}/outcome", headers=LIFEGUARD, json={"outcome": "resolved"})
        assert ws.receive_json()["type"] == "alert.closed"


def test_ws_camera_filter(client, camera):
    with client.websocket_connect("/ws/alerts?dev_role=operator&camera_id=cam_other") as ws:
        ws.receive_json()
        client.post("/api/events", headers=SERVICE, json=event_body(camera["id"]))
        ws.send_text('{"action":"ping"}')
        assert ws.receive_json()["type"] == "pong"  # nothing was pushed before the pong


def test_ws_subscribe_message(client, camera):
    with client.websocket_connect("/ws/alerts?dev_role=operator") as ws:
        ws.receive_json()
        ws.send_text('{"action":"subscribe","camera_ids":["cam_other"]}')
        assert ws.receive_json()["type"] == "subscribed"
        ws.send_text("not json")
        assert ws.receive_json()["type"] == "error"
