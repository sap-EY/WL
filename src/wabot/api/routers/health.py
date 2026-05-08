"""Health and readiness probes.

`/healthz` — liveness; returns 200 if the process is up.
`/readyz`  — readiness; verifies that the database is reachable.

Later phases will extend `/readyz` to probe Redis and the broker. The
response shape (`HealthResponse`) is stable; new dependency-status
fields will be additive.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from wabot import __version__
from wabot.data.db import ping as db_ping
from wabot.infra.config import get_settings

router = APIRouter(tags=["health"])


class DependencyStatus(BaseModel):
    db: bool


class HealthResponse(BaseModel):
    status: str
    app: str
    env: str
    version: str
    time: datetime
    dependencies: DependencyStatus | None = None


def _build_health_response(
    *, dependencies: DependencyStatus | None = None, status_label: str = "ok"
) -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status=status_label,
        app=settings.name,
        env=settings.env,
        version=__version__,
        time=datetime.now(tz=UTC),
        dependencies=dependencies,
    )


@router.get("/healthz", status_code=status.HTTP_200_OK, response_model=HealthResponse)
async def healthz() -> HealthResponse:
    return _build_health_response()


@router.get("/readyz", response_model=HealthResponse)
async def readyz(response: Response) -> HealthResponse:
    db_ok = await db_ping()
    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return _build_health_response(
            dependencies=DependencyStatus(db=False),
            status_label="degraded",
        )
    return _build_health_response(dependencies=DependencyStatus(db=True))
