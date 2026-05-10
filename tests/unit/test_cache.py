"""Unit tests for the cache primitives (Redis client + dedupe key)."""

from __future__ import annotations

from wabot.cache.dedupe import build_dedupe_key


def test_build_dedupe_key_uses_all_three_parts() -> None:
    key = build_dedupe_key(
        event_type="message_api_sent",
        interakt_message_id="abc-123",
        message_status="Sent",
    )
    assert key == "wabot:webhook:dedupe:message_api_sent:abc-123:Sent"


def test_build_dedupe_key_handles_missing_parts() -> None:
    key = build_dedupe_key(
        event_type="message_received",
        interakt_message_id=None,
        message_status=None,
    )
    assert key == "wabot:webhook:dedupe:message_received:-:-"
