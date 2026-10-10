"""Request-validation helpers shared by API schemas."""
from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import urlparse

SAFE_ID_PATTERN = r"^[A-Za-z0-9_\-]{1,64}$"
_STORAGE_KEY_RE = re.compile(r"^[A-Za-z0-9_\-./]{1,200}$")
DEFAULT_STREAM_SCHEMES = ("rtsp", "rtsps", "http", "https", "mock")


def validate_stream_url(url: str, allowed_schemes: Iterable[str] = DEFAULT_STREAM_SCHEMES) -> str:
    parsed = urlparse(url)
    if parsed.scheme.lower() not in set(allowed_schemes):
        raise ValueError(f"stream_url scheme must be one of {sorted(set(allowed_schemes))}")
    if not (parsed.netloc or parsed.scheme.lower() == "mock"):
        raise ValueError("stream_url must include a host")
    return url


def validate_storage_key(key: str) -> str:
    if not _STORAGE_KEY_RE.match(key) or ".." in key or key.startswith("/"):
        raise ValueError("invalid storage key")
    return key
