"""GenAI port — protocol contract used by the registered-journey handler.

Phase 8 ships the protocol + a `StubGenAIPort` that always returns a
fallback response. Phase 9 will implement the real `httpx`-backed
adapter under `wabot.adapters.genai.client` and the worker will wire
that implementation in place of the stub.

Keeping the protocol in `domain/ports/` (and not in `adapters/`)
guarantees the journey handler never imports adapter code directly —
the dependency direction stays Domain → Port ← Adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

QueryNature = Literal["scientific", "non_scientific"]
IntentLabel = Literal["answer", "hotline", "fallback"]


class GenAIServiceError(RuntimeError):
    """Raised by adapters when the GenAI call cannot produce a valid response.

    The journey handler catches this and emits the GenAI-failed fallback;
    transient retries / circuit breaker live inside the adapter (Phase 9).
    """


@dataclass(frozen=True, slots=True)
class GenAIRequest:
    """Input to the GenAI port. Mirrors implementation_plan.md §14.2."""

    conversation_id: str
    doctor_id: str
    user_message: str
    current_state: str
    locale: str = "en"
    recent_turns: tuple[dict[str, str], ...] = ()
    summary_context: str = ""


@dataclass(frozen=True, slots=True)
class GenAIResponse:
    """Subset of the GenAI response shape the journey handler cares about.

    The full response schema lives in §14.3; Phase 8 uses only the fields
    that drive state transitions. Phase 9's real adapter parses the wire
    response and produces this dataclass.
    """

    intent: IntentLabel
    query_nature: QueryNature
    answer_text: str
    app_link: str | None = None
    send_processing_message: bool = False
    show_answer_buttons: bool = False
    requires_hotline: bool = False
    meta: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class GenAIPort(Protocol):
    """Async port the registered-journey handler depends on.

    Implementations are responsible for retries, timeouts, circuit
    breaking, and audit logging (the `genai_interaction` table). The
    handler treats any failure as `GenAIServiceError` and emits the
    fallback message.
    """

    async def generate(self, request: GenAIRequest) -> GenAIResponse: ...


class StubGenAIPort:
    """Default port wired before Phase 9. Always raises `GenAIServiceError`.

    This forces the journey handler down the fallback branch in any
    environment that has not registered a real adapter, which is the
    safe default — we never want production traffic to hit a silent
    stub answer.
    """

    async def generate(self, request: GenAIRequest) -> GenAIResponse:
        del request
        msg = "GenAI port not configured (StubGenAIPort active)."
        raise GenAIServiceError(msg)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


_active_port: GenAIPort = StubGenAIPort()


def register_genai_port(port: GenAIPort) -> None:
    """Install `port` as the active implementation. Phase 9 calls this."""
    global _active_port  # noqa: PLW0603 - module-level registry
    _active_port = port


def get_genai_port() -> GenAIPort:
    """Return the currently registered GenAI port (or the stub)."""
    return _active_port


def reset_genai_port_for_tests() -> None:
    """Restore the stub. Test-only seam."""
    global _active_port  # noqa: PLW0603 - module-level registry
    _active_port = StubGenAIPort()


__all__ = [
    "GenAIPort",
    "GenAIRequest",
    "GenAIResponse",
    "GenAIServiceError",
    "StubGenAIPort",
    "get_genai_port",
    "register_genai_port",
    "reset_genai_port_for_tests",
]
