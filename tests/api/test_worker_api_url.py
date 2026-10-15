"""Workers must reach the API over the scheme the API actually serves.

REGRESSION. ``worker_api_url`` was hardcoded to "http://127.0.0.1:8000". The moment TLS was
switched on in .env, every worker made a plaintext request to a TLS socket, which the server
closes without replying. The worker died with "Remote end closed connection without response" and
the Control Room showed only "worker exited with code 1" - so live camera monitoring AND video
analysis both failed, with nothing on screen pointing at the cause.
"""
from __future__ import annotations

import ssl
from pathlib import Path

from app.config.settings import Settings
from app.worker.api_client import ApiClient

CERT = {"ssl_certfile": Path("data/certs/cert.pem"), "ssl_keyfile": Path("data/certs/key.pem")}


def settings(**kw) -> Settings:
    # _env_file=None so a developer's real .env cannot change the answer.
    return Settings(_env_file=None, **kw)


def test_worker_url_follows_plain_http_when_tls_is_off():
    assert settings().worker_api_url == "http://127.0.0.1:8000"


def test_worker_url_switches_to_https_when_tls_is_on():
    assert settings(**CERT).worker_api_url == "https://127.0.0.1:8000"


def test_a_bind_all_host_becomes_loopback_for_the_worker():
    """run_api.py --lan binds 0.0.0.0. That is an address to listen on, not one to connect to."""
    assert settings(host="0.0.0.0").worker_api_url == "http://127.0.0.1:8000"


def test_a_custom_port_is_carried_through():
    assert settings(port=9100).worker_api_url == "http://127.0.0.1:9100"


def test_an_explicit_url_still_wins():
    """A worker on another host must stay configurable."""
    assert settings(worker_api_url="http://10.0.0.5:8000").worker_api_url == "http://10.0.0.5:8000"


def test_the_client_verifies_tls_rather_than_skipping_it():
    """Verification stays ON. An unverified context would be a permanent hole in a safety system,
    kept alive by the fact that it appears to work."""
    assert ApiClient("http://127.0.0.1:8000")._ssl is None  # no TLS, no context needed

    secure = ApiClient("https://127.0.0.1:8000")
    assert isinstance(secure._ssl, ssl.SSLContext)
    assert secure._ssl.verify_mode == ssl.CERT_REQUIRED
    assert secure._ssl.check_hostname is True
