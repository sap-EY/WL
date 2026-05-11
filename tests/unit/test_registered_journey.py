"""Tests for `wabot.domain.journeys.registered` (Phase 8)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from wabot.domain.enums import (
    ConsentStatus,
    ExpectedInputKind,
    JourneyType,
    RegisteredState,
)
from wabot.domain.events import CanonicalInboundEvent, EventKind
from wabot.domain.journeys.registered import RegisteredJourneyHandler
from wabot.domain.messages.catalog import ButtonId, MessageSymbol
from wabot.domain.ports.genai import (
    GenAIRequest,
    GenAIResponse,
    GenAIServiceError,
)
from wabot.domain.router import RoutingCase, RoutingDecision
from wabot.infra.config import get_settings

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _RecordingConsentRepo:
    def __init__(self) -> None:
        self.upserts: list[uuid.UUID] = []
        self.status_calls: list[dict[str, Any]] = []

    async def upsert_pending(
        self, *, doctor_id: uuid.UUID, last_template_msg_id: str | None = None
    ) -> Any:
        del last_template_msg_id
        self.upserts.append(doctor_id)
        return SimpleNamespace(doctor_id=doctor_id, status=ConsentStatus.PENDING)

    async def set_status(self, **kwargs: Any) -> Any:
        self.status_calls.append(kwargs)
        return SimpleNamespace(**kwargs)


class _RecordingOnboardingRepo:
    def __init__(self) -> None:
        self.marked: list[uuid.UUID] = []

    async def mark_onboarded(self, doctor_id: uuid.UUID) -> Any:
        self.marked.append(doctor_id)
        return SimpleNamespace(doctor_id=doctor_id, is_onboarded=True)


class _ScriptedGenAIPort:
    """GenAI stub returning a scripted response or raising."""

    def __init__(
        self,
        *,
        response: GenAIResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self._response = response
        self._error = error
        self.calls: list[GenAIRequest] = []

    async def generate(self, request: GenAIRequest) -> GenAIResponse:
        self.calls.append(request)
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


@pytest.fixture(autouse=True)
def _patch_repos(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    consent = _RecordingConsentRepo()
    onboarding = _RecordingOnboardingRepo()
    monkeypatch.setattr(
        "wabot.domain.journeys.registered.ConsentRepository",
        lambda _session: consent,
    )
    monkeypatch.setattr(
        "wabot.domain.journeys.registered.OnboardingRepository",
        lambda _session: onboarding,
    )
    return {"consent": consent, "onboarding": onboarding}


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _event(
    *,
    text: str | None = None,
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


def _decision_case_b() -> RoutingDecision:
    return RoutingDecision(
        case=RoutingCase.B_RESUME_REGISTERED,
        journey=JourneyType.REGISTERED,
        is_resume=True,
    )


def _decision_case_c() -> RoutingDecision:
    return RoutingDecision(
        case=RoutingCase.C_TRIGGER_CONSENT,
        journey=JourneyType.REGISTERED,
        initial_registered_state=RegisteredState.CONSENT_PENDING,
        expected_input_kind=ExpectedInputKind.BUTTON,
        is_resume=False,
    )


def _doctor() -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        full_phone_number="9170000000",
        first_name="Jane",
        last_name="Doe",
        is_profile_complete=True,
    )


def _journey(state: RegisteredState) -> Any:
    return SimpleNamespace(
        doctor_id=uuid.uuid4(),
        journey=JourneyType.REGISTERED,
        state_registration=None,
        state_registered=state,
        expected_input_kind=None,
        expected_outbound_id=None,
        retry_count=0,
        context={},
    )


# ---------------------------------------------------------------------------
# Case C — fresh consent send
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_c_sends_consent_template_and_marks_onboarded(
    _patch_repos: dict[str, Any],
) -> None:
    handler = RegisteredJourneyHandler()
    doctor = _doctor()
    result = await handler.handle(
        event=_event(text="hi"),
        decision=_decision_case_c(),
        journey=None,
        doctor=doctor,
        session=object(),
    )

    assert _patch_repos["consent"].upserts == [doctor.id]
    assert _patch_repos["onboarding"].marked == [doctor.id]
    assert result.next_registered_state == RegisteredState.CONSENT_PENDING
    assert result.expected_input_kind == ExpectedInputKind.BUTTON
    assert len(result.outbound_intents) == 1
    intent = result.outbound_intents[0]
    assert intent.kind == "TEMPLATE"
    assert intent.symbol == MessageSymbol.TEMPLATE_DOCTOR_WELCOME_CONSENT.value
    assert intent.body_values == ("Jane Doe",)


# ---------------------------------------------------------------------------
# CONSENT_PENDING — Accept / Decline / unknown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consent_accept_transitions_and_sends_icebreaker(
    _patch_repos: dict[str, Any],
) -> None:
    handler = RegisteredJourneyHandler()
    doctor = _doctor()
    result = await handler.handle(
        event=_event(button_text="Accept", event_kind=EventKind.USER_BUTTON_REPLY),
        decision=_decision_case_b(),
        journey=_journey(RegisteredState.CONSENT_PENDING),
        doctor=doctor,
        session=object(),
    )

    assert len(_patch_repos["consent"].status_calls) == 1
    assert _patch_repos["consent"].status_calls[0]["status"] == ConsentStatus.ACCEPTED
    assert result.next_registered_state == RegisteredState.CONSENT_ACCEPTED
    assert result.expected_input_kind == ExpectedInputKind.BUTTON
    symbols = [intent.symbol for intent in result.outbound_intents]
    assert symbols == [
        MessageSymbol.MSG_REGISTERED_CONSENT_ACK.value,
        MessageSymbol.MSG_REGISTERED_ICEBREAKER.value,
    ]


@pytest.mark.asyncio
async def test_consent_decline_records_and_replies(
    _patch_repos: dict[str, Any],
) -> None:
    handler = RegisteredJourneyHandler()
    result = await handler.handle(
        event=_event(button_text="Decline", event_kind=EventKind.USER_BUTTON_REPLY),
        decision=_decision_case_b(),
        journey=_journey(RegisteredState.CONSENT_PENDING),
        doctor=_doctor(),
        session=object(),
    )

    assert _patch_repos["consent"].status_calls[0]["status"] == ConsentStatus.DECLINED
    assert result.next_registered_state == RegisteredState.CONSENT_DECLINED
    assert result.outbound_intents[0].symbol == (
        MessageSymbol.MSG_REGISTERED_CONSENT_DECLINED.value
    )


@pytest.mark.asyncio
async def test_consent_pending_free_text_falls_back() -> None:
    handler = RegisteredJourneyHandler()
    result = await handler.handle(
        event=_event(text="hi"),
        decision=_decision_case_b(),
        journey=_journey(RegisteredState.CONSENT_PENDING),
        doctor=_doctor(),
        session=object(),
    )

    assert result.next_registered_state == RegisteredState.CONSENT_PENDING
    assert result.outbound_intents[0].symbol == (
        MessageSymbol.MSG_REGISTERED_FALLBACK_CHOOSE_OPTION.value
    )


# ---------------------------------------------------------------------------
# CONSENT_DECLINED — any inbound retriggers consent template
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consent_declined_reentry_sends_template(
    _patch_repos: dict[str, Any],
) -> None:
    handler = RegisteredJourneyHandler()
    result = await handler.handle(
        event=_event(text="please come back"),
        decision=_decision_case_b(),
        journey=_journey(RegisteredState.CONSENT_DECLINED),
        doctor=_doctor(),
        session=object(),
    )

    assert _patch_repos["consent"].upserts  # PENDING re-upserted
    assert result.next_registered_state == RegisteredState.CONSENT_PENDING
    assert result.outbound_intents[0].kind == "TEMPLATE"


# ---------------------------------------------------------------------------
# Ice-breaker (CONSENT_ACCEPTED)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_icebreaker_ask_question_transitions_to_awaiting_free_text() -> None:
    handler = RegisteredJourneyHandler()
    result = await handler.handle(
        event=_event(
            button_text="Ask a question",
            event_kind=EventKind.USER_BUTTON_REPLY,
        ),
        decision=_decision_case_b(),
        journey=_journey(RegisteredState.CONSENT_ACCEPTED),
        doctor=_doctor(),
        session=object(),
    )

    assert result.next_registered_state == RegisteredState.AWAITING_FREE_TEXT
    assert result.expected_input_kind == ExpectedInputKind.FREE_TEXT


@pytest.mark.asyncio
async def test_icebreaker_talk_to_hotline_sends_hotline_template() -> None:
    handler = RegisteredJourneyHandler()
    result = await handler.handle(
        event=_event(
            button_text="Talk to hotline",
            event_kind=EventKind.USER_BUTTON_REPLY,
        ),
        decision=_decision_case_b(),
        journey=_journey(RegisteredState.CONSENT_ACCEPTED),
        doctor=_doctor(),
        session=object(),
    )

    assert result.next_registered_state == RegisteredState.HOTLINE_TEMPLATE_SENT
    assert result.outbound_intents[0].symbol == MessageSymbol.TEMPLATE_HOTLINE.value
    assert result.outbound_intents[0].body_values == ("Jane Doe",)


# ---------------------------------------------------------------------------
# AWAITING_FREE_TEXT — GenAI branches
# ---------------------------------------------------------------------------


def _genai_scientific(*, app_link: str | None = None) -> GenAIResponse:
    return GenAIResponse(
        intent="answer",
        query_nature="scientific",
        answer_text="Scientific answer body",
        app_link=app_link,
        send_processing_message=True,
        show_answer_buttons=True,
    )


def _genai_non_scientific() -> GenAIResponse:
    return GenAIResponse(
        intent="answer",
        query_nature="non_scientific",
        answer_text="Hi there!",
    )


@pytest.mark.asyncio
async def test_free_text_scientific_emits_ack_and_buttons_answer() -> None:
    port = _ScriptedGenAIPort(response=_genai_scientific(app_link="https://x"))
    handler = RegisteredJourneyHandler(genai_port=port)
    result = await handler.handle(
        event=_event(text="What is hypertension?"),
        decision=_decision_case_b(),
        journey=_journey(RegisteredState.AWAITING_FREE_TEXT),
        doctor=_doctor(),
        session=object(),
    )

    assert [intent.symbol for intent in result.outbound_intents] == [
        MessageSymbol.MSG_REGISTERED_ACK_THINKING.value,
        MessageSymbol.MSG_REGISTERED_ANSWER_WITH_BUTTONS.value,
    ]
    answer_intent = result.outbound_intents[1]
    assert answer_intent.text == "Scientific answer body\n\nhttps://x"
    button_ids = {btn.id for btn in answer_intent.buttons or ()}
    assert button_ids == {
        ButtonId.REGISTERED_ANSWER_SATISFIED.value,
        ButtonId.REGISTERED_ANSWER_CALL_HOTLINE.value,
    }
    assert result.next_registered_state == RegisteredState.AWAITING_ANSWER_BUTTON


@pytest.mark.asyncio
async def test_free_text_non_scientific_emits_text_only() -> None:
    port = _ScriptedGenAIPort(response=_genai_non_scientific())
    handler = RegisteredJourneyHandler(genai_port=port)
    result = await handler.handle(
        event=_event(text="hi"),
        decision=_decision_case_b(),
        journey=_journey(RegisteredState.AWAITING_FREE_TEXT),
        doctor=_doctor(),
        session=object(),
    )

    assert len(result.outbound_intents) == 1
    assert result.outbound_intents[0].kind == "TEXT"
    assert result.outbound_intents[0].text == "Hi there!"
    assert result.next_registered_state == RegisteredState.AWAITING_FREE_TEXT


@pytest.mark.asyncio
async def test_free_text_genai_failure_emits_fallback() -> None:
    port = _ScriptedGenAIPort(error=GenAIServiceError("boom"))
    handler = RegisteredJourneyHandler(genai_port=port)
    result = await handler.handle(
        event=_event(text="What is hypertension?"),
        decision=_decision_case_b(),
        journey=_journey(RegisteredState.AWAITING_FREE_TEXT),
        doctor=_doctor(),
        session=object(),
    )

    assert result.outbound_intents[0].symbol == (
        MessageSymbol.MSG_REGISTERED_FALLBACK_GENAI_FAILED.value
    )
    assert result.next_registered_state == RegisteredState.AWAITING_FREE_TEXT


@pytest.mark.asyncio
async def test_free_text_intent_hotline_sends_template() -> None:
    port = _ScriptedGenAIPort(
        response=GenAIResponse(
            intent="hotline",
            query_nature="non_scientific",
            answer_text="",
            requires_hotline=True,
        ),
    )
    handler = RegisteredJourneyHandler(genai_port=port)
    result = await handler.handle(
        event=_event(text="connect me to support"),
        decision=_decision_case_b(),
        journey=_journey(RegisteredState.AWAITING_FREE_TEXT),
        doctor=_doctor(),
        session=object(),
    )

    assert result.outbound_intents[0].symbol == MessageSymbol.TEMPLATE_HOTLINE.value
    assert result.next_registered_state == RegisteredState.HOTLINE_TEMPLATE_SENT


# ---------------------------------------------------------------------------
# AWAITING_ANSWER_BUTTON
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_answer_button_satisfied_loops_to_awaiting_free_text() -> None:
    handler = RegisteredJourneyHandler()
    result = await handler.handle(
        event=_event(button_text="Satisfied", event_kind=EventKind.USER_BUTTON_REPLY),
        decision=_decision_case_b(),
        journey=_journey(RegisteredState.AWAITING_ANSWER_BUTTON),
        doctor=_doctor(),
        session=object(),
    )

    assert result.next_registered_state == RegisteredState.AWAITING_FREE_TEXT


@pytest.mark.asyncio
async def test_answer_button_call_hotline_sends_template() -> None:
    handler = RegisteredJourneyHandler()
    result = await handler.handle(
        event=_event(button_text="Call hotline", event_kind=EventKind.USER_BUTTON_REPLY),
        decision=_decision_case_b(),
        journey=_journey(RegisteredState.AWAITING_ANSWER_BUTTON),
        doctor=_doctor(),
        session=object(),
    )

    assert result.next_registered_state == RegisteredState.HOTLINE_TEMPLATE_SENT
    assert result.outbound_intents[0].symbol == MessageSymbol.TEMPLATE_HOTLINE.value


@pytest.mark.asyncio
async def test_answer_button_free_text_treated_as_next_query() -> None:
    port = _ScriptedGenAIPort(response=_genai_non_scientific())
    handler = RegisteredJourneyHandler(genai_port=port)
    result = await handler.handle(
        event=_event(text="another question"),
        decision=_decision_case_b(),
        journey=_journey(RegisteredState.AWAITING_ANSWER_BUTTON),
        doctor=_doctor(),
        session=object(),
    )

    assert port.calls  # GenAI was invoked
    assert result.next_registered_state == RegisteredState.AWAITING_FREE_TEXT


# ---------------------------------------------------------------------------
# Auto-registration
# ---------------------------------------------------------------------------


def test_registered_handler_is_auto_registered() -> None:
    from wabot.domain.journeys import (
        get_journey_handler,
        register_journey_handler,
    )

    register_journey_handler(JourneyType.REGISTERED, RegisteredJourneyHandler())
    handler = get_journey_handler(JourneyType.REGISTERED)
    assert isinstance(handler, RegisteredJourneyHandler)
