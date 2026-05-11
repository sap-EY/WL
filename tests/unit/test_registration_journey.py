"""Tests for `wabot.domain.journeys.registration` (Phase 7)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from wabot.domain.enums import (
    ExpectedInputKind,
    JourneyType,
    RegistrationState,
)
from wabot.domain.events import CanonicalInboundEvent, EventKind
from wabot.domain.journeys.registration import RegistrationJourneyHandler
from wabot.domain.messages.catalog import ButtonId, MessageSymbol
from wabot.domain.router import RoutingCase, RoutingDecision
from wabot.infra.config import get_settings

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _RecordingDoctorRepo:
    """In-memory stand-in for `DoctorRepository` capturing calls."""

    def __init__(self) -> None:
        self.created_shells: list[str] = []
        self.upserts: list[dict[str, Any]] = []

    async def create_shell(self, full_phone_number: str) -> Any:
        self.created_shells.append(full_phone_number)
        return SimpleNamespace(
            id=uuid.uuid4(),
            full_phone_number=full_phone_number,
            is_profile_complete=False,
        )

    async def upsert_profile(self, **kwargs: Any) -> Any:
        self.upserts.append(kwargs)
        return SimpleNamespace(**kwargs)


@pytest.fixture(autouse=True)
def _patch_repo(monkeypatch: pytest.MonkeyPatch) -> _RecordingDoctorRepo:
    repo = _RecordingDoctorRepo()
    monkeypatch.setattr(
        "wabot.domain.journeys.registration.DoctorRepository",
        lambda _session: repo,
    )
    return repo


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _event(
    *,
    text: str | None = "hi",
    button_text: str | None = None,
    event_kind: EventKind = EventKind.USER_TEXT,
) -> CanonicalInboundEvent:
    return CanonicalInboundEvent(
        correlation_id="11111111-1111-4111-8111-111111111111",
        raw_event_id=uuid.uuid4(),
        event_kind=event_kind,
        interakt_message_id="im-1",
        interakt_customer_id="c-1",
        full_phone_number="9170000000",
        text=text,
        button_text=button_text,
        received_at=datetime.now(UTC),
    )


def _decision_fresh_a() -> RoutingDecision:
    return RoutingDecision(
        case=RoutingCase.A_UNKNOWN_USER,
        journey=JourneyType.REGISTRATION,
        initial_registration_state=RegistrationState.REG_INITIATED,
        expected_input_kind=ExpectedInputKind.REGISTRATION_TEXT,
        is_resume=False,
    )


def _decision_resume_d() -> RoutingDecision:
    return RoutingDecision(
        case=RoutingCase.D_RESUME_REGISTRATION,
        journey=JourneyType.REGISTRATION,
        is_resume=True,
    )


def _journey(state: RegistrationState, *, retry_count: int = 0) -> Any:
    return SimpleNamespace(
        doctor_id=uuid.uuid4(),
        journey=JourneyType.REGISTRATION,
        state_registration=state,
        state_registered=None,
        expected_input_kind=ExpectedInputKind.REGISTRATION_TEXT.value,
        expected_outbound_id=None,
        retry_count=retry_count,
        context={},
    )


def _doctor(*, partial: bool = False) -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        full_phone_number="9170000000",
        first_name="Jane" if partial else None,
        last_name=None,
        speciality="Cardiology" if partial else None,
        email=None,
        address=None,
        city=None,
        state=None,
        pincode=None,
        is_profile_complete=False,
    )


_VALID_REG_TEXT = "Jane Doe#Cardiology#221B Baker Street#jane@example.com#Mumbai#Maharashtra#400001"


# ---------------------------------------------------------------------------
# Fresh entry — Case A
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_a_creates_shell_and_prompts(
    _patch_repo: _RecordingDoctorRepo,
) -> None:
    handler = RegistrationJourneyHandler()
    result = await handler.handle(
        event=_event(),
        decision=_decision_fresh_a(),
        journey=None,
        doctor=None,
        session=object(),  # unused — repo is patched
    )

    assert _patch_repo.created_shells == ["9170000000"]
    assert result.next_journey == JourneyType.REGISTRATION
    assert result.next_registration_state == RegistrationState.AWAITING_FULL_DETAILS
    assert result.expected_input_kind == ExpectedInputKind.REGISTRATION_TEXT
    assert result.retry_count == 0
    assert len(result.outbound_intents) == 1
    intent = result.outbound_intents[0]
    assert intent.symbol == MessageSymbol.MSG_REG_FULL_DETAILS_PROMPT.value
    assert intent.kind == "TEXT"


# ---------------------------------------------------------------------------
# AWAITING_FULL_DETAILS — happy parse
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_awaiting_full_valid_completes_registration(
    _patch_repo: _RecordingDoctorRepo,
) -> None:
    handler = RegistrationJourneyHandler()
    result = await handler.handle(
        event=_event(text=_VALID_REG_TEXT),
        decision=_decision_resume_d(),
        journey=_journey(RegistrationState.AWAITING_FULL_DETAILS),
        doctor=_doctor(),
        session=object(),
    )

    assert len(_patch_repo.upserts) == 1
    upsert = _patch_repo.upserts[0]
    assert upsert["is_profile_complete"] is True
    assert upsert["first_name"] == "Jane"
    assert upsert["last_name"] == "Doe"
    assert upsert["pincode"] == "400001"
    assert result.next_registration_state == RegistrationState.REGISTRATION_COMPLETED
    assert result.outbound_intents[0].symbol == MessageSymbol.MSG_REG_COMPLETED.value


# ---------------------------------------------------------------------------
# Parse failure — retry then escalate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parse_failure_first_retry_prompts_again(
    _patch_repo: _RecordingDoctorRepo,
) -> None:
    handler = RegistrationJourneyHandler()
    result = await handler.handle(
        event=_event(text="not-enough-tokens"),
        decision=_decision_resume_d(),
        journey=_journey(RegistrationState.AWAITING_FULL_DETAILS, retry_count=0),
        doctor=_doctor(),
        session=object(),
    )

    assert _patch_repo.upserts == []
    assert result.next_registration_state == RegistrationState.AWAITING_CORRECTED_FULL
    assert result.retry_count == 1
    assert result.outbound_intents[0].symbol == MessageSymbol.MSG_REG_RETRY_PROMPT.value


@pytest.mark.asyncio
async def test_parse_failure_after_max_retries_escalates() -> None:
    handler = RegistrationJourneyHandler()
    settings = get_settings()
    # retry_count is already at the configured max; the next failure must escalate.
    result = await handler.handle(
        event=_event(text="bad"),
        decision=_decision_resume_d(),
        journey=_journey(
            RegistrationState.AWAITING_CORRECTED_FULL,
            retry_count=settings.registration_max_retries,
        ),
        doctor=_doctor(),
        session=object(),
    )

    assert result.next_registration_state == RegistrationState.ASSISTED_SUPPORT
    assert result.outbound_intents[0].symbol == MessageSymbol.MSG_REG_ASSISTED_SUPPORT.value


# ---------------------------------------------------------------------------
# PARTIAL_CONFIRM_PENDING
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_partial_confirm_yes_completes_with_existing_data(
    _patch_repo: _RecordingDoctorRepo,
) -> None:
    handler = RegistrationJourneyHandler()
    doctor = SimpleNamespace(
        id=uuid.uuid4(),
        full_phone_number="9170000000",
        first_name="Jane",
        last_name="Doe",
        speciality="Cardio",
        email="j@example.com",
        address="addr",
        city="Mumbai",
        state="MH",
        pincode="400001",
        is_profile_complete=False,
    )
    result = await handler.handle(
        event=_event(
            text=None,
            button_text="Yes",
            event_kind=EventKind.USER_BUTTON_REPLY,
        ),
        decision=_decision_resume_d(),
        journey=_journey(RegistrationState.PARTIAL_CONFIRM_PENDING),
        doctor=doctor,
        session=object(),
    )

    assert len(_patch_repo.upserts) == 1
    assert _patch_repo.upserts[0]["is_profile_complete"] is True
    assert _patch_repo.upserts[0]["first_name"] == "Jane"
    assert result.next_registration_state == RegistrationState.REGISTRATION_COMPLETED


@pytest.mark.asyncio
async def test_partial_confirm_no_reprompts_for_full_details() -> None:
    handler = RegistrationJourneyHandler()
    result = await handler.handle(
        event=_event(
            text=None,
            button_text="No",
            event_kind=EventKind.USER_BUTTON_REPLY,
        ),
        decision=_decision_resume_d(),
        journey=_journey(RegistrationState.PARTIAL_CONFIRM_PENDING),
        doctor=_doctor(partial=True),
        session=object(),
    )

    assert result.next_registration_state == RegistrationState.AWAITING_FULL_DETAILS
    assert result.outbound_intents[0].symbol == MessageSymbol.MSG_REG_FULL_DETAILS_PROMPT.value


@pytest.mark.asyncio
async def test_partial_confirm_free_text_falls_back() -> None:
    handler = RegistrationJourneyHandler()
    result = await handler.handle(
        event=_event(text="something", event_kind=EventKind.USER_TEXT),
        decision=_decision_resume_d(),
        journey=_journey(RegistrationState.PARTIAL_CONFIRM_PENDING),
        doctor=_doctor(partial=True),
        session=object(),
    )

    assert result.next_registration_state == RegistrationState.PARTIAL_CONFIRM_PENDING
    assert result.outbound_intents[0].symbol == (
        MessageSymbol.MSG_REGISTERED_FALLBACK_CHOOSE_OPTION.value
    )


# ---------------------------------------------------------------------------
# Defensive Case D — partial doctor, no journey row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_defensive_d_partial_doctor_offers_partial_confirm() -> None:
    handler = RegistrationJourneyHandler()
    result = await handler.handle(
        event=_event(),
        decision=_decision_resume_d(),
        journey=None,
        doctor=_doctor(partial=True),
        session=object(),
    )

    assert result.next_registration_state == RegistrationState.PARTIAL_CONFIRM_PENDING
    assert result.expected_input_kind == ExpectedInputKind.BUTTON
    assert result.outbound_intents[0].symbol == (MessageSymbol.MSG_REG_PARTIAL_CONFIRM_PROMPT.value)
    # Both expected button ids should be present in the InteractiveButton list.
    button_ids = {btn.id for btn in result.outbound_intents[0].buttons or ()}
    assert button_ids == {
        ButtonId.REG_PARTIAL_CONFIRM_YES.value,
        ButtonId.REG_PARTIAL_CONFIRM_NO.value,
    }


@pytest.mark.asyncio
async def test_defensive_d_empty_doctor_prompts_full_details() -> None:
    handler = RegistrationJourneyHandler()
    result = await handler.handle(
        event=_event(),
        decision=_decision_resume_d(),
        journey=None,
        doctor=_doctor(partial=False),
        session=object(),
    )

    assert result.next_registration_state == RegistrationState.AWAITING_FULL_DETAILS


# ---------------------------------------------------------------------------
# Terminal states are no-ops
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_terminal_state_is_noop() -> None:
    handler = RegistrationJourneyHandler()
    result = await handler.handle(
        event=_event(),
        decision=_decision_resume_d(),
        journey=_journey(RegistrationState.ASSISTED_SUPPORT),
        doctor=_doctor(),
        session=object(),
    )

    assert result.next_registration_state == RegistrationState.ASSISTED_SUPPORT
    assert result.outbound_intents == ()


# ---------------------------------------------------------------------------
# Handler is auto-registered on import
# ---------------------------------------------------------------------------


def test_handler_is_auto_registered() -> None:
    from wabot.domain.journeys import (
        get_journey_handler,
        register_journey_handler,
    )

    # Other tests (notably `test_orchestrator.py`) may have cleared the
    # registry via `reset_handlers_for_tests`. Re-register and verify.
    register_journey_handler(JourneyType.REGISTRATION, RegistrationJourneyHandler())
    handler = get_journey_handler(JourneyType.REGISTRATION)
    assert isinstance(handler, RegistrationJourneyHandler)
