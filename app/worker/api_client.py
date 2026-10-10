"""Tiny HTTP client the worker uses to talk to the API (stdlib only; no extra dependency).
Authenticates as role ``service`` (dev auth header). FUTURE: a service token when auth_mode=token."""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)


class ApiError(RuntimeError):
    pass


class ApiClient:
    def __init__(self, base_url: str, prefix: str = "/api", timeout: float = 15.0) -> None:
        self.base = base_url.rstrip("/") + prefix
        self.timeout = timeout
        self.headers = {"X-Dev-Role": "service", "X-Dev-User": "vision-worker", "Content-Type": "application/json"}

    def _call(self, method: str, path: str, payload=None, retries: int = 2, params: dict | None = None):
        url = self.base + path + (("?" + urllib.parse.urlencode(params)) if params else "")
        data = json.dumps(payload).encode() if payload is not None else None
        for attempt in range(retries + 1):
            req = urllib.request.Request(url, data=data, method=method, headers=self.headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = resp.read()
                    return json.loads(body) if body else None
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace")[:500]
                if exc.code < 500 or attempt == retries:
                    raise ApiError(f"{method} {path} -> {exc.code}: {detail}") from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt == retries:
                    raise ApiError(f"{method} {path} failed: {exc}") from None
            time.sleep(1.5 * (attempt + 1))
        return None

    def get(self, path: str, **params):
        return self._call("GET", path, params=params or None)

    def post(self, path: str, payload, retries: int = 2):
        return self._call("POST", path, payload, retries=retries)
