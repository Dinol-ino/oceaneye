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

#: Installation-level actions: changing which beach is watched, de-registering a lifeguard's phone.
#:
#: OPERATOR is included deliberately. OceanEye is deployed for ONE beach and run by that beach's
#: authority, where the person who configures the site is the same person who watches it. A
#: separate administrator produced no real separation of duty - it only meant the control room's
#: own setup dialog failed with "Insufficient permissions". Role.ADMINISTRATOR is kept in the enum
#: and still accepted, so stored principals remain valid and a genuine multi-site deployment can
#: narrow this back to (Role.ADMINISTRATOR,) in one line.
ADMIN_ROLES = (Role.OPERATOR, Role.ADMINISTRATOR)
EVENT_PRODUCER_ROLES = (Role.SERVICE, Role.ADMINISTRATOR)


def authorize(principal: Principal, allowed: Iterable[Role]) -> None:
    if principal.role not in set(allowed):
        raise AuthorizationError("Insufficient permissions")
