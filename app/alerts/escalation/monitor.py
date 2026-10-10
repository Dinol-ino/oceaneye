"""Background timeout checker (plumbing only; no AI). Disabled in tests via settings."""
from __future__ import annotations

import asyncio
import logging

from app.alerts.escalation.base import EscalationService

logger = logging.getLogger(__name__)


class EscalationMonitor:
    def __init__(self, service: EscalationService, interval_seconds: float) -> None:
        self._service = service
        self._interval = interval_seconds
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="escalation-monitor")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await self._service.process_timeouts()
            except Exception:  # noqa: BLE001
                logger.exception("escalation monitor iteration failed")
            await asyncio.sleep(self._interval)
