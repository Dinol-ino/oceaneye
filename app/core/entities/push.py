"""A browser's Web Push subscription: how to wake a lifeguard whose app is closed.

WebSocket alerts only reach a phone whose browser tab is alive and in the foreground - which is not
how a lifeguard carries a phone during a shift. Web Push goes through the browser vendor's push
service, so the device wakes even with the app closed and the screen off.

The endpoint URL identifies a device-and-browser and is a tracking-grade identifier, so the stored
primary key is a hash of it; the URL itself is kept only because it is needed to deliver, and never
leaves the server.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from app.core.enums import Role
from app.core.exceptions import DomainValidationError


def endpoint_fingerprint(endpoint: str) -> str:
    """Stable, non-reversible id for a push endpoint (used as the primary key)."""
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()[:40]


@dataclass
class PushSubscription:
    endpoint_hash: str
    endpoint: str  # SENSITIVE: never serialised to API clients
    p256dh_key: str  # subscriber public key (payload encryption)
    auth_key: str  # subscriber auth secret
    role: Role
    created_at: datetime
    label: str | None = None  # e.g. "Lifeguard Ravi - Tower 2", so a stale device can be identified
    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None
    consecutive_failures: int = 0

    def __post_init__(self) -> None:
        if not (self.endpoint and self.p256dh_key and self.auth_key):
            raise DomainValidationError("push subscription is missing endpoint or keys")
        if self.endpoint_hash != endpoint_fingerprint(self.endpoint):
            raise DomainValidationError("endpoint_hash does not match endpoint")

    @classmethod
    def create(cls, endpoint: str, p256dh_key: str, auth_key: str, role: Role, created_at: datetime,
               label: str | None = None) -> "PushSubscription":
        return cls(endpoint_fingerprint(endpoint), endpoint, p256dh_key, auth_key, role, created_at, label)
