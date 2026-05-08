"""FastAPI application factory and ASGI entrypoint.

Final shape for Phase 0: a minimal-but-real app exposing `/healthz` and
`/readyz`. Routers for webhooks/admin will be plugged into `_register_routes`
in subsequent phases without changing this module's public surface.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI

from wabot import __version__
from wabot.api.routers import health
from wabot.infra.config import AppSettings, get_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan hook.

    Phase 0: just log startup/shutdown. Phase 1+ will open the DB engine,
    Redis pool, and HTTP clients here, and close them on shutdown.
    """
    settings: AppSettings = get_settings()
    logger.info(
        "wabot.startup app=%s env=%s version=%s db=%s",
        settings.name,
        settings.env,
        __version__,
        settings.db_dsn_for_logging,
    )
    try:
        yield
    finally:
        logger.info("wabot.shutdown app=%s", settings.name)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Wockhardt WhatsApp Bot",
        version=__version__,
        docs_url="/docs" if settings.env != "prod" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.env != "prod" else None,
        lifespan=_lifespan,
    )
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
