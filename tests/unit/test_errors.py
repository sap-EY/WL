"""Verify the error envelope for unhandled HTTP errors."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from wabot.main import app


@pytest.mark.asyncio
async def test_unknown_route_returns_envelope() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/this-route-does-not-exist")

    assert resp.status_code == 404
    body = resp.json()
    assert "error" in body
    err = body["error"]
    assert err["code"] == "not_found"
    assert isinstance(err["message"], str) and err["message"]
    assert "correlation_id" in err
    assert err["correlation_id"] == resp.headers.get("x-correlation-id")


@pytest.mark.asyncio
async def test_method_not_allowed_envelope() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post("/healthz", json={})

    assert resp.status_code == 405
    body = resp.json()
    assert body["error"]["code"] == "method_not_allowed"
    assert body["error"]["correlation_id"] == resp.headers.get("x-correlation-id")
