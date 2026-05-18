"""Tests for `wabot.adapters.interakt.client.InteraktClient`."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic_settings import SettingsConfigDict

from wabot.adapters.interakt.client import (
    InteraktClient,
    InteraktPermanentError,
    InteraktTransientError,
    build_request_body,
)
from wabot.domain.outbound import InteractiveButton, OutboundIntent


async def _no_sleep(_: float) -> None:
    return None


def _settings() -> Any:
    from wabot.infra.config import get_settings

    return get_settings()


def _text_intent() -> OutboundIntent:
    return OutboundIntent(
        kind="TEXT",
        full_phone_number="919999900001",
        symbol="MSG_TEST",
        text="hello",
    )


def _buttons_intent() -> OutboundIntent:
    return OutboundIntent(
        kind="BUTTONS",
        full_phone_number="919999900001",
        symbol="MSG_TEST",
        text="pick one",
        buttons=(
            InteractiveButton(id="a", title="A"),
            InteractiveButton(id="b", title="B"),
        ),
    )


def _template_intent() -> OutboundIntent:
    return OutboundIntent(
        kind="TEMPLATE",
        full_phone_number="919999900001",
        symbol="TEMPLATE_TEST",
        template_name="welcome_v1",
        body_values=("Dr Smith",),
        button_values={"0": ("yes",)},
    )


class TestBuildRequestBody:
    def test_text_shape(self) -> None:
        body = build_request_body(_text_intent(), callback_data="cb-1")
        assert body == {
            "fullPhoneNumber": "919999900001",
            "callbackData": "cb-1",
            "type": "Text",
            "data": {"message": "hello"},
        }

    def test_buttons_shape(self) -> None:
        body = build_request_body(_buttons_intent(), callback_data="cb-2")
        assert body["type"] == "InteractiveButton"
        assert body["data"]["message"]["type"] == "button"
        assert body["data"]["message"]["body"] == {"text": "pick one"}
        assert [b["reply"]["id"] for b in body["data"]["message"]["action"]["buttons"]] == [
            "a",
            "b",
        ]

    def test_template_shape_no_category(self) -> None:
        body = build_request_body(_template_intent(), callback_data="cb-3")
        assert body["type"] == "Template"
        assert "template_category" not in body
        assert body["template"]["name"] == "welcome_v1"
        assert body["template"]["languageCode"] == "en"
        assert body["template"]["bodyValues"] == ["Dr Smith"]
        assert body["template"]["buttonValues"] == {"0": ["yes"]}


class TestInteraktClientSend:
    @pytest.mark.asyncio
    async def test_dry_run_returns_synthetic_message_without_http_call(self) -> None:
        class DryRunSettings(_settings().__class__):
            model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

        settings = DryRunSettings(
            DB_HOST="localhost",
            DB_USER="user",
            DB_PASSWORD="pw",
            APP_FEATURE_FLAG_DRY_RUN_OUTBOUND=True,
        )
        called = False

        def handler(_: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(500, text="should not be called")

        http = httpx.AsyncClient(
            base_url="https://api.interakt.ai", transport=httpx.MockTransport(handler)
        )
        client = InteraktClient(settings, http_client=http, sleep=_no_sleep)
        try:
            result = await client.send(_text_intent(), callback_data="cb-dry")
        finally:
            await http.aclose()

        assert called is False
        assert result.interakt_message_id == "dry-run:cb-dry"
        assert result.raw_response["dry_run"] is True
        assert result.raw_response["request"]["type"] == "Text"

    @pytest.mark.asyncio
    async def test_success_returns_message_id(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["headers"] = dict(request.headers)
            captured["json"] = json.loads(request.content)
            return httpx.Response(
                200, json={"result": True, "id": "interakt-id-1", "message": "ok"}
            )

        transport = httpx.MockTransport(handler)
        http = httpx.AsyncClient(
            base_url="https://api.interakt.ai",
            transport=transport,
            headers={"Authorization": "Basic key", "Content-Type": "application/json"},
        )
        client = InteraktClient(_settings(), http_client=http, sleep=_no_sleep)
        try:
            result = await client.send(_text_intent(), callback_data="cb-1")
        finally:
            await http.aclose()
        assert result.interakt_message_id == "interakt-id-1"
        assert captured["json"]["type"] == "Text"
        assert captured["json"]["callbackData"] == "cb-1"

    @pytest.mark.asyncio
    async def test_4xx_raises_permanent(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(400, text="bad request")

        http = httpx.AsyncClient(
            base_url="https://api.interakt.ai", transport=httpx.MockTransport(handler)
        )
        client = InteraktClient(_settings(), http_client=http, sleep=_no_sleep)
        try:
            with pytest.raises(InteraktPermanentError):
                await client.send(_text_intent(), callback_data="cb")
        finally:
            await http.aclose()

    @pytest.mark.asyncio
    async def test_5xx_retries_then_succeeds(self) -> None:
        attempts = {"count": 0}

        def handler(_: httpx.Request) -> httpx.Response:
            attempts["count"] += 1
            if attempts["count"] < 3:
                return httpx.Response(503, text="upstream")
            return httpx.Response(200, json={"result": True, "id": "ok-id"})

        http = httpx.AsyncClient(
            base_url="https://api.interakt.ai", transport=httpx.MockTransport(handler)
        )
        client = InteraktClient(_settings(), http_client=http, sleep=_no_sleep)
        try:
            result = await client.send(_text_intent(), callback_data="cb")
        finally:
            await http.aclose()
        assert result.interakt_message_id == "ok-id"
        assert attempts["count"] == 3

    @pytest.mark.asyncio
    async def test_5xx_exhausts_retries(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="boom")

        http = httpx.AsyncClient(
            base_url="https://api.interakt.ai", transport=httpx.MockTransport(handler)
        )
        client = InteraktClient(_settings(), http_client=http, sleep=_no_sleep)
        try:
            with pytest.raises(InteraktTransientError):
                await client.send(_text_intent(), callback_data="cb")
        finally:
            await http.aclose()

    @pytest.mark.asyncio
    async def test_result_false_is_permanent(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"result": False, "message": "rejected"})

        http = httpx.AsyncClient(
            base_url="https://api.interakt.ai", transport=httpx.MockTransport(handler)
        )
        client = InteraktClient(_settings(), http_client=http, sleep=_no_sleep)
        try:
            with pytest.raises(InteraktPermanentError):
                await client.send(_text_intent(), callback_data="cb")
        finally:
            await http.aclose()
