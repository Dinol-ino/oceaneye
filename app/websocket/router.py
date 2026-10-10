"""WS /ws/alerts - live alert feed for the operator dashboard and lifeguard client.

Auth: handshake credentials via the central Authenticator (dev: ?dev_role=...). Optional filter:
?camera_id=cam_x&camera_id=cam_y. Client messages: {"action":"subscribe","camera_ids":[...]} | {"action":"ping"}.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.exceptions import OceanEyeError
from app.security.authentication import Credentials
from app.security.authorization import RESPONDER_ROLES, authorize
from app.websocket.manager import Subscription

router = APIRouter()


@router.websocket("/ws/alerts")
async def alerts_socket(websocket: WebSocket):
    container = websocket.app.state.container
    try:
        principal = container.authenticator.authenticate(
            Credentials(headers=dict(websocket.headers), query=dict(websocket.query_params))
        )
        authorize(principal, RESPONDER_ROLES)
    except OceanEyeError:
        await websocket.close(code=1008)  # policy violation
        return

    manager = container.ws_manager
    sub = Subscription(set(websocket.query_params.getlist("camera_id")))
    conn = await manager.connect(websocket, principal, sub)
    try:
        await websocket.send_json({"type": "connection.ready", "subscribed_cameras": sorted(sub.camera_ids)})
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                action = msg.get("action")
            except (ValueError, AttributeError):
                await websocket.send_json({"type": "error", "message": "invalid message"})
                continue
            if action == "subscribe":
                ids = msg.get("camera_ids") or []
                if isinstance(ids, list) and all(isinstance(i, str) for i in ids):
                    conn.subscription.camera_ids = set(ids)
                    await websocket.send_json({"type": "subscribed", "camera_ids": sorted(ids)})
                else:
                    await websocket.send_json({"type": "error", "message": "camera_ids must be a list of strings"})
            elif action == "ping":
                await websocket.send_json({"type": "pong"})
            else:
                await websocket.send_json({"type": "error", "message": "unknown action"})
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(conn)
