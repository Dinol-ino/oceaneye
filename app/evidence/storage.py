"""Evidence storage port (clips, thumbnails, metadata). Local disk now; object storage later."""
from __future__ import annotations

from abc import ABC, abstractmethod


class EvidenceStorage(ABC):
    @abstractmethod
    def save(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None: ...

    @abstractmethod
    def read(self, key: str) -> bytes | None:
        """None if missing."""

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def healthcheck(self) -> bool: ...
