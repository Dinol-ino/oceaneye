from __future__ import annotations

from pathlib import Path

from app.core.exceptions import DomainValidationError
from app.evidence.storage import EvidenceStorage


class LocalEvidenceStorage(EvidenceStorage):
    """Local-disk adapter. Keys are confined to the storage root (no path traversal)."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self._root / key).resolve()
        if self._root != path and self._root not in path.parents:
            raise DomainValidationError("invalid storage key")
        return path

    def save(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)  # content_type kept for interface parity with object storage

    def read(self, key: str) -> bytes | None:
        path = self._path(key)
        return path.read_bytes() if path.is_file() else None

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.is_file():
            path.unlink()

    def healthcheck(self) -> bool:
        return self._root.is_dir()
