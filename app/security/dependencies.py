"""Centralised FastAPI auth dependencies: every protected route uses require_roles()."""
from __future__ import annotations

from fastapi import Depends, Request

from app.core.enums import Role
from app.security.authentication import Credentials
from app.security.authorization import authorize
from app.security.principal import Principal


async def get_current_principal(request: Request) -> Principal:
    authenticator = request.app.state.container.authenticator
    # Query-string credentials are only honoured on WebSocket handshakes, never on HTTP.
    return authenticator.authenticate(Credentials(headers=dict(request.headers)))


def require_roles(*roles: Role):
    async def _dependency(principal: Principal = Depends(get_current_principal)) -> Principal:
        authorize(principal, roles)
        return principal

    return _dependency
