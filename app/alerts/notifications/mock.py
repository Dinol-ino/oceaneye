from __future__ import annotations

import logging
from typing import Sequence

from app.alerts.notifications.base import NotificationProvider
from app.core.entities.alert import AlertNotification, DeliveryRecord
from app.core.enums import DeliveryStatus, NotificationChannel

logger = logging.getLogger(__name__)


class MockNotificationProvider(NotificationProvider):
    """Development provider: logs and records notifications in memory. Sends nothing anywhere."""

    channel = NotificationChannel.MOCK

    def __init__(self) -> None:
        self.sent: list[AlertNotification] = []

    async def send(self, notification: AlertNotification) -> Sequence[DeliveryRecord]:
        self.sent.append(notification)
        logger.info("MOCK notification", extra={"type": notification.type.value,
                                                "event_id": notification.payload.event_id})
        return [DeliveryRecord(self.channel, DeliveryStatus.SENT, notification.sent_at, "mock")]
