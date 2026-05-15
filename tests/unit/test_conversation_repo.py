"""Tests for `wabot.data.repositories.conversation_repo.ConversationRepository`.

Uses a hand-rolled fake `AsyncSession` so the test exercises the real
repository logic (which `add()` calls happen, which queries fire,
which fields are populated) without needing a live Postgres.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from wabot.data.models.conversation import ConversationMessage, ConversationSession
from wabot.data.repositories.conversation_repo import ConversationRepository
from wabot.domain.enums import MessageDirection


class _FakeSession:
    """Records ``add()`` calls and lets the test script ``execute()``
    return values per call."""

    def __init__(self, *, execute_results: list[Any] | None = None) -> None:
        self.added: list[Any] = []
        self._execute_results = list(execute_results or [])
        self.get = AsyncMock(return_value=None)
        self.flush = AsyncMock()

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def execute(self, _stmt: Any) -> Any:
        if not self._execute_results:
            msg = "FakeSession.execute called more times than scripted"
            raise AssertionError(msg)
        return self._execute_results.pop(0)


def _scalar_result(value: Any) -> MagicMock:
    """Build a fake SQLAlchemy ``Result`` whose ``scalar_one_or_none``
    returns ``value``."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


@pytest.mark.asyncio
async def test_get_or_create_active_session_returns_existing_row() -> None:
    doctor_id = uuid.uuid4()
    existing = ConversationSession(id=uuid.uuid4(), doctor_id=doctor_id)
    session = _FakeSession(execute_results=[_scalar_result(existing)])
    repo = ConversationRepository(session)  # type: ignore[arg-type]

    row = await repo.get_or_create_active_session(doctor_id)

    assert row is existing
    assert session.added == []  # did NOT insert a new row


@pytest.mark.asyncio
async def test_get_or_create_active_session_inserts_when_missing() -> None:
    doctor_id = uuid.uuid4()
    session = _FakeSession(execute_results=[_scalar_result(None)])
    repo = ConversationRepository(session)  # type: ignore[arg-type]

    row = await repo.get_or_create_active_session(doctor_id)

    assert isinstance(row, ConversationSession)
    assert row.doctor_id == doctor_id
    assert row.id is not None
    assert session.added == [row]


@pytest.mark.asyncio
async def test_log_inbound_populates_row_and_adds_to_session() -> None:
    session = _FakeSession()
    repo = ConversationRepository(session)  # type: ignore[arg-type]

    session_id = uuid.uuid4()
    doctor_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    payload = {"foo": "bar"}

    row = await repo.log_inbound(
        session_id=session_id,
        doctor_id=doctor_id,
        text="hello",
        payload=payload,
        interakt_msg_id="im-1",
        correlation_id=correlation_id,
    )

    assert isinstance(row, ConversationMessage)
    assert session.added == [row]
    assert row.session_id == session_id
    assert row.doctor_id == doctor_id
    assert row.direction == MessageDirection.INBOUND
    assert row.text == "hello"
    assert row.payload == payload
    assert row.interakt_msg_id == "im-1"
    assert row.callback_data is None
    assert row.correlation_id == correlation_id


@pytest.mark.asyncio
async def test_log_outbound_populates_row_and_adds_to_session() -> None:
    session = _FakeSession()
    repo = ConversationRepository(session)  # type: ignore[arg-type]

    session_id = uuid.uuid4()
    doctor_id = uuid.uuid4()
    correlation_id = uuid.uuid4()

    row = await repo.log_outbound(
        session_id=session_id,
        doctor_id=doctor_id,
        text="answer body",
        payload={"kind": "TEXT"},
        interakt_msg_id="ix-9",
        callback_data="out-1|corr-1",
        correlation_id=correlation_id,
    )

    assert isinstance(row, ConversationMessage)
    assert session.added == [row]
    assert row.direction == MessageDirection.OUTBOUND
    assert row.text == "answer body"
    assert row.interakt_msg_id == "ix-9"
    assert row.callback_data == "out-1|corr-1"
    assert row.correlation_id == correlation_id


@pytest.mark.asyncio
async def test_touch_updates_last_activity_when_session_exists() -> None:
    session = _FakeSession()
    existing = ConversationSession(id=uuid.uuid4(), doctor_id=uuid.uuid4())
    original_activity = existing.last_activity_at
    session.get = AsyncMock(return_value=existing)
    repo = ConversationRepository(session)  # type: ignore[arg-type]

    await repo.touch(existing.id)

    assert existing.last_activity_at != original_activity


@pytest.mark.asyncio
async def test_touch_is_noop_when_session_missing() -> None:
    session = _FakeSession()
    session.get = AsyncMock(return_value=None)
    repo = ConversationRepository(session)  # type: ignore[arg-type]

    # Must not raise.
    await repo.touch(uuid.uuid4())
