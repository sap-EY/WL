"""Local-only fake GenAI port for end-to-end shake-out before Phase 9.

Activated by `WABOT_USE_FAKE_GENAI=true` in the local `.env`. Never use
this in any deployed environment — Phase 9 wires the real httpx-based
client and registers it the same way (`register_genai_port`).

The fake follows simple keyword heuristics so each branch of the
Registered journey free-text flow can be exercised from a real
WhatsApp conversation without standing up a GenAI service:

* contains "hotline" / "support" / "call"  → intent="hotline".
* starts with "fallback"                   → intent="fallback".
* contains "?" or any medical-keyword hit  → scientific answer +
                                              processing ack +
                                              answer buttons.
* otherwise                                → non-scientific chit-chat.
"""

from __future__ import annotations

from wabot.domain.ports.genai import GenAIRequest, GenAIResponse
from wabot.infra.logging import get_logger

logger = get_logger(__name__)


_HOTLINE_HINTS = ("hotline", "support agent", "call agent", "talk to agent")
_SCIENTIFIC_HINTS = (
    "?",
    "dose",
    "dosage",
    "mg",
    "drug",
    "treatment",
    "diagnos",
    "symptom",
    "interaction",
    "side effect",
    "contraindic",
)


class FakeGenAIPort:
    """In-process GenAI stub for local manual testing."""

    async def generate(self, request: GenAIRequest) -> GenAIResponse:
        message = request.user_message.strip()
        lower = message.lower()
        logger.info("wabot.genai.fake_invoked", message=message)

        if any(hint in lower for hint in _HOTLINE_HINTS):
            return GenAIResponse(
                intent="hotline",
                query_nature="non_scientific",
                answer_text="",
                requires_hotline=True,
                meta={"fake": "true", "branch": "hotline"},
            )

        if lower.startswith("fallback"):
            return GenAIResponse(
                intent="fallback",
                query_nature="non_scientific",
                answer_text="",
                meta={"fake": "true", "branch": "fallback"},
            )

        if any(hint in lower for hint in _SCIENTIFIC_HINTS):
            return GenAIResponse(
                intent="answer",
                query_nature="scientific",
                answer_text=(
                    f"(fake scientific answer) You asked: {message!r}. "
                    "This is a stand-in response from the local fake "
                    "GenAI port. The real adapter ships in Phase 9."
                ),
                app_link="https://example.com/app/doc-stub",
                send_processing_message=True,
                show_answer_buttons=True,
                meta={"fake": "true", "branch": "scientific"},
            )

        return GenAIResponse(
            intent="answer",
            query_nature="non_scientific",
            answer_text=(
                f"(fake reply) Got your message: {message!r}. Ask a "
                "clinical question (try ending with '?') to see the "
                "scientific branch."
            ),
            meta={"fake": "true", "branch": "non_scientific"},
        )


__all__ = ["FakeGenAIPort"]
