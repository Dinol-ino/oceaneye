"""Pure geometry helpers (no numpy)."""
from __future__ import annotations

from typing import Sequence


def point_in_polygon(x: float, y: float, points: Sequence[tuple[float, float]]) -> bool:
    """Ray casting. Points on an edge may fall either way (irrelevant at pixel scale)."""
    inside = False
    n = len(points)
    j = n - 1
    for i in range(n):
        xi, yi = points[i]
        xj, yj = points[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def is_normalized(points: Sequence[tuple[float, float]]) -> bool:
    return all(0.0 <= c <= 1.0 for p in points for c in p)
