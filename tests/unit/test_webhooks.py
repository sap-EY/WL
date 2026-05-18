"""Tests for the Interakt webhook ingestion endpoint.

The router has three external dependencies (Redis dedupe, the DB-backed
`WebhookRepository`, and the broker). Each is replaced with an
in-memory fake so the test exercises the orchestration logic without
opening real connections.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from wabot.adapters.broker import factory as broker_factory
from wabot.api.routers import webhooks as webhooks_router
from wabot.api.schemas.interakt_webhook import EVENT_TYPE_API_CLICKED, EVENT_TYPE_RECEIVED
from wabot.infra.config import get_settings
from wabot.infra.correlation import CorrelationMiddleware
from wabot.infra.errors import register_exception_handlers


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    get_settings.cache_clear()


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CorrelationMiddleware)
    register_exception_handlers(app)
    app.include_router(webhooks_router.router)
    return app


def _sample_received_payload() -> dict[str, Any]:
    return {
        "version": "1.0",
        "timestamp": "2024-06-10T08:38:08.837610",
        "type": EVENT_TYPE_RECEIVED,
        "data": {
            "customer": {
                "channel_phone_number": "917003705584",
                "phone_number": "7003705584",
                "country_code": "+91",
            },
            "message": {
                "id": str(uuid.uuid4()),
                "message_status": "Sent",
                "is_template_message": False,
                "message_content_type": "Text",
                "message": "Hello",
                "meta_data": {},
            },
        },
    }


class _FakeBroker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def enqueue(self, *, partition_key: str, payload: dict[str, Any]) -> str:
        self.calls.append((partition_key, payload))
        return "0-1"

    async def close(self) -> None:
        return


class _FakeRepoFactory:
    def __init__(self, *, is_new: bool = True) -> None:
        self.is_new = is_new
        self.recorded: list[dict[str, Any]] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        @asynccontextmanager
        async def _scope():  # type: ignore[no-untyped-def]
            yield MagicMock()

        monkeypatch.setattr(webhooks_router, "session_scope", _scope)

        repo_instance = MagicMock()
        row = MagicMock()
        row.id = uuid.uuid4()

        async def _record_if_new(**kwargs: Any) -> tuple[Any, bool]:
            self.recorded.append(kwargs)
            return row, self.is_new

        repo_instance.record_if_new = AsyncMock(side_effect=_record_if_new)

        def _ctor(_session: Any) -> Any:
            return repo_instance

        monkeypatch.setattr(webhooks_router, "WebhookRepository", _ctor)


def _install_dedupe(monkeypatch: pytest.MonkeyPatch, *, claim_returns: bool) -> None:
    fake = MagicMock()
    fake.claim = AsyncMock(return_value=claim_returns)
    monkeypatch.setattr(webhooks_router, "WebhookDedupe", lambda: fake)


@pytest.fixture
def secret() -> str:
    return get_settings().interakt_webhook_path_secret.get_secret_value()


@pytest.mark.asyncio
async def test_webhook_rejects_wrong_secret_with_404(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post("/webhooks/wrong-secret/interakt", json={"type": "x"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_webhook_rejects_invalid_envelope_with_400(
    monkeypatch: pytest.MonkeyPatch, secret: str
) -> None:
    _install_dedupe(monkeypatch, claim_returns=True)
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(f"/webhooks/{secret}/interakt", json={"missing": "type"})
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "validation_failed"


@pytest.mark.asyncio
async def test_webhook_persists_and_enqueues_known_event(
    monkeypatch: pytest.MonkeyPatch, secret: str
) -> None:
    _install_dedupe(monkeypatch, claim_returns=True)
    repo_factory = _FakeRepoFactory(is_new=True)
    repo_factory.install(monkeypatch)
    fake_broker = _FakeBroker()
    broker_calls: list[str] = []
    monkeypatch.setattr(
        webhooks_router,
        "get_broker",
        lambda settings, *, queue="inbound": broker_calls.append(queue) or fake_broker,
    )

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            f"/webhooks/{secret}/interakt",
            json=_sample_received_payload(),
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["event_id"]
    assert len(repo_factory.recorded) == 1
    assert repo_factory.recorded[0]["event_type"] == EVENT_TYPE_RECEIVED
    assert repo_factory.recorded[0]["full_phone_number"] == "917003705584"
    assert len(fake_broker.calls) == 1
    assert broker_calls == ["inbound"]
    partition, payload = fake_broker.calls[0]
    assert partition == "917003705584"
    assert payload["type"] == EVENT_TYPE_RECEIVED


@pytest.mark.asyncio
async def test_webhook_short_circuits_on_redis_dedupe(
    monkeypatch: pytest.MonkeyPatch, secret: str
) -> None:
    _install_dedupe(monkeypatch, claim_returns=False)
    fake_broker = _FakeBroker()
    monkeypatch.setattr(
        webhooks_router,
        "get_broker",
        lambda settings, *, queue="inbound": fake_broker,
    )

    repo_factory = _FakeRepoFactory(is_new=True)
    repo_factory.install(monkeypatch)

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            f"/webhooks/{secret}/interakt",
            json=_sample_received_payload(),
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "duplicate"
    # Neither DB nor broker should have been touched.
    assert repo_factory.recorded == []
    assert fake_broker.calls == []


@pytest.mark.asyncio
async def test_webhook_returns_duplicate_when_db_already_has_row(
    monkeypatch: pytest.MonkeyPatch, secret: str
) -> None:
    _install_dedupe(monkeypatch, claim_returns=True)
    repo_factory = _FakeRepoFactory(is_new=False)
    repo_factory.install(monkeypatch)
    fake_broker = _FakeBroker()
    monkeypatch.setattr(
        webhooks_router,
        "get_broker",
        lambda settings, *, queue="inbound": fake_broker,
    )

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            f"/webhooks/{secret}/interakt",
            json=_sample_received_payload(),
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "duplicate"
    assert fake_broker.calls == []  # no enqueue on DB-side duplicate


@pytest.mark.asyncio
async def test_webhook_handles_click_event(monkeypatch: pytest.MonkeyPatch, secret: str) -> None:
    _install_dedupe(monkeypatch, claim_returns=True)
    repo_factory = _FakeRepoFactory(is_new=True)
    repo_factory.install(monkeypatch)
    fake_broker = _FakeBroker()
    broker_calls: list[str] = []
    monkeypatch.setattr(
        webhooks_router,
        "get_broker",
        lambda settings, *, queue="inbound": broker_calls.append(queue) or fake_broker,
    )

    payload = _sample_received_payload()
    payload["type"] = EVENT_TYPE_API_CLICKED
    payload["event"] = {
        "callbackData": "out-id|corr-id",
        "click_type": "QR",
        "button_text": "Yes",
    }

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(f"/webhooks/{secret}/interakt", json=payload)

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert len(fake_broker.calls) == 1
    assert broker_calls == ["status"]


@pytest.fixture(autouse=True)
def _clear_broker_singleton() -> None:
    broker_factory.set_broker(None)
