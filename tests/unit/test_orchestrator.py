"""Tests for `wabot.services.orchestrator`.

These are orchestration tests: every external dependency (Redis lock,
DB session, normalizer, journey handler) is replaced with a fake so
the test exercises the *control flow* through `Orchestrator.handle_message`.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from wabot.adapters.broker.base import InboundMessage
from wabot.cache.locks import UserLockUnavailableError
from wabot.domain.enums import (
    ExpectedInputKind,
    JourneyType,
    RegisteredState,
)
from wabot.domain.events import CanonicalInboundEvent, EventKind
from wabot.domain.journeys import JourneyResult, reset_handlers_for_tests
from wabot.infra.config import get_settings
from wabot.services import orchestrator as orch_mod

# ---------------------------------------------------------------------------
# Common fakes
# ---------------------------------------------------------------------------


class _NoLock:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        return

    async def __aenter__(self) -> _NoLock:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


class _RaisingLock:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        return

    async def __aenter__(self) -> _RaisingLock:
        msg = "lock contended"
        raise UserLockUnavailableError(msg)

    async def __aexit__(self, *exc: Any) -> None:
        return None


def _canonical(
    *,
    event_kind: EventKind = EventKind.USER_TEXT,
    interakt_message_id: str = "im-1",
    full_phone: str = "9170000000",
) -> CanonicalInboundEvent:
    return CanonicalInboundEvent(
        correlation_id="11111111-1111-4111-8111-111111111111",
        raw_event_id=uuid.UUID("22222222-2222-4222-8222-222222222222"),
        event_kind=event_kind,
        interakt_message_id=interakt_message_id,
        interakt_customer_id="c-1",
        full_phone_number=full_phone,
        text="hi",
        received_at=datetime.now(UTC),
    )


def _broker_message(event_id: uuid.UUID, *, full_phone: str = "9170000000") -> InboundMessage:
    return InboundMessage(
        message_id="0-1",
        partition_key=full_phone,
        payload={
            "event_id": str(event_id),
            "full_phone_number": full_phone,
            "correlation_id": "11111111-1111-4111-8111-111111111111",
            "type": "message_received",
            "interakt_message_id": "im-1",
            "message_status": None,
        },
    )


def _patch_lock_and_redis(monkeypatch: pytest.MonkeyPatch, lock_cls: type = _NoLock) -> None:
    monkeypatch.setattr(orch_mod, "UserLock", lock_cls)
    monkeypatch.setattr(orch_mod, "get_redis", lambda *a, **kw: MagicMock())


def _patch_session(monkeypatch: pytest.MonkeyPatch, session: Any) -> None:
    @asynccontextmanager
    async def _scope() -> Any:
        yield session

    monkeypatch.setattr(orch_mod, "session_scope", _scope)


def _patch_normalize(monkeypatch: pytest.MonkeyPatch, event: CanonicalInboundEvent) -> None:
    monkeypatch.setattr(orch_mod, "normalize", lambda **kwargs: event)


def _make_session_with_raw_row(raw_row: Any) -> Any:
    session = MagicMock()
    session.get = AsyncMock(return_value=raw_row)
    session.execute = AsyncMock()
    return session


def _settings() -> Any:
    return get_settings()


@pytest.fixture(autouse=True)
def _reset_handlers() -> None:
    reset_handlers_for_tests()


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_message_acks_when_raw_row_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_lock_and_redis(monkeypatch)
    session = _make_session_with_raw_row(None)
    _patch_session(monkeypatch, session)

    orch = orch_mod.Orchestrator(_settings())
    ok = await orch.handle_message(_broker_message(uuid.uuid4()))
    assert ok is True


@pytest.mark.asyncio
async def test_handle_message_skips_already_processed_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_lock_and_redis(monkeypatch)
    raw_row = SimpleNamespace(
        id=uuid.uuid4(),
        payload={"type": "message_received"},
        processed_at=datetime.now(UTC),
    )
    session = _make_session_with_raw_row(raw_row)
    _patch_session(monkeypatch, session)

    orch = orch_mod.Orchestrator(_settings())
    ok = await orch.handle_message(_broker_message(raw_row.id))
    assert ok is True
    # Already processed → normalize must not be called either; we
    # didn't patch it so a call would explode.


@pytest.mark.asyncio
async def test_handle_message_returns_false_on_lock_contention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_lock_and_redis(monkeypatch, lock_cls=_RaisingLock)
    session = _make_session_with_raw_row(None)
    _patch_session(monkeypatch, session)

    orch = orch_mod.Orchestrator(_settings())
    ok = await orch.handle_message(_broker_message(uuid.uuid4()))
    assert ok is False


@pytest.mark.asyncio
async def test_user_event_routes_to_journey_handler_and_persists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_lock_and_redis(monkeypatch)

    raw_row = SimpleNamespace(
        id=uuid.uuid4(),
        payload={"type": "message_received"},
        processed_at=None,
    )
    session = _make_session_with_raw_row(raw_row)
    _patch_session(monkeypatch, session)

    canonical = _canonical()
    _patch_normalize(monkeypatch, canonical)

    doctor = SimpleNamespace(
        id=uuid.uuid4(),
        full_phone_number=canonical.full_phone_number,
        is_profile_complete=True,
    )
    doctor_repo = MagicMock()
    doctor_repo.get_by_phone = AsyncMock(return_value=doctor)
    monkeypatch.setattr(orch_mod, "DoctorRepository", lambda _s: doctor_repo)

    journey_repo = MagicMock()
    journey_repo.get = AsyncMock(return_value=None)
    journey_repo.upsert = AsyncMock(return_value=SimpleNamespace())
    journey_repo.append_history = AsyncMock(return_value=SimpleNamespace())
    monkeypatch.setattr(orch_mod, "JourneyRepository", lambda _s: journey_repo)

    monkeypatch.setattr(
        orch_mod,
        "_load_onboarding",
        AsyncMock(return_value=SimpleNamespace(is_onboarded=True)),
    )

    handler_calls: list[Any] = []

    class _Handler:
        async def handle(self, **kwargs: Any) -> JourneyResult:
            handler_calls.append(kwargs)
            return JourneyResult(
                next_journey=JourneyType.REGISTERED,
                next_registered_state=RegisteredState.AWAITING_FREE_TEXT,
                expected_input_kind=ExpectedInputKind.FREE_TEXT,
            )

    from wabot.domain.journeys import register_journey_handler

    register_journey_handler(JourneyType.REGISTERED, _Handler())

    orch = orch_mod.Orchestrator(_settings())
    ok = await orch.handle_message(_broker_message(raw_row.id))

    assert ok is True
    assert len(handler_calls) == 1
    journey_repo.upsert.assert_awaited_once()
    upsert_kwargs = journey_repo.upsert.await_args.kwargs
    assert upsert_kwargs["doctor_id"] == doctor.id
    assert upsert_kwargs["journey"] is JourneyType.REGISTERED
    assert upsert_kwargs["state_registered"] is RegisteredState.AWAITING_FREE_TEXT
    assert upsert_kwargs["last_processed_event_id"] == canonical.interakt_message_id
    assert raw_row.processed_at is not None


@pytest.mark.asyncio
async def test_user_event_dedupes_when_last_processed_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_lock_and_redis(monkeypatch)

    raw_row = SimpleNamespace(
        id=uuid.uuid4(),
        payload={"type": "message_received"},
        processed_at=None,
    )
    session = _make_session_with_raw_row(raw_row)
    _patch_session(monkeypatch, session)

    canonical = _canonical(interakt_message_id="im-1")
    _patch_normalize(monkeypatch, canonical)

    doctor = SimpleNamespace(
        id=uuid.uuid4(),
        full_phone_number=canonical.full_phone_number,
        is_profile_complete=True,
    )
    doctor_repo = MagicMock()
    doctor_repo.get_by_phone = AsyncMock(return_value=doctor)
    monkeypatch.setattr(orch_mod, "DoctorRepository", lambda _s: doctor_repo)

    existing_journey = SimpleNamespace(
        journey=JourneyType.REGISTERED,
        last_processed_event_id="im-1",  # same as canonical → duplicate
        state_registration=None,
        state_registered=RegisteredState.AWAITING_FREE_TEXT,
        expected_input_kind="FREE_TEXT",
        expected_outbound_id=None,
        retry_count=0,
        context={},
    )
    journey_repo = MagicMock()
    journey_repo.get = AsyncMock(return_value=existing_journey)
    journey_repo.upsert = AsyncMock()
    monkeypatch.setattr(orch_mod, "JourneyRepository", lambda _s: journey_repo)

    monkeypatch.setattr(
        orch_mod,
        "_load_onboarding",
        AsyncMock(return_value=SimpleNamespace(is_onboarded=True)),
    )

    orch = orch_mod.Orchestrator(_settings())
    ok = await orch.handle_message(_broker_message(raw_row.id))

    assert ok is True
    journey_repo.upsert.assert_not_called()
    assert raw_row.processed_at is not None  # still marked processed


@pytest.mark.asyncio
async def test_status_event_dispatches_to_outbound_status_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_lock_and_redis(monkeypatch)

    raw_row = SimpleNamespace(
        id=uuid.uuid4(),
        payload={"type": "message_api_delivered"},
        processed_at=None,
    )
    session = _make_session_with_raw_row(raw_row)
    _patch_session(monkeypatch, session)

    canonical = _canonical(event_kind=EventKind.OUTBOUND_DELIVERED)
    _patch_normalize(monkeypatch, canonical)

    calls: list[CanonicalInboundEvent] = []

    class _StatusHandler:
        async def handle(self, *, event: CanonicalInboundEvent, session: Any) -> None:
            del session
            calls.append(event)

    from wabot.domain.journeys import register_outbound_status_handler

    register_outbound_status_handler(_StatusHandler())

    orch = orch_mod.Orchestrator(_settings())
    ok = await orch.handle_message(_broker_message(raw_row.id))

    assert ok is True
    assert len(calls) == 1
    assert calls[0].event_kind is EventKind.OUTBOUND_DELIVERED
    assert raw_row.processed_at is not None


@pytest.mark.asyncio
async def test_poison_payload_is_acked_to_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_lock_and_redis(monkeypatch)
    bad_message = InboundMessage(
        message_id="0-1",
        partition_key="9170000000",
        payload={},  # missing event_id + full_phone_number
    )

    orch = orch_mod.Orchestrator(_settings())
    ok = await orch.handle_message(bad_message)
    assert ok is True


@pytest.mark.asyncio
async def test_normalization_failure_marks_processed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_lock_and_redis(monkeypatch)

    raw_row = SimpleNamespace(
        id=uuid.uuid4(),
        payload={"type": "message_received"},
        processed_at=None,
    )
    session = _make_session_with_raw_row(raw_row)
    _patch_session(monkeypatch, session)

    from wabot.adapters.interakt import NormalizationError

    def _raise(**kwargs: Any) -> None:
        msg = "missing fields"
        raise NormalizationError(msg)

    monkeypatch.setattr(orch_mod, "normalize", _raise)

    orch = orch_mod.Orchestrator(_settings())
    ok = await orch.handle_message(_broker_message(raw_row.id))
    assert ok is True
    assert raw_row.processed_at is not None
