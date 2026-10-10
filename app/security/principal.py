from __future__ import annotations

from dataclasses import dataclass

from app.core.enums import Role


@dataclass(frozen=True)
class Principal:
    subject: str
    role: Role
