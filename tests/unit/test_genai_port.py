"""Tests for `wabot.domain.ports.genai` (stub + registry)."""

from __future__ import annotations

import pytest

from wabot.domain.ports.genai import (
    GenAIRequest,
    GenAIResponse,
    GenAIServiceError,
    StubGenAIPort,
    get_genai_port,
    register_genai_port,
    reset_genai_port_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_port() -> None:
    reset_genai_port_for_tests()


@pytest.mark.asyncio
async def test_stub_port_always_raises_service_error() -> None:
    port = StubGenAIPort()
    with pytest.raises(GenAIServiceError):
        await port.generate(
            GenAIRequest(
                conversation_id="c",
                doctor_id="d",
                user_message="hi",
                current_state="AWAITING_FREE_TEXT",
            )
        )


def test_registry_default_is_stub() -> None:
    assert isinstance(get_genai_port(), StubGenAIPort)


@pytest.mark.asyncio
async def test_registry_swap_replaces_active_port() -> None:
    class _Echo:
        async def generate(self, request: GenAIRequest) -> GenAIResponse:
            return GenAIResponse(
                intent="answer",
                query_nature="non_scientific",
                answer_text=request.user_message.upper(),
            )

    register_genai_port(_Echo())
    response = await get_genai_port().generate(
        GenAIRequest(
            conversation_id="c",
            doctor_id="d",
            user_message="hello",
            current_state="AWAITING_FREE_TEXT",
        )
    )
    assert response.answer_text == "HELLO"
