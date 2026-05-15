"""Tests for `wabot.domain.journeys.registration` (Phase 7 \u2014 form flow)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from wabot.domain.enums import (
    ExpectedInputKind,
    JourneyType,
    RegisteredState,
    RegistrationState,
)
from wabot.domain.events import CanonicalInboundEvent, EventKind
from wabot.domain.journeys.registration import RegistrationJourneyHandler
from wabot.domain.messages.catalog import MessageSymbol
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
        self._doctor_id = uuid.uuid4()

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

    async def get_by_phone(self, full_phone_number: str) -> Any:
        return SimpleNamespace(
            id=self._doctor_id,
            full_phone_number=full_phone_number,
            is_profile_complete=True,
        )


class _RecordingConsentRepo:
    def __init__(self) -> None:
        self.pending_calls: list[uuid.UUID] = []

    async def upsert_pending(
        self, *, doctor_id: uuid.UUID, last_template_msg_id: str | None = None
    ) -> None:
        self.pending_calls.append(doctor_id)


class _RecordingOnboardingRepo:
    def __init__(self) -> None:
        self.onboarded_calls: list[uuid.UUID] = []

    async def mark_onboarded(self, doctor_id: uuid.UUID) -> None:
        self.onboarded_calls.append(doctor_id)


@pytest.fixture(autouse=True)
def _patch_repo(monkeypatch: pytest.MonkeyPatch) -> _RecordingDoctorRepo:
    repo = _RecordingDoctorRepo()
    monkeypatch.setattr(
        "wabot.domain.journeys.registration.DoctorRepository",
        lambda _session: repo,
    )
    monkeypatch.setattr(
        "wabot.domain.journeys.registration.ConsentRepository",
        lambda _session: _RecordingConsentRepo(),
    )
    monkeypatch.setattr(
        "wabot.domain.journeys.registration.OnboardingRepository",
        lambda _session: _RecordingOnboardingRepo(),
    )
    return repo


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


_FORM_PAYLOAD: dict[str, object] = {
    "screen_0_first_name_0": "Jane",
    "screen_0_last_name_1": "Doe",
    "screen_0_mci_id_2": "MCI-12345",
    "screen_1_speciality_0": ["Cardiology"],
}


def _event(
    *,
    text: str | None = "hi",
    event_kind: EventKind = EventKind.USER_TEXT,
    form_response: dict[str, Any] | None = None,
) -> CanonicalInboundEvent:
    return CanonicalInboundEvent(
        correlation_id="11111111-1111-4111-8111-111111111111",
        raw_event_id=uuid.uuid4(),
        event_kind=event_kind,
        interakt_message_id="im-1",
        interakt_customer_id="c-1",
        full_phone_number="9170000000",
        text=text,
        button_text=None,
        form_response=form_response,
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


def _doctor() -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        full_phone_number="9170000000",
        first_name=None,
        last_name=None,
        speciality=None,
        mci_id=None,
        email=None,
        address=None,
        city=None,
        state=None,
        pincode=None,
        is_profile_complete=False,
    )


# ---------------------------------------------------------------------------
# Fresh entry \u2014 Case A: send template
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_a_creates_shell_and_sends_form_template(
    _patch_repo: _RecordingDoctorRepo,
) -> None:
    handler = RegistrationJourneyHandler()
    result = await handler.handle(
        event=_event(),
        decision=_decision_fresh_a(),
        journey=None,
        doctor=None,
        session=object(),
    )

    assert _patch_repo.created_shells == ["9170000000"]
    assert result.next_journey == JourneyType.REGISTRATION
    assert result.next_registration_state == RegistrationState.AWAITING_FULL_DETAILS
    assert result.expected_input_kind == ExpectedInputKind.REGISTRATION_TEXT
    assert result.retry_count == 0
    assert len(result.outbound_intents) == 1
    intent = result.outbound_intents[0]
    assert intent.symbol == MessageSymbol.TEMPLATE_USER_REGISTRATION.value
    assert intent.kind == "TEMPLATE"
    assert intent.is_flow_template is True


@pytest.mark.asyncio
async def test_fresh_entry_with_existing_doctor_skips_shell_creation(
    _patch_repo: _RecordingDoctorRepo,
) -> None:
    handler = RegistrationJourneyHandler()
    result = await handler.handle(
        event=_event(),
        decision=_decision_fresh_a(),
        journey=None,
        doctor=_doctor(),
        session=object(),
    )

    assert _patch_repo.created_shells == []
    assert result.outbound_intents[0].symbol == MessageSymbol.TEMPLATE_USER_REGISTRATION.value


# ---------------------------------------------------------------------------
# Form submission \u2014 completes registration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_form_submission_completes_registration(
    _patch_repo: _RecordingDoctorRepo,
) -> None:
    handler = RegistrationJourneyHandler()
    result = await handler.handle(
        event=_event(
            text=None,
            event_kind=EventKind.USER_FORM_REPLY,
            form_response=_FORM_PAYLOAD,
        ),
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
    assert upsert["speciality"] == "Cardiology"
    assert upsert["mci_id"] == "MCI-12345"
    # Email / address / city / state / pincode are NOT collected.
    assert upsert["email"] is None
    assert upsert["address"] is None
    assert upsert["city"] is None
    assert upsert["state"] is None
    assert upsert["pincode"] is None
    assert result.next_journey == JourneyType.REGISTERED
    assert result.next_registered_state == RegisteredState.CONSENT_PENDING
    assert result.next_registration_state is None
    assert len(result.outbound_intents) == 2
    assert result.outbound_intents[0].symbol == MessageSymbol.MSG_REG_COMPLETED.value
    assert result.outbound_intents[0].text == (
        "Thank you, Dr. Jane.\nYour registration has been completed successfully."
    )
    assert result.outbound_intents[1].symbol == MessageSymbol.TEMPLATE_DOCTOR_WELCOME_CONSENT.value


@pytest.mark.asyncio
async def test_form_submission_without_journey_still_completes(
    _patch_repo: _RecordingDoctorRepo,
) -> None:
    """Defensive: if Interakt fires the form reply before the journey
    row exists, we still upsert the profile."""
    handler = RegistrationJourneyHandler()
    result = await handler.handle(
        event=_event(
            text=None,
            event_kind=EventKind.USER_FORM_REPLY,
            form_response=_FORM_PAYLOAD,
        ),
        decision=_decision_fresh_a(),
        journey=None,
        doctor=_doctor(),
        session=object(),
    )

    assert len(_patch_repo.upserts) == 1
    assert result.next_journey == JourneyType.REGISTERED
    assert result.next_registered_state == RegisteredState.CONSENT_PENDING


@pytest.mark.asyncio
async def test_form_submission_parse_failure_escalates(
    _patch_repo: _RecordingDoctorRepo,
) -> None:
    handler = RegistrationJourneyHandler()
    result = await handler.handle(
        event=_event(
            text=None,
            event_kind=EventKind.USER_FORM_REPLY,
            form_response={},  # empty payload \u2192 RegistrationParseError
        ),
        decision=_decision_resume_d(),
        journey=_journey(RegistrationState.AWAITING_FULL_DETAILS),
        doctor=_doctor(),
        session=object(),
    )

    assert _patch_repo.upserts == []
    assert result.next_registration_state == RegistrationState.ASSISTED_SUPPORT
    assert result.outbound_intents[0].symbol == MessageSymbol.MSG_REG_ASSISTED_SUPPORT.value


# ---------------------------------------------------------------------------
# Non-form text while awaiting form \u2014 re-send template
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_text_while_awaiting_form_resends_template(
    _patch_repo: _RecordingDoctorRepo,
) -> None:
    handler = RegistrationJourneyHandler()
    result = await handler.handle(
        event=_event(text="oops typed instead of tapping"),
        decision=_decision_resume_d(),
        journey=_journey(RegistrationState.AWAITING_FULL_DETAILS),
        doctor=_doctor(),
        session=object(),
    )

    assert _patch_repo.upserts == []
    assert result.next_registration_state == RegistrationState.AWAITING_FULL_DETAILS
    assert result.outbound_intents[0].symbol == MessageSymbol.TEMPLATE_USER_REGISTRATION.value


# ---------------------------------------------------------------------------
# Terminal states are no-ops
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_completed_state_is_noop(_patch_repo: _RecordingDoctorRepo) -> None:
    handler = RegistrationJourneyHandler()
    result = await handler.handle(
        event=_event(),
        decision=_decision_resume_d(),
        journey=_journey(RegistrationState.REGISTRATION_COMPLETED),
        doctor=_doctor(),
        session=object(),
    )
    assert _patch_repo.upserts == []
    assert result.outbound_intents == ()
    assert result.next_registration_state == RegistrationState.REGISTRATION_COMPLETED


@pytest.mark.asyncio
async def test_assisted_support_state_is_noop(
    _patch_repo: _RecordingDoctorRepo,
) -> None:
    handler = RegistrationJourneyHandler()
    result = await handler.handle(
        event=_event(),
        decision=_decision_resume_d(),
        journey=_journey(RegistrationState.ASSISTED_SUPPORT),
        doctor=_doctor(),
        session=object(),
    )
    assert result.outbound_intents == ()
    assert result.next_registration_state == RegistrationState.ASSISTED_SUPPORT
