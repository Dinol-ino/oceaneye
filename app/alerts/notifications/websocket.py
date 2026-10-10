from __future__ import annotations

from typing import Sequence

from app.alerts.notifications.base import AlertBroadcaster, NotificationProvider
from app.core.entities.alert import AlertNotification, DeliveryRecord
from app.core.enums import DeliveryStatus, NotificationChannel


class WebSocketNotificationProvider(NotificationProvider):
    channel = NotificationChannel.WEBSOCKET

    def __init__(self, broadcaster: AlertBroadcaster) -> None:
        self._broadcaster = broadcaster

    async def send(self, notification: AlertNotification) -> Sequence[DeliveryRecord]:
        reached = await self._broadcaster.broadcast(notification)
        status = DeliveryStatus.SENT if reached else DeliveryStatus.SKIPPED
        return [DeliveryRecord(self.channel, status, notification.sent_at, f"{reached} client(s)")]
