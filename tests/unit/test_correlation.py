"""Verify correlation-id middleware behavior."""

from __future__ import annotations

import re

import pytest
from httpx import ASGITransport, AsyncClient

from wabot.main import app

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


@pytest.mark.asyncio
async def test_correlation_id_generated_when_missing() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/healthz")

    assert resp.status_code == 200
    cid = resp.headers.get("x-correlation-id")
    assert cid is not None
    assert _UUID_RE.match(cid), f"expected a UUID4, got {cid!r}"


@pytest.mark.asyncio
async def test_correlation_id_echoed_when_supplied() -> None:
    supplied = "test-correlation-9f1c2a"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/healthz", headers={"X-Correlation-Id": supplied})

    assert resp.status_code == 200
    assert resp.headers.get("x-correlation-id") == supplied


@pytest.mark.asyncio
async def test_distinct_requests_get_distinct_ids() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        a = await client.get("/healthz")
        b = await client.get("/healthz")

    assert a.headers["x-correlation-id"] != b.headers["x-correlation-id"]
