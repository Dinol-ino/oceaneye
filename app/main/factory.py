"""Application factory + lifespan (startup/shutdown flow)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.alerts.api.push import router as push_router
from app.alerts.api.router import router as alerts_router
from app.camera.api.router import router as camera_router
from app.config.settings import Settings, get_settings
from app.core.interfaces.clock import Clock
from app.environment.api.router import router as environment_router
from app.environment.api.tiles import router as tiles_router
from app.events.api.router import router as events_router
from app.evidence.api.router import router as evidence_router
from app.main import health
from app.main.container import build_container
from app.main.error_handlers import register_error_handlers
from app.main.middleware import RequestContextMiddleware
from app.processing.api.router import router as processing_router
from app.security.middleware import SecurityHeadersMiddleware
from app.shared.logging_setup import configure_logging
from app.websocket.router import router as ws_router

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parents[1] / "web" / "static"


def create_app(settings: Settings | None = None, clock: Clock | None = None, launcher=None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)           # 1. logging
    container = build_container(settings, clock, launcher)             # 2-6. persistence, repos, services, alerts, ws

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        import asyncio
        import sys
        if sys.platform == "win32":
            loop = asyncio.get_running_loop()
            orig = loop.get_exception_handler()

            def _filter_winerror10054(lp, ctx):
                exc = ctx.get("exception")
                msg = str(ctx.get("message") or "")
                if isinstance(exc, ConnectionResetError) or (isinstance(exc, OSError) and getattr(exc, "winerror", None) == 10054):
                    return
                if "WinError 10054" in msg or "forcibly closed by the remote host" in msg:
                    return
                if orig:
                    orig(lp, ctx)
                else:
                    lp.default_exception_handler(ctx)

            loop.set_exception_handler(_filter_winerror10054)

        await container.start()
        logger.info("OceanEye API ready")
        yield
        await container.stop()

    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan,
                  docs_url="/docs" if settings.environment != "production" else None,
                  redoc_url=None, openapi_url="/openapi.json" if settings.environment != "production" else None)
    app.state.container = container

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                           allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"], allow_headers=["*"])
    register_error_handlers(app)

    app.include_router(health.router)                                   # /health, /ready
    for r in (camera_router, environment_router, tiles_router, events_router, alerts_router,
              evidence_router, processing_router, push_router):
        app.include_router(r, prefix=settings.api_prefix)
    app.include_router(ws_router)                                       # /ws/alerts

    _mount_web(app)
    return app


def _mount_web(app: FastAPI) -> None:
    """Serve the three operator interfaces (plain HTML/JS, no build step).

    The service worker is also served from the site root. A worker's *scope* can never be broader
    than the path it was served from, so ``/sw.js`` is what lets one worker handle the Control Room,
    the Lifeguard app and Video Analysis - which is what makes all three installable to a phone's
    home screen from the same origin.
    """
    if not WEB_DIR.is_dir():  # pragma: no cover - only in a trimmed deployment
        logger.warning("web interface directory missing: %s", WEB_DIR)
        return
    app.mount("/ui", StaticFiles(directory=WEB_DIR, html=True), name="ui")

    for root_file, media_type in (("sw.js", "text/javascript"), ("offline.html", "text/html")):
        _serve_root_file(app, root_file, media_type)

    @app.get("/", include_in_schema=False)
    async def _root():
        return RedirectResponse("/ui/")


def _serve_root_file(app: FastAPI, name: str, media_type: str) -> None:
    from fastapi.responses import FileResponse, Response  # noqa: PLC0415 - local to the mount helper

    @app.get(f"/{name}", include_in_schema=False, name=f"root_{name.replace('.', '_')}")
    async def _file():  # noqa: ANN202
        path = WEB_DIR / name
        if not path.is_file():
            return Response(status_code=404)
        # Never cached: a stale service worker would pin every client to an old build.
        return FileResponse(path, media_type=media_type,
                            headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})
