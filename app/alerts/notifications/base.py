"""Notification boundary. Add Web Push / SMS by implementing NotificationProvider and
registering it in the composition root; no risk/event code changes."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from app.core.entities.alert import AlertNotification, DeliveryRecord
from app.core.enums import NotificationChannel


class NotificationProvider(ABC):
    channel: NotificationChannel

    @abstractmethod
    async def send(self, notification: AlertNotification) -> Sequence[DeliveryRecord]: ...


class AlertBroadcaster(ABC):
    """Implemented by the WebSocket connection manager (alerts must not import websocket)."""

    @abstractmethod
    async def broadcast(self, notification: AlertNotification) -> int:
        """Return the number of clients reached."""
