"""Background phone alerts: payload shape, delivery isolation, and subscription hygiene."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest

from app.alerts.notifications.web_push import (
    MAX_CONSECUTIVE_FAILURES,
    WebPushNotificationProvider,
    build_push_payload,
)
from app.core.entities.alert import Alert, AlertNotification, AlertPayload
from app.core.entities.event import EventLocation
from app.core.entities.push import PushSubscription, endpoint_fingerprint
from app.core.enums import (
    AlertNotificationType,
    DeliveryStatus,
    DistressSignalType,
    EventStatus,
    RiskLevel,
    Role,
)
from app.core.exceptions import ConfigurationError, DomainValidationError
from app.persistence.repositories.in_memory import InMemoryPushSubscriptionRepository
from tests.conftest import FakeClock

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def notification(kind=AlertNotificationType.CREATED) -> AlertNotification:
    payload = AlertPayload(
        alert_id="alt_1", event_id="evt_1", camera_id="cam_1", track_id="cam_1-T7", risk_score=0.812,
        risk_level=RiskLevel.HIGH, timestamp=NOW, location=EventLocation(12.84, 74.80, "Swim area"),
        distress_signals=(DistressSignalType.VERTICAL_BOBBING, DistressSignalType.REPEATED_SUBMERSION),
        reason="long reason text", thumbnail_url="/api/evidence/evt_1/thumbnail", clip_url=None,
        ack_deadline=NOW, event_status=EventStatus.PENDING, escalation_level=0)
    return AlertNotification(kind, payload, NOW)


def subscription(n: int = 1, role: Role = Role.LIFEGUARD) -> PushSubscription:
    return PushSubscription.create(f"https://push.example/{n}", "p" * 20, "a" * 12, role, NOW, f"Tower {n}")


def provider(repo, sender):
    return WebPushNotificationProvider(repo, FakeClock(), vapid_private_key="test-key",
                                       vapid_subject="mailto:test@example.invalid", sender=sender)


# ---- payload ----------------------------------------------------------------------
def test_payload_carries_what_a_responder_needs_and_no_evidence():
    body = json.loads(build_push_payload(notification(), camera_label="North tower"))
    assert body["camera"] == "North tower" and body["zone"] == "Swim area"
    assert body["risk_level"] == "high" and body["risk_score"] == 0.81
    assert body["signals"] == ["vertical_bobbing", "repeated_submersion"]
    assert body["event_id"] == "evt_1" and body["title"] == "Possible distress"
    # Push payloads pass through a third party: no images, no free-text reason, no track detail.
    assert "thumbnail_url" not in body and "reason" not in body and "track_id" not in body


def test_payload_stays_small_enough_for_a_push_service():
    assert len(build_push_payload(notification())) < 1024


def test_escalation_has_its_own_title():
    body = json.loads(build_push_payload(notification(AlertNotificationType.ESCALATED)))
    assert body["title"] == "Alert escalated"


# ---- delivery ----------------------------------------------------------------------
def test_sends_to_every_subscribed_responder():
    repo = InMemoryPushSubscriptionRepository()
    repo.save(subscription(1))
    repo.save(subscription(2, Role.OPERATOR))
    calls = []
    records = asyncio.run(provider(repo, lambda info, data: calls.append(info) or 201).send(notification()))
    assert len(calls) == 2
    assert records[0].status is DeliveryStatus.SENT and "2/2" in records[0].detail


def test_no_devices_is_skipped_not_failed():
    records = asyncio.run(provider(InMemoryPushSubscriptionRepository(), lambda *_: 201).send(notification()))
    assert records[0].status is DeliveryStatus.SKIPPED


def test_acknowledgement_does_not_wake_a_phone():
    repo = InMemoryPushSubscriptionRepository()
    repo.save(subscription(1))
    calls = []
    records = asyncio.run(provider(repo, lambda *a: calls.append(a) or 201)
                          .send(notification(AlertNotificationType.ACKNOWLEDGED)))
    assert calls == [] and records[0].status is DeliveryStatus.SKIPPED


def test_one_dead_device_does_not_silence_the_others():
    repo = InMemoryPushSubscriptionRepository()
    repo.save(subscription(1))
    repo.save(subscription(2))
    def sender(info, data):
        if info["endpoint"].endswith("/1"):
            raise RuntimeError("network down")
        return 201
    records = asyncio.run(provider(repo, sender).send(notification()))
    assert records[0].status is DeliveryStatus.SENT and "1/2" in records[0].detail


def test_all_devices_failing_is_reported_as_failed():
    repo = InMemoryPushSubscriptionRepository()
    repo.save(subscription(1))
    def sender(*_):
        raise RuntimeError("offline")
    records = asyncio.run(provider(repo, sender).send(notification()))
    assert records[0].status is DeliveryStatus.FAILED


@pytest.mark.parametrize("status", [404, 410])
def test_a_gone_endpoint_is_forgotten_immediately(status):
    """404/410 means the browser dropped the subscription; keeping it would retry forever."""
    repo = InMemoryPushSubscriptionRepository()
    repo.save(subscription(1))
    asyncio.run(provider(repo, lambda *_: status).send(notification()))
    assert repo.list() == []


def test_transient_failures_are_counted_then_the_device_is_dropped():
    repo = InMemoryPushSubscriptionRepository()
    sub = subscription(1)
    repo.save(sub)
    push = provider(repo, lambda *_: 500)
    for _ in range(MAX_CONSECUTIVE_FAILURES - 1):
        asyncio.run(push.send(notification()))
    assert repo.list()[0].consecutive_failures == MAX_CONSECUTIVE_FAILURES - 1
    asyncio.run(push.send(notification()))
    assert repo.list() == []


def test_a_success_clears_the_failure_count():
    repo = InMemoryPushSubscriptionRepository()
    repo.save(subscription(1))
    asyncio.run(provider(repo, lambda *_: 500).send(notification()))
    assert repo.list()[0].consecutive_failures == 1
    asyncio.run(provider(repo, lambda *_: 201).send(notification()))
    stored = repo.list()[0]
    assert stored.consecutive_failures == 0 and stored.last_success_at is not None


def test_provider_refuses_to_start_without_a_key():
    with pytest.raises(ConfigurationError):
        WebPushNotificationProvider(InMemoryPushSubscriptionRepository(), FakeClock(),
                                    vapid_private_key="", vapid_subject="mailto:x@y.invalid")


# ---- subscription entity -------------------------------------------------------------
def test_endpoint_is_keyed_by_a_hash_not_the_url():
    sub = subscription(1)
    assert sub.endpoint_hash == endpoint_fingerprint("https://push.example/1")
    assert "push.example" not in sub.endpoint_hash and len(sub.endpoint_hash) == 40


def test_a_tampered_hash_is_rejected():
    with pytest.raises(DomainValidationError):
        PushSubscription("deadbeef", "https://push.example/1", "p" * 20, "a" * 12, Role.LIFEGUARD, NOW)


def test_missing_keys_are_rejected():
    with pytest.raises(DomainValidationError):
        PushSubscription.create("https://push.example/1", "", "a" * 12, Role.LIFEGUARD, NOW)
