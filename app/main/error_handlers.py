"""Centralised exception handling -> consistent ErrorResponse. No stack traces or internals leak."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    DomainValidationError,
    NotFoundError,
    NotImplementedFeature,
    OceanEyeError,
)
from app.shared.logging_setup import request_id_var
from app.shared.schemas import ErrorBody, ErrorResponse

logger = logging.getLogger(__name__)

_STATUS: list[tuple[type[OceanEyeError], int]] = [
    (NotFoundError, 404),
    (ConflictError, 409),
    (DomainValidationError, 422),
    (AuthenticationError, 401),
    (AuthorizationError, 403),
    (NotImplementedFeature, 501),
]


def _response(status: int, code: str, message: str, details=None) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=details,
                                         request_id=request_id_var.get()))
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(OceanEyeError)
    async def _domain(_: Request, exc: OceanEyeError):
        for cls, status in _STATUS:
            if isinstance(exc, cls):
                return _response(status, exc.code, exc.message, exc.details)
        logger.error("unhandled domain error", exc_info=exc)
        return _response(500, "internal_error", "Internal server error.")

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        # only loc/msg/type: never echo submitted values
        details = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return _response(422, "request_validation_error", "Request validation failed.", details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        return _response(exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        logger.exception("unhandled exception", exc_info=exc)
        return _response(500, "internal_error", "Internal server error.")
