"""Web Push notification channel: wakes a phone whose lifeguard app is closed.

WebSocket alerts reach only a live, foreground tab. A lifeguard on duty has the phone in a pocket
with the screen off, so the alert has to arrive through the operating system. Web Push does that: the
server posts an encrypted message to the endpoint the browser gave us, the browser vendor's push
service delivers it, and the installed service worker shows the notification.

Requirements this imposes, and why they are not negotiable:

* **A secure origin.** Browsers expose the Push API only over HTTPS (or localhost), so a LAN demo
  needs the self-signed certificate from ``scripts/make_certs.py``.
* **A VAPID key pair.** The push service authenticates the sender. ``scripts/make_push_keys.py``
  generates the pair; the private key is a secret and lives only in ``.env``.
* **A small payload.** Push payloads are size-limited and pass through a third party, so this sends
  identifiers and a short human summary - never evidence images, and never more personal detail than
  the responder needs to act.

Delivery is best-effort and isolated: a dead endpoint is removed (HTTP 404/410 means the browser
dropped the subscription), any other failure is recorded and retried on the next alert. Nothing here
can delay or fail the alert itself.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Sequence

from app.alerts.notifications.base import NotificationProvider
from app.core.entities.alert import AlertNotification, DeliveryRecord
from app.core.enums import AlertNotificationType, DeliveryStatus, NotificationChannel, Role
from app.core.exceptions import ConfigurationError
from app.core.interfaces.clock import Clock
from app.alerts.services.test_alert import is_test_notification
from app.core.interfaces.repositories import PushSubscriptionRepository

logger = logging.getLogger(__name__)

#: A subscription that keeps failing is almost certainly a phone that was wiped or reinstalled.
MAX_CONSECUTIVE_FAILURES = 10
#: Endpoints the push service tells us are permanently gone.
GONE_STATUS_CODES = (404, 410)
#: Who gets woken. Operators watch a screen; lifeguards are the ones who must be reached.
PUSH_ROLES = (Role.LIFEGUARD, Role.OPERATOR)
#: Only these transitions are worth waking a phone for.
PUSHABLE = (AlertNotificationType.CREATED, AlertNotificationType.ESCALATED)


def select_targets(subscriptions, camera_id: str | None):
    """Which phones this alert goes to, and a one-word record of why.

    Posts, not GPS. A guard registers the camera (tower, stretch of beach) they are covering, and
    an alert from that camera reaches them. This needs no location permission, no battery drain,
    and nothing from a phone sitting in a pocket with no signal - and it matches how beaches are
    actually staffed.

    Two rules keep it safe rather than merely clever:

    * A device with **no post** is roaming and receives everything. That is the default, so a
      guard who skipped the setting, or a phone registered before posts existed, is never
      silently cut out of alerts.
    * If a camera has **no covering guard and no roamers**, the alert goes to **everyone**. An
      alert that reaches the wrong guard is an inconvenience; a drowning alert that reaches
      nobody because the roster was mis-entered is the failure this whole system exists to
      prevent. Narrow routing must never be able to produce silence.

    Returns ``(targets, routing)`` where ``routing`` is "assigned", "roaming-only" or
    "broadcast-fallback", so the control room can see which rule fired.
    """
    pure_broadcast = list(subscriptions)
    if not camera_id:
        return pure_broadcast, "broadcast-no-camera"
    assigned = [s for s in subscriptions if camera_id in (s.assigned_camera_ids or ())]
    roaming = [s for s in subscriptions if not (s.assigned_camera_ids or ())]
    chosen = assigned + [s for s in roaming if s not in assigned]
    if chosen:
        return chosen, ("assigned" if assigned else "roaming-only")
    logger.warning("no guard covers camera %s and none are roaming; broadcasting to all %d device(s)",
                   camera_id, len(pure_broadcast))
    return pure_broadcast, "broadcast-fallback"


def _title(notification: AlertNotification) -> str:
    if is_test_notification(notification.payload):
        # A connection check must never read like a swimmer in trouble.
        return "OceanEye test alert"
    return ("Possible distress" if notification.type is AlertNotificationType.CREATED
            else "Alert escalated")


def build_push_payload(notification: AlertNotification, camera_label: str | None = None) -> bytes:
    """The JSON the service worker renders. Deliberately minimal (see module docstring)."""
    p = notification.payload
    body = {
        "type": notification.type.value,
        "title": _title(notification),
        "test": is_test_notification(p) or None,
        "event_id": p.event_id,
        "camera": camera_label or p.camera_id,
        "zone": p.location.zone_name,
        "risk_score": round(p.risk_score, 2),
        "risk_level": p.risk_level.value if p.risk_level else None,
        "signals": [s.value for s in p.distress_signals][:4],
        "ack_deadline": p.ack_deadline.isoformat(),
        "sent_at": notification.sent_at.isoformat(),
    }
    return json.dumps(body, separators=(",", ":")).encode("utf-8")


class WebPushNotificationProvider(NotificationProvider):
    channel = NotificationChannel.WEB_PUSH

    def __init__(self, subscriptions: PushSubscriptionRepository, clock: Clock, *,
                 vapid_private_key: str, vapid_subject: str, ttl_seconds: int = 120,
                 sender=None) -> None:
        if not vapid_private_key:
            raise ConfigurationError(
                "web_push needs a VAPID private key: generate one with python scripts/make_push_keys.py")
        self._subs, self._clock = subscriptions, clock
        self._private_key, self._subject, self._ttl = vapid_private_key, vapid_subject, ttl_seconds
        self._sender = sender or self._pywebpush_send

    # -- transport -------------------------------------------------------------
    def _pywebpush_send(self, subscription_info: dict, payload: bytes) -> int:
        """Blocking send via pywebpush. Returns the push service's HTTP status code."""
        try:
            from pywebpush import WebPushException, webpush  # noqa: PLC0415 - optional extra
        except ImportError as exc:
            raise ConfigurationError(
                "the web_push channel needs the push extra: pip install -e \".[push]\"") from exc
        try:
            response = webpush(subscription_info=subscription_info, data=payload, ttl=self._ttl,
                               vapid_private_key=self._private_key,
                               vapid_claims={"sub": self._subject},
                               headers={"Urgency": "high"},  # a drowning alert is not a digest item
                               content_encoding="aes128gcm")
            return int(getattr(response, "status_code", 201))
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status is None:
                raise
            return int(status)

    # -- NotificationProvider ---------------------------------------------------
    async def send(self, notification: AlertNotification) -> Sequence[DeliveryRecord]:
        if notification.type not in PUSHABLE:
            return [DeliveryRecord(self.channel, DeliveryStatus.SKIPPED, notification.sent_at,
                                   f"{notification.type.value} is not pushed")]
        subscribed = [s for role in PUSH_ROLES for s in self._subs.list(role.value)]
        if not subscribed:
            return [DeliveryRecord(self.channel, DeliveryStatus.SKIPPED, notification.sent_at,
                                   "no devices subscribed")]
        targets, routing = select_targets(subscribed, notification.payload.camera_id)
        payload = build_push_payload(notification)
        results = await asyncio.gather(*(self._deliver(s, payload) for s in targets))
        sent = sum(1 for ok in results if ok)
        status = DeliveryStatus.SENT if sent else DeliveryStatus.FAILED
        return [DeliveryRecord(self.channel, status, notification.sent_at,
                               f"{sent}/{len(targets)} device(s) [{routing}]")]

    async def _deliver(self, sub, payload: bytes) -> bool:
        """Push to one device. Never raises: one dead phone must not silence the others."""
        info = {"endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh_key, "auth": sub.auth_key}}
        now = self._clock.now()
        try:
            status = await asyncio.to_thread(self._sender, info, payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("web push failed for %s: %s", sub.endpoint_hash, type(exc).__name__)
            self._record_failure(sub, now)
            return False
        if status in GONE_STATUS_CODES:
            logger.info("push endpoint gone; removing subscription %s", sub.endpoint_hash)
            self._subs.delete(sub.endpoint_hash)
            return False
        if status >= 400:
            logger.warning("push service returned %s for %s", status, sub.endpoint_hash)
            self._record_failure(sub, now)
            return False
        self._subs.touch(sub.endpoint_hash, now, 0)
        return True

    def _record_failure(self, sub, now) -> None:
        failures = sub.consecutive_failures + 1
        if failures >= MAX_CONSECUTIVE_FAILURES:
            logger.info("dropping push subscription %s after %d failures", sub.endpoint_hash, failures)
            self._subs.delete(sub.endpoint_hash)
        else:
            self._subs.touch(sub.endpoint_hash, now, failures)
