"""Authentication boundary. Authenticators turn request credentials into a Principal.

PLACEHOLDERS: no production identity provider is built yet.
- DevHeaderAuthenticator trusts X-Dev-Role / X-Dev-User. DEVELOPMENT ONLY - Settings refuse
  auth_mode=dev in production.
- TokenAuthenticator is the future home of real token verification (JWT/OAuth/etc.).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Mapping

from app.core.enums import Role
from app.core.exceptions import AuthenticationError, NotImplementedFeature
from app.security.principal import Principal


@dataclass(frozen=True)
class Credentials:
    headers: Mapping[str, str] = field(default_factory=dict)
    query: Mapping[str, str] = field(default_factory=dict)  # only populated for WebSocket handshakes


class Authenticator(ABC):
    @abstractmethod
    def authenticate(self, credentials: Credentials) -> Principal:
        """Return a Principal or raise AuthenticationError."""


class DevHeaderAuthenticator(Authenticator):
    def authenticate(self, credentials: Credentials) -> Principal:
        role_raw = credentials.headers.get("x-dev-role") or credentials.query.get("dev_role")
        subject = credentials.headers.get("x-dev-user") or credentials.query.get("dev_user") or "dev-user"
        if not role_raw:
            raise AuthenticationError("Authentication required")
        try:
            return Principal(subject=subject[:64], role=Role(role_raw))
        except ValueError:
            raise AuthenticationError("Authentication required") from None


class TokenAuthenticator(Authenticator):
    """TODO(security): verify bearer tokens using settings.secret_key / an identity provider."""

    def authenticate(self, credentials: Credentials) -> Principal:
        raise NotImplementedFeature("Token authentication is not implemented yet")
