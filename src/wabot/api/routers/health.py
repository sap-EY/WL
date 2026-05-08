"""Health and readiness probes.

`/healthz` — liveness; returns 200 if the process is up.
`/readyz`  — readiness; will be extended in later phases to verify DB + Redis.

For Phase 0 the readiness probe also returns 200 because no downstream
clients are wired yet. The contract (status codes, JSON shape) is final.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, status
from pydantic import BaseModel

from wabot import __version__
from wabot.infra.config import get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    app: str
    env: str
    version: str
    time: datetime


def _build_health_response() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        app=settings.name,
        env=settings.env,
        version=__version__,
        time=datetime.now(tz=UTC),
    )


@router.get("/healthz", status_code=status.HTTP_200_OK, response_model=HealthResponse)
async def healthz() -> HealthResponse:
    return _build_health_response()


@router.get("/readyz", status_code=status.HTTP_200_OK, response_model=HealthResponse)
async def readyz() -> HealthResponse:
    # Phase 0: liveness is sufficient. Later phases will probe DB + Redis here.
    return _build_health_response()
