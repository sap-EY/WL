"""Smoke tests for the Phase 0 health endpoints."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from wabot.main import app


@pytest.mark.asyncio
async def test_healthz_ok() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/healthz")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["app"] == "wabot"
    assert body["env"] in {"local", "dev", "staging", "prod"}
    assert body.get("version")
    assert "time" in body


@pytest.mark.asyncio
async def test_readyz_ok() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/readyz")

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
