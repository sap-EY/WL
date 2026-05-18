"""Tests for `wabot.domain.router`.

The router is a pure function over already-loaded snapshots, so the
fixtures here use lightweight stand-in objects (`SimpleNamespace`)
rather than instantiating the SQLAlchemy models.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from wabot.domain.enums import (
    ExpectedInputKind,
    JourneyType,
    RegisteredState,
    RegistrationState,
)
from wabot.domain.events import CanonicalInboundEvent, EventKind
from wabot.domain.router import RoutingCase, route_user_event


def _user_event(kind: EventKind = EventKind.USER_TEXT) -> CanonicalInboundEvent:
    return CanonicalInboundEvent(
        correlation_id="corr-1",
        raw_event_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        event_kind=kind,
        interakt_message_id="im-1",
        interakt_customer_id="c-1",
        full_phone_number="9170000000",
        text="hi",
        received_at=datetime.now(UTC),
    )


def _doctor() -> Any:
    return SimpleNamespace(
        id=uuid.UUID("22222222-2222-4222-8222-222222222222"),
        full_phone_number="9170000000",
    )


def _journey(journey: JourneyType, **kwargs: Any) -> Any:
    return SimpleNamespace(journey=journey, **kwargs)


def _onboarding(*, is_onboarded: bool) -> Any:
    return SimpleNamespace(is_onboarded=is_onboarded)


def test_case_a_unknown_user() -> None:
    decision = route_user_event(
        event=_user_event(),
        doctor=None,
        journey=None,
        onboarding=None,
    )
    assert decision.case is RoutingCase.A_UNKNOWN_USER
    assert decision.journey is JourneyType.REGISTRATION
    assert decision.initial_registration_state is RegistrationState.REG_INITIATED
    assert decision.expected_input_kind is ExpectedInputKind.REGISTRATION_TEXT
    assert decision.is_resume is False


def test_active_registration_journey_resumes() -> None:
    doctor = _doctor()
    journey = _journey(JourneyType.REGISTRATION)
    decision = route_user_event(
        event=_user_event(),
        doctor=doctor,
        journey=journey,
        onboarding=None,
    )
    assert decision.case is RoutingCase.RESUME_REGISTRATION
    assert decision.journey is JourneyType.REGISTRATION
    assert decision.is_resume is True


def test_known_doctor_without_onboarding_triggers_consent() -> None:
    doctor = _doctor()
    decision = route_user_event(
        event=_user_event(),
        doctor=doctor,
        journey=None,
        onboarding=None,
    )
    assert decision.case is RoutingCase.C_TRIGGER_CONSENT
    assert decision.journey is JourneyType.REGISTERED
    assert decision.is_resume is False
    assert decision.initial_registered_state is RegisteredState.CONSENT_PENDING


def test_case_c_complete_but_not_onboarded() -> None:
    doctor = _doctor()
    decision = route_user_event(
        event=_user_event(),
        doctor=doctor,
        journey=None,
        onboarding=_onboarding(is_onboarded=False),
    )
    assert decision.case is RoutingCase.C_TRIGGER_CONSENT
    assert decision.journey is JourneyType.REGISTERED
    assert decision.initial_registered_state is RegisteredState.CONSENT_PENDING
    assert decision.expected_input_kind is ExpectedInputKind.BUTTON
    assert decision.is_resume is False


def test_case_c_no_onboarding_row_treated_as_not_onboarded() -> None:
    doctor = _doctor()
    decision = route_user_event(
        event=_user_event(),
        doctor=doctor,
        journey=None,
        onboarding=None,
    )
    assert decision.case is RoutingCase.C_TRIGGER_CONSENT


def test_case_b_resume_registered() -> None:
    doctor = _doctor()
    journey = _journey(JourneyType.REGISTERED)
    decision = route_user_event(
        event=_user_event(),
        doctor=doctor,
        journey=journey,
        onboarding=_onboarding(is_onboarded=True),
    )
    assert decision.case is RoutingCase.B_RESUME_REGISTERED
    assert decision.is_resume is True


def test_case_b_defensive_when_journey_row_missing() -> None:
    doctor = _doctor()
    decision = route_user_event(
        event=_user_event(),
        doctor=doctor,
        journey=None,
        onboarding=_onboarding(is_onboarded=True),
    )
    assert decision.case is RoutingCase.B_RESUME_REGISTERED
    assert decision.is_resume is False
    assert decision.initial_registered_state is RegisteredState.AWAITING_FREE_TEXT
    assert decision.expected_input_kind is ExpectedInputKind.FREE_TEXT


def test_status_event_returns_non_user_decision() -> None:
    decision = route_user_event(
        event=_user_event(EventKind.OUTBOUND_DELIVERED),
        doctor=_doctor(),
        journey=None,
        onboarding=_onboarding(is_onboarded=True),
    )
    assert decision.case is RoutingCase.NON_USER_EVENT
    assert decision.journey is None
