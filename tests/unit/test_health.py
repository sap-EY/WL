"""Smoke tests for the health endpoints."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from wabot.api.routers import health as health_module
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
async def test_metrics_endpoint_exposes_text() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/metrics")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")


@pytest.mark.asyncio
async def test_readyz_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_ping() -> bool:
        return True

    monkeypatch.setattr(health_module, "db_ping", _fake_ping)
    monkeypatch.setattr(health_module, "redis_ping", _fake_ping)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/readyz")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["dependencies"] == {"db": True, "redis": True}


@pytest.mark.asyncio
async def test_readyz_db_down_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _ok() -> bool:
        return True

    async def _down() -> bool:
        return False

    monkeypatch.setattr(health_module, "db_ping", _down)
    monkeypatch.setattr(health_module, "redis_ping", _ok)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/readyz")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["dependencies"] == {"db": False, "redis": True}


@pytest.mark.asyncio
async def test_readyz_redis_down_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _ok() -> bool:
        return True

    async def _down() -> bool:
        return False

    monkeypatch.setattr(health_module, "db_ping", _ok)
    monkeypatch.setattr(health_module, "redis_ping", _down)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/readyz")

    assert resp.status_code == 503
    assert resp.json()["dependencies"] == {"db": True, "redis": False}
