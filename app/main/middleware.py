from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware

from app.shared.logging_setup import request_id_var

logger = logging.getLogger("oceaneye.access")
_SAFE_RID = re.compile(r"^[A-Za-z0-9\-]{8,64}$")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Request-id correlation + access log (HTTP only; WebSockets log in their handler)."""

    async def dispatch(self, request, call_next):
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if _SAFE_RID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(rid)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        logger.info("%s %s -> %s", request.method, request.url.path, response.status_code,
                    extra={"request_id": rid, "duration_ms": round((time.perf_counter() - start) * 1000, 1)})
        return response
