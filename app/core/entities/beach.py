"""The beach a deployment watches.

In the field OceanEye runs for **one** beach: that beach's authority owns the cameras, its lifeguards
answer the alerts, and nobody there picks a location from a dropdown. That is what ``is_active``
expresses - exactly one beach is the deployment, and everything the operator sees is scoped to it.

The region/beach picker exists for a different reason: so the prototype can be set up, and
demonstrated, for any stretch of coast without editing code. Choosing a beach in the Control Room is
a *configuration* action (it changes which beach this installation watches), not a browsing one.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.core.domain.value_objects import GeoPoint
from app.core.exceptions import DomainValidationError


@dataclass
class Beach:
    id: str
    region: str  # administrative area the beach sits in, e.g. "Karnataka, India"
    name: str
    location: GeoPoint
    created_at: datetime
    is_active: bool = False  # the one beach this installation is deployed at
    authority_name: str | None = None  # who operates the cameras and is accountable for response
    authority_phone: str | None = None
    lifeguard_count: int = 0  # staffed posts, shown to the control room; maintained by the authority
    notes: str | None = None
    source_id: str | None = None  # OpenStreetMap element this was created from, when picked from the map

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise DomainValidationError("beach name must not be empty")
        if self.lifeguard_count < 0:
            raise DomainValidationError("lifeguard_count must not be negative")

    @property
    def label(self) -> str:
        return f"{self.name}, {self.region}" if self.region else self.name
