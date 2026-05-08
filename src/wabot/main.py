"""FastAPI application factory and ASGI entrypoint.

Phase 1 wiring:
- structlog logging configured at startup (also covers stdlib loggers).
- `CorrelationMiddleware` binds `X-Correlation-Id` for every request and
  echoes it on the response.
- Typed exceptions and a stable error envelope are registered.

The public surface (`create_app`, module-level `app`) is unchanged from
Phase 0; later phases plug in webhook and admin routers without further
changes here.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI

from wabot import __version__
from wabot.api.routers import health
from wabot.data.db import dispose_engine, get_engine
from wabot.infra.config import AppSettings, get_settings
from wabot.infra.correlation import CorrelationMiddleware
from wabot.infra.errors import register_exception_handlers
from wabot.infra.logging import configure_logging, get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = get_logger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan hook.

    Configures logging, primes the async DB engine, and emits a
    structured startup event. Disposes the engine on shutdown. Later
    phases will open the Redis pool and HTTP clients here too.
    """
    settings: AppSettings = get_settings()
    configure_logging(settings)
    get_engine(settings)
    logger.info(
        "wabot.startup",
        db=settings.db_dsn_for_logging,
        broker=settings.broker_backend,
        log_json=settings.log_json,
    )
    try:
        yield
    finally:
        await dispose_engine()
        logger.info("wabot.shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    # Configure logging eagerly so import-time logs share the same structure
    # even before lifespan runs (e.g. under gunicorn worker preload).
    configure_logging(settings)

    app = FastAPI(
        title="Wockhardt WhatsApp Bot",
        version=__version__,
        docs_url="/docs" if settings.env != "prod" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.env != "prod" else None,
        lifespan=_lifespan,
    )
    app.add_middleware(CorrelationMiddleware)
    register_exception_handlers(app)
    _register_routes(app)
    return app


def _register_routes(app: FastAPI) -> None:
    app.include_router(health.router)
    # Future phases:
    #   from wabot.api.routers import webhooks, admin
    #   app.include_router(webhooks.router, prefix="/webhooks")
    #   app.include_router(admin.router, prefix="/admin")


# ASGI target for uvicorn / gunicorn.
app = create_app()
