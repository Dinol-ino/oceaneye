"""Tiny HTTP client the worker uses to talk to the API (stdlib only; no extra dependency).
Authenticates as role ``service`` (dev auth header). FUTURE: a service token when auth_mode=token."""
from __future__ import annotations

import json
import logging
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)


class ApiError(RuntimeError):
    pass


class ApiClient:
    def __init__(self, base_url: str, prefix: str = "/api", timeout: float = 15.0,
                 cafile: "str | Path | None" = None) -> None:
        self.base = base_url.rstrip("/") + prefix
        self.timeout = timeout
        self.headers = {"X-Dev-Role": "service", "X-Dev-User": "vision-worker", "Content-Type": "application/json"}
        self._ssl = self._build_ssl_context(base_url, cafile)

    @staticmethod
    def _build_ssl_context(base_url: str, cafile) -> "ssl.SSLContext | None":
        """Trust the installation's own certificate, rather than switching verification off.

        The prototype serves TLS with a self-signed certificate, which no default trust store
        knows, so a worker would fail verification against its own API. Loading that exact
        certificate as the trust anchor fixes it while keeping hostname and signature checks on -
        an unverified context here would be a permanent hole in a safety system, kept alive by the
        fact that it appears to work.
        """
        if not base_url.lower().startswith("https"):
            return None
        context = ssl.create_default_context()
        if cafile and Path(cafile).is_file():
            context.load_verify_locations(cafile=str(cafile))
            logger.info("worker trusts the installation certificate at %s", cafile)
        else:
            logger.warning("TLS API at %s but no certificate given to trust; verification will use "
                           "the system store and will fail against a self-signed certificate",
                           base_url)
        return context

    def _call(self, method: str, path: str, payload=None, retries: int = 2, params: dict | None = None):
        url = self.base + path + (("?" + urllib.parse.urlencode(params)) if params else "")
        data = json.dumps(payload).encode() if payload is not None else None
        for attempt in range(retries + 1):
            req = urllib.request.Request(url, data=data, method=method, headers=self.headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout, context=self._ssl) as resp:
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
