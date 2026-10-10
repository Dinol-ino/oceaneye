from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Awaitable, Callable, TypeVar

from app.core.domain.domain_events import DomainEvent

E = TypeVar("E", bound=DomainEvent)
Handler = Callable[[E], Awaitable[None]]


class DomainEventBus(ABC):
    @abstractmethod
    def subscribe(self, event_type: type[E], handler: Handler) -> None: ...

    @abstractmethod
    async def publish(self, event: DomainEvent) -> None: ...
