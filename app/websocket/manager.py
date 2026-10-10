"""In-process WebSocket connection manager (single process; no distributed fan-out)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from fastapi import WebSocket

from app.alerts.api.schemas import AlertPayloadSchema
from app.alerts.notifications.base import AlertBroadcaster
from app.core.entities.alert import AlertNotification
from app.security.principal import Principal

logger = logging.getLogger(__name__)


@dataclass
class Subscription:
    """Which cameras a client wants. Empty set = all cameras."""

    camera_ids: set[str] = field(default_factory=set)

    def matches(self, camera_id: str) -> bool:
        return not self.camera_ids or camera_id in self.camera_ids


@dataclass
class Connection:
    websocket: WebSocket
    principal: Principal
    subscription: Subscription


def notification_to_message(n: AlertNotification) -> dict:
    return {
        "type": n.type.value,
        "sent_at": n.sent_at.isoformat(),
        "payload": AlertPayloadSchema.from_domain(n.payload).model_dump(mode="json"),
    }


class ConnectionManager(AlertBroadcaster):
    def __init__(self) -> None:
        self._connections: list[Connection] = []

    @property
    def active_connections(self) -> int:
        return len(self._connections)

    async def connect(self, websocket: WebSocket, principal: Principal, subscription: Subscription) -> Connection:
        await websocket.accept()
        conn = Connection(websocket, principal, subscription)
        self._connections.append(conn)
        logger.info("ws connected", extra={"role": principal.role.value})
        return conn

    def disconnect(self, conn: Connection) -> None:
        if conn in self._connections:
            self._connections.remove(conn)

    async def broadcast(self, notification: AlertNotification) -> int:
        message = notification_to_message(notification)
        reached = 0
        for conn in list(self._connections):
            if not conn.subscription.matches(notification.payload.camera_id):
                continue
            try:
                await conn.websocket.send_json(message)
                reached += 1
            except Exception:  # noqa: BLE001 - drop dead sockets
                logger.warning("ws send failed; dropping connection")
                self.disconnect(conn)
        return reached

    async def close_all(self) -> None:
        for conn in list(self._connections):
            try:
                await conn.websocket.close(code=1001)
            except Exception:  # noqa: BLE001
                pass
            self.disconnect(conn)
