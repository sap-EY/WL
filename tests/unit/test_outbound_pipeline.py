"""Tests for `wabot.services.outbound_pipeline.OutboundPipeline`."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from wabot.adapters.interakt import InteraktPermanentError, InteraktSendResult
from wabot.domain.enums import OutboundKind, OutboundStatus
from wabot.domain.outbound import OutboundIntent
from wabot.services import outbound_pipeline as pipeline_mod
from wabot.services.outbound_pipeline import (
    OutboundPipeline,
    compute_idempotency_key,
)


def _intent(symbol: str = "MSG_TEST", text: str = "hi") -> OutboundIntent:
    return OutboundIntent(
        kind="TEXT",
        full_phone_number="919999900001",
        symbol=symbol,
        text=text,
    )


class _FakeRow:
    def __init__(self, row_id: uuid.UUID) -> None:
        self.id = row_id
        self.callback_data = "PENDING_SEND"
        self.status = OutboundStatus.PENDING_SEND
        self.failed_at: Any = None
        self.failure_reason: Any = None


class _FakeRepo:
    def __init__(self, row: _FakeRow) -> None:
        self._row = row
        self.create_pending = AsyncMock(return_value=row)
        self.mark_sent = AsyncMock()


def _patch_session(monkeypatch: pytest.MonkeyPatch, session: Any) -> None:
    @asynccontextmanager
    async def _scope():
        yield session

    monkeypatch.setattr(pipeline_mod, "session_scope", _scope)


@pytest.mark.asyncio
async def test_dispatch_persists_and_sends(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _FakeRow(uuid.uuid4())
    fake_repo = _FakeRepo(row)
    fake_session = MagicMock()
    fake_session.get = AsyncMock(return_value=row)
    _patch_session(monkeypatch, fake_session)
    monkeypatch.setattr(pipeline_mod, "OutboundRepository", lambda _s: fake_repo)

    client = MagicMock()
    client.send = AsyncMock(
        return_value=InteraktSendResult(interakt_message_id="ix-1", raw_response={"id": "ix-1"})
    )
    pipe = OutboundPipeline(client=client)

    doctor_id = uuid.uuid4()
    correlation_id = str(uuid.uuid4())
    results = await pipe.dispatch(
        [_intent()],
        doctor_id=doctor_id,
        state_when_sent="REGISTRATION_AWAITING_DETAILS",
        correlation_id=correlation_id,
    )

    assert len(results) == 1
    assert results[0].status is OutboundStatus.SENT
    assert results[0].interakt_message_id == "ix-1"

    # callback_data was patched on the fake row before sending.
    call_kwargs = client.send.call_args.kwargs
    assert call_kwargs["callback_data"] == f"{row.id}|{correlation_id}"
    fake_repo.create_pending.assert_awaited_once()
    fake_repo.mark_sent.assert_awaited_once_with(
        row.id, interakt_message_id="ix-1", sent_at=fake_repo.mark_sent.call_args.kwargs["sent_at"]
    )


@pytest.mark.asyncio
async def test_dispatch_marks_failed_on_permanent_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _FakeRow(uuid.uuid4())
    fake_repo = _FakeRepo(row)
    fake_session = MagicMock()
    fake_session.get = AsyncMock(return_value=row)
    _patch_session(monkeypatch, fake_session)
    monkeypatch.setattr(pipeline_mod, "OutboundRepository", lambda _s: fake_repo)

    client = MagicMock()
    client.send = AsyncMock(side_effect=InteraktPermanentError("rejected"))
    pipe = OutboundPipeline(client=client)

    results = await pipe.dispatch(
        [_intent()],
        doctor_id=uuid.uuid4(),
        state_when_sent=None,
        correlation_id=str(uuid.uuid4()),
    )

    assert results[0].status is OutboundStatus.FAILED
    assert results[0].failure_reason == "rejected"
    assert row.status is OutboundStatus.FAILED
    fake_repo.mark_sent.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_isolates_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row1 = _FakeRow(uuid.uuid4())
    row2 = _FakeRow(uuid.uuid4())
    rows = [row1, row2]
    fake_repo = MagicMock()
    fake_repo.create_pending = AsyncMock(side_effect=lambda **kw: rows.pop(0))
    fake_repo.mark_sent = AsyncMock()
    fake_session = MagicMock()
    fake_session.get = AsyncMock(side_effect=lambda _model, rid: row1 if rid == row1.id else row2)
    _patch_session(monkeypatch, fake_session)
    monkeypatch.setattr(pipeline_mod, "OutboundRepository", lambda _s: fake_repo)

    client = MagicMock()
    client.send = AsyncMock(
        side_effect=[
            InteraktPermanentError("first failed"),
            InteraktSendResult(interakt_message_id="ix-2", raw_response={}),
        ]
    )
    pipe = OutboundPipeline(client=client)

    results = await pipe.dispatch(
        [_intent("A"), _intent("B")],
        doctor_id=uuid.uuid4(),
        state_when_sent="X",
        correlation_id=str(uuid.uuid4()),
    )
    assert [r.status for r in results] == [OutboundStatus.FAILED, OutboundStatus.SENT]


def test_idempotency_key_deterministic() -> None:
    doctor = uuid.uuid4()
    cid = str(uuid.uuid4())
    intent = _intent()
    a = compute_idempotency_key(
        doctor_id=doctor,
        state_when_sent="S1",
        correlation_id=cid,
        sequence=0,
        intent=intent,
    )
    b = compute_idempotency_key(
        doctor_id=doctor,
        state_when_sent="S1",
        correlation_id=cid,
        sequence=0,
        intent=intent,
    )
    c = compute_idempotency_key(
        doctor_id=doctor,
        state_when_sent="S1",
        correlation_id=cid,
        sequence=1,
        intent=intent,
    )
    assert a == b
    assert a != c
    assert a.startswith("out_")


def test_kind_passes_through() -> None:
    # Sanity-check that OutboundKind round-trips.
    assert OutboundKind.TEXT.value == "TEXT"
