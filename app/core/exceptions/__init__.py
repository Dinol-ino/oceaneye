"""Framework-independent exception hierarchy. The API layer maps these to HTTP."""
from __future__ import annotations

from typing import Any


class OceanEyeError(Exception):
    code = "internal_error"

    def __init__(self, message: str = "", *, details: Any = None) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code
        self.details = details


class DomainValidationError(OceanEyeError):
    code = "validation_error"


class NotFoundError(OceanEyeError):
    code = "not_found"

    def __init__(self, resource: str, identifier: str) -> None:
        super().__init__(f"{resource} '{identifier}' not found")
        self.resource = resource
        self.identifier = identifier


class ConflictError(OceanEyeError):
    code = "conflict"


class InvalidStateTransition(ConflictError):
    code = "invalid_state_transition"


class AuthenticationError(OceanEyeError):
    code = "authentication_required"


class AuthorizationError(OceanEyeError):
    code = "forbidden"


class NotImplementedFeature(OceanEyeError):
    """Raised by scaffold stubs for functionality that is intentionally not built yet."""

    code = "not_implemented"


class ConfigurationError(OceanEyeError):
    code = "configuration_error"


class SourceOpenError(OceanEyeError):
    """A video source (file / webcam / stream) could not be opened or read."""

    code = "source_open_failed"
