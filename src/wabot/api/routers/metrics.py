"""Prometheus-compatible metrics endpoint."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from wabot.infra.config import get_settings
from wabot.infra.metrics import render_metrics

router = APIRouter(tags=["metrics"])


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    settings = get_settings()
    if not settings.metrics_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return Response(render_metrics(), media_type="text/plain; version=0.0.4")
