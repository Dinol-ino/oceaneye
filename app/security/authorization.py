"""Authorization boundary: role-based access. Detailed permissions are intentionally not
invented; routes declare which roles may call them."""
from __future__ import annotations

from typing import Iterable

from app.core.enums import Role
from app.core.exceptions import AuthorizationError
from app.security.principal import Principal

# Role groups used by route declarations (PROPOSED SCAFFOLD).
HUMAN_ROLES = (Role.OPERATOR, Role.LIFEGUARD, Role.ADMINISTRATOR)
RESPONDER_ROLES = HUMAN_ROLES
MANAGEMENT_ROLES = (Role.OPERATOR, Role.ADMINISTRATOR)
ADMIN_ROLES = (Role.ADMINISTRATOR,)
EVENT_PRODUCER_ROLES = (Role.SERVICE, Role.ADMINISTRATOR)


def authorize(principal: Principal, allowed: Iterable[Role]) -> None:
    if principal.role not in set(allowed):
        raise AuthorizationError("Insufficient permissions")
