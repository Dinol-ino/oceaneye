from __future__ import annotations

from datetime import datetime, timezone

from app.core.interfaces.clock import Clock


class SystemClock(Clock):
    def now(self) -> datetime:
        return datetime.now(timezone.utc)
