"""Web Push subscription endpoints: how a phone registers to be woken when the app is closed.

The browser creates the subscription (endpoint URL + two keys) and posts it here. The endpoint URL
identifies a device-and-browser, so it is stored but never returned - listing devices exposes only a
hash and the label the lifeguard typed.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from app.alerts.services.test_alert import build_test_notification
from app.core.entities.push import PushSubscription, endpoint_fingerprint
from app.core.enums import DeliveryStatus, NotificationChannel
from app.core.exceptions import NotImplementedFeature
from app.security.authorization import ADMIN_ROLES, RESPONDER_ROLES
from app.security.dependencies import require_roles
from app.security.principal import Principal
from app.shared.dependencies import get_container, get_push_repository

router = APIRouter(prefix="/push", tags=["push"])
EndpointHash = Annotated[str, Path(pattern=r"^[a-f0-9]{8,64}$")]


class SubscriptionKeys(BaseModel):
    model_config = ConfigDict(extra="forbid")
    p256dh: str = Field(min_length=16, max_length=200)
    auth: str = Field(min_length=8, max_length=100)


class SubscriptionIn(BaseModel):
    """Mirrors the browser's ``PushSubscription.toJSON()`` plus a human label."""

    model_config = ConfigDict(extra="forbid")
    endpoint: str = Field(min_length=12, max_length=1000, pattern=r"^https://")
    keys: SubscriptionKeys
    label: str | None = Field(default=None, max_length=80)


class DeviceOut(BaseModel):
    endpoint_hash: str
    role: str
    label: str | None
    consecutive_failures: int


@router.get("/public-key", dependencies=[Depends(require_roles(*RESPONDER_ROLES))])
async def vapid_public_key(container=Depends(get_container)):
    """The application server's VAPID public key, which the browser needs to subscribe.

    404 when background push is not configured, so the client can fall back to foreground alerts
    instead of failing.
    """
    settings = container.settings
    if not (settings.push_enabled and settings.vapid_public_key):
        return Response(status_code=404)
    return {"public_key": settings.vapid_public_key, "subject": settings.vapid_subject}


@router.post("/subscribe", status_code=201, response_model=DeviceOut)
async def subscribe(body: SubscriptionIn, principal: Principal = Depends(require_roles(*RESPONDER_ROLES)),
                    repo=Depends(get_push_repository), container=Depends(get_container)):
    """Register this browser for background alerts. Re-posting the same endpoint just updates it.

    501 when the server has no push channel configured: a server misconfiguration would be a 500, but
    this is simply a capability this installation does not offer, which the client can handle by
    falling back to foreground alerts.
    """
    if not container.settings.push_enabled:
        raise NotImplementedFeature("background push is not enabled on this server")
    subscription = PushSubscription.create(
        endpoint=body.endpoint, p256dh_key=body.keys.p256dh, auth_key=body.keys.auth,
        role=principal.role, created_at=container.clock.now(),
        label=(body.label or principal.subject)[:80])
    repo.save(subscription)
    return DeviceOut(endpoint_hash=subscription.endpoint_hash, role=subscription.role.value,
                     label=subscription.label, consecutive_failures=0)


@router.post("/unsubscribe", status_code=204)
async def unsubscribe(body: SubscriptionIn, _: Principal = Depends(require_roles(*RESPONDER_ROLES)),
                      repo=Depends(get_push_repository)):
    """Called when a lifeguard turns alerts off, or the browser rotates the subscription."""
    repo.delete(endpoint_fingerprint(body.endpoint))
    return Response(status_code=204)


@router.get("/devices", response_model=list[DeviceOut], dependencies=[Depends(require_roles(*RESPONDER_ROLES))])
async def list_devices(repo=Depends(get_push_repository)):
    """Which devices would be woken by an alert. Endpoint URLs are never included.

    Readable by any responder, not just an administrator: an operator about to rely on phone alerts
    needs to see that a phone is actually registered, and a hash plus a label reveals nothing.
    """
    return [DeviceOut(endpoint_hash=s.endpoint_hash, role=s.role.value, label=s.label,
                      consecutive_failures=s.consecutive_failures) for s in repo.list()]


@router.post("/test", dependencies=[Depends(require_roles(*RESPONDER_ROLES))])
async def send_test_push(container=Depends(get_container)):
    """Send a test notification to every registered phone, and report what happened.

    This is the one honest way to answer "will the PC actually reach the phone?". It goes through
    the real push channel, so a success here means a real alert would arrive too - including with
    the app closed and the screen off.
    """
    if not container.settings.push_enabled:
        raise NotImplementedFeature("background push is not enabled on this server")

    devices = container.push_repository.list()
    if not devices:
        return {"sent": 0, "devices": 0,
                "detail": "No phones are registered. Open the lifeguard app on a phone and tap "
                          "'Turn on alerts' first."}

    notification = build_test_notification(container.clock.now())
    records = await container.notification_provider.send(notification)
    push = [r for r in records if r.channel is NotificationChannel.WEB_PUSH]
    detail = "; ".join(f"{r.channel.value}: {r.status.value} ({r.detail})" for r in records)
    sent = sum(1 for r in push if r.status is DeliveryStatus.SENT)
    return {"sent": sent, "devices": len(devices), "detail": detail}


@router.delete("/devices/{endpoint_hash}", status_code=204,
               dependencies=[Depends(require_roles(*ADMIN_ROLES))])
async def forget_device(endpoint_hash: EndpointHash, repo=Depends(get_push_repository)):
    repo.delete(endpoint_hash)
    return Response(status_code=204)
