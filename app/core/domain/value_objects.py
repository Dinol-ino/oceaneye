"""Immutable value objects shared across modules."""
from __future__ import annotations

import math
from dataclasses import dataclass

from app.core.exceptions import DomainValidationError


@dataclass(frozen=True)
class GeoPoint:
    lat: float
    lon: float

    def __post_init__(self) -> None:
        if not (-90 <= self.lat <= 90 and -180 <= self.lon <= 180):
            raise DomainValidationError("GeoPoint out of range")


@dataclass(frozen=True)
class BoundingBox:
    """Axis-aligned box in image coordinates (units defined by the producer)."""

    x_min: float
    y_min: float
    x_max: float
    y_max: float

    def __post_init__(self) -> None:
        if self.x_max < self.x_min or self.y_max < self.y_min:
            raise DomainValidationError("BoundingBox max must be >= min")

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x_min + self.x_max) / 2, (self.y_min + self.y_max) / 2)


@dataclass(frozen=True)
class Polygon:
    """Zone polygon. PROPOSED SCAFFOLD: vertices in the camera image coordinate space."""

    points: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        if len(self.points) < 3:
            raise DomainValidationError("Polygon needs at least 3 points")
        if not all(math.isfinite(c) for p in self.points for c in p):
            raise DomainValidationError("Polygon coordinates must be finite")
