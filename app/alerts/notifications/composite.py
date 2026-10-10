from __future__ import annotations

import logging
from typing import Sequence

from app.alerts.notifications.base import NotificationProvider
from app.core.entities.alert import AlertNotification, DeliveryRecord
from app.core.enums import DeliveryStatus, NotificationChannel

logger = logging.getLogger(__name__)


class CompositeNotificationProvider(NotificationProvider):
    """Fan-out to all configured channels; one failing channel never blocks the others."""

    channel = NotificationChannel.MOCK  # not meaningful for a composite

    def __init__(self, providers: Sequence[NotificationProvider]) -> None:
        self._providers = list(providers)

    async def send(self, notification: AlertNotification) -> Sequence[DeliveryRecord]:
        records: list[DeliveryRecord] = []
        for provider in self._providers:
            try:
                records.extend(await provider.send(notification))
            except Exception:  # noqa: BLE001
                logger.exception("notification channel failed", extra={"channel": provider.channel.value})
                records.append(DeliveryRecord(provider.channel, DeliveryStatus.FAILED, notification.sent_at, "error"))
        return records
