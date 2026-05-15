"""Registered-user journey handler (implementation_plan.md §Phase 8).

Wires the routing decisions from `domain.router` (Cases B and C) into
the registered-user state machine (`RegisteredState`). Coordinates
the consent template send, accept/decline handling, ice-breaker,
free-text → GenAI loop, scientific vs non-scientific answer shaping,
and the hotline template send.

The handler stays pure of wire-side effects: it owns DB transitions
via repositories and returns ``JourneyResult.outbound_intents`` for
the orchestrator to dispatch after the journey-state transaction
commits.
"""

from __future__ import annotations

import uuid as _uuid
from typing import TYPE_CHECKING

from wabot.data.repositories.consent_repo import ConsentRepository
from wabot.data.repositories.onboarding_repo import OnboardingRepository
from wabot.domain.enums import (
    ConsentStatus,
    ExpectedInputKind,
    JourneyType,
    RegisteredState,
)
from wabot.domain.events import EventKind
from wabot.domain.journeys.base import (
    JourneyResult,
    register_journey_handler,
)
from wabot.domain.messages.builder import build_buttons, build_template, build_text
from wabot.domain.messages.catalog import ButtonId, MessageSymbol
from wabot.domain.ports.genai import (
    GenAIPort,
    GenAIRequest,
    GenAIServiceError,
    get_genai_port,
)
from wabot.infra.config import get_settings
from wabot.infra.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from wabot.data.models.doctor import Doctor
    from wabot.data.models.journey import JourneyState
    from wabot.domain.events import CanonicalInboundEvent
    from wabot.domain.outbound import OutboundIntent
    from wabot.domain.router import RoutingDecision

logger = get_logger(__name__)


# Consent template buttons echo their TITLE in `message_received`
# (Interakt drops the reply-id for QR / quick-reply variants). The
# titles below match the WhatsApp template configuration.
_CONSENT_ACCEPT_TITLE = "Let's Continue"
_CONSENT_DECLINE_TITLE = "No, thanks"


class RegisteredJourneyHandler:
    """State-machine handler for `JourneyType.REGISTERED`.

    `genai_port` is injected for tests; production uses
    `get_genai_port()` (which returns the stub until Phase 9 wires a
    real adapter via `register_genai_port`).
    """

    def __init__(self, *, genai_port: GenAIPort | None = None) -> None:
        self._genai_port_override = genai_port

    @property
    def _genai_port(self) -> GenAIPort:
        return self._genai_port_override or get_genai_port()

    async def handle(  # noqa: PLR0911 - state dispatcher with explicit branches
        self,
        *,
        event: CanonicalInboundEvent,
        decision: RoutingDecision,
        journey: JourneyState | None,
        doctor: Doctor | None,
        session: AsyncSession,
    ) -> JourneyResult:
        if doctor is None:
            # Router only routes here when doctor exists; if it doesn't,
            # something upstream is wrong — emit a fallback and bail.
            logger.warning("wabot.registered.no_doctor")
            return _result_text(
                MessageSymbol.MSG_REGISTERED_FALLBACK_CHOOSE_OPTION,
                event=event,
                next_state=RegisteredState.AWAITING_FREE_TEXT,
                expected=ExpectedInputKind.FREE_TEXT,
            )

        consent_repo = ConsentRepository(session)
        onboarding_repo = OnboardingRepository(session)

        # ------------------------------------------------------------------
        # Fresh entry — Case C trigger consent (no journey row yet)
        # ------------------------------------------------------------------
        if journey is None:
            return await self._send_consent_template(
                event=event,
                doctor=doctor,
                consent_repo=consent_repo,
                onboarding_repo=onboarding_repo,
            )

        current_state = journey.state_registered
        if current_state is None:
            # Defensive: registered journey row missing the registered
            # state. Treat as a fresh consent send.
            logger.warning(
                "wabot.registered.missing_state",
                doctor_id=str(doctor.id),
            )
            return await self._send_consent_template(
                event=event,
                doctor=doctor,
                consent_repo=consent_repo,
                onboarding_repo=onboarding_repo,
            )

        # ------------------------------------------------------------------
        # Resume — dispatch on current registered state
        # ------------------------------------------------------------------
        if current_state == RegisteredState.CONSENT_PENDING:
            return await self._handle_consent_reply(
                event=event,
                doctor=doctor,
                consent_repo=consent_repo,
            )

        if current_state == RegisteredState.CONSENT_DECLINED:
            # Any inbound after a decline re-triggers the consent template
            # (no cooldown — implementation_plan.md §7.7).
            return await self._send_consent_template(
                event=event,
                doctor=doctor,
                consent_repo=consent_repo,
                onboarding_repo=onboarding_repo,
            )

        if current_state == RegisteredState.CONSENT_ACCEPTED:
            # We landed here after sending the ack + ice-breaker; the
            # next inbound either taps an ice-breaker button or starts
            # a free-text query.
            return await self._handle_icebreaker_or_free_text(
                event=event,
                doctor=doctor,
            )

        if current_state == RegisteredState.AWAITING_FREE_TEXT:
            return await self._handle_free_text(event=event, doctor=doctor)

        if current_state == RegisteredState.AWAITING_ANSWER_BUTTON:
            return await self._handle_answer_button(event=event, doctor=doctor)

        if current_state in {
            RegisteredState.GENAI_PROCESSING,
            RegisteredState.HOTLINE_TEMPLATE_SENT,
        }:
            # The user replied during a transient state. Treat as a fresh
            # free-text turn so the conversation does not stall.
            return await self._handle_free_text(event=event, doctor=doctor)

        logger.warning(
            "wabot.registered.unknown_state",
            state=current_state.value,
        )
        return _result_text(
            MessageSymbol.MSG_REGISTERED_FALLBACK_CHOOSE_OPTION,
            event=event,
            next_state=RegisteredState.AWAITING_FREE_TEXT,
            expected=ExpectedInputKind.FREE_TEXT,
        )

    # ------------------------------------------------------------------
    # Consent
    # ------------------------------------------------------------------
    async def _send_consent_template(
        self,
        *,
        event: CanonicalInboundEvent,
        doctor: Doctor,
        consent_repo: ConsentRepository,
        onboarding_repo: OnboardingRepository,
    ) -> JourneyResult:
        settings = get_settings()
        await consent_repo.upsert_pending(doctor_id=doctor.id)
        await onboarding_repo.mark_onboarded(doctor.id)
        intent = build_template(
            symbol=MessageSymbol.TEMPLATE_DOCTOR_WELCOME_CONSENT,
            full_phone_number=event.full_phone_number,
            template_name=settings.template_doctor_welcome_consent,
            template_locale=settings.template_locale,
            body_values=(_doctor_display_name(doctor),),
        )
        return JourneyResult(
            next_journey=JourneyType.REGISTERED,
            next_registered_state=RegisteredState.CONSENT_PENDING,
            expected_input_kind=ExpectedInputKind.BUTTON,
            retry_count=0,
            outbound_intents=(intent,),
        )

    async def _handle_consent_reply(
        self,
        *,
        event: CanonicalInboundEvent,
        doctor: Doctor,
        consent_repo: ConsentRepository,
    ) -> JourneyResult:
        if event.event_kind != EventKind.USER_BUTTON_REPLY or event.button_text is None:
            return _result_text(
                MessageSymbol.MSG_REGISTERED_FALLBACK_CHOOSE_OPTION,
                event=event,
                next_state=RegisteredState.CONSENT_PENDING,
                expected=ExpectedInputKind.BUTTON,
            )
        title = event.button_text.strip().lower()
        correlation_uuid = _safe_uuid(event.correlation_id)
        if title == _CONSENT_ACCEPT_TITLE.lower():
            await consent_repo.set_status(
                doctor_id=doctor.id,
                status=ConsentStatus.ACCEPTED,
                correlation_id=correlation_uuid,
            )
            return _result_consent_accepted(
                full_phone_number=event.full_phone_number,
                doctor=doctor,
            )
        if title == _CONSENT_DECLINE_TITLE.lower():
            await consent_repo.set_status(
                doctor_id=doctor.id,
                status=ConsentStatus.DECLINED,
                correlation_id=correlation_uuid,
            )
            return _result_text(
                MessageSymbol.MSG_REGISTERED_CONSENT_DECLINED,
                event=event,
                next_state=RegisteredState.CONSENT_DECLINED,
                expected=ExpectedInputKind.FREE_TEXT,
            )
        return _result_text(
            MessageSymbol.MSG_REGISTERED_FALLBACK_CHOOSE_OPTION,
            event=event,
            next_state=RegisteredState.CONSENT_PENDING,
            expected=ExpectedInputKind.BUTTON,
        )

    # ------------------------------------------------------------------
    # Ice-breaker (CONSENT_ACCEPTED state)
    # ------------------------------------------------------------------
    async def _handle_icebreaker_or_free_text(
        self,
        *,
        event: CanonicalInboundEvent,
        doctor: Doctor,
    ) -> JourneyResult:
        # The ice-breaker template ships a SINGLE button: "Call hotline".
        # The user is otherwise free to type their query directly —
        # that goes straight into the GenAI free-text flow.
        if event.event_kind == EventKind.USER_BUTTON_REPLY and event.button_text:
            title = event.button_text.strip().lower()
            if title == "call hotline":
                return self._send_hotline_template(
                    full_phone_number=event.full_phone_number,
                    doctor=doctor,
                )
        # Anything else: treat as a free-text query (Case R11 — context
        # says free text after consent should flow into GenAI).
        return await self._handle_free_text(event=event, doctor=doctor)

    # ------------------------------------------------------------------
    # AWAITING_FREE_TEXT — GenAI loop
    # ------------------------------------------------------------------
    async def _handle_free_text(
        self,
        *,
        event: CanonicalInboundEvent,
        doctor: Doctor,
    ) -> JourneyResult:
        user_message = (event.text or event.button_text or "").strip()
        if not user_message:
            return _result_text(
                MessageSymbol.MSG_REGISTERED_FALLBACK_CHOOSE_OPTION,
                event=event,
                next_state=RegisteredState.AWAITING_FREE_TEXT,
                expected=ExpectedInputKind.FREE_TEXT,
            )

        request = GenAIRequest(
            conversation_id=str(doctor.id),
            doctor_id=str(doctor.id),
            user_message=user_message,
            current_state=RegisteredState.AWAITING_FREE_TEXT.value,
        )
        try:
            response = await self._genai_port.generate(request)
        except GenAIServiceError as exc:
            logger.warning(
                "wabot.registered.genai_failed",
                reason=str(exc),
                doctor_id=str(doctor.id),
            )
            return _result_text(
                MessageSymbol.MSG_REGISTERED_FALLBACK_GENAI_FAILED,
                event=event,
                next_state=RegisteredState.AWAITING_FREE_TEXT,
                expected=ExpectedInputKind.FREE_TEXT,
            )

        if response.intent == "hotline" or response.requires_hotline:
            return self._send_hotline_template(
                full_phone_number=event.full_phone_number,
                doctor=doctor,
            )
        if response.intent == "fallback":
            return _result_text(
                MessageSymbol.MSG_REGISTERED_FALLBACK_GENAI_FAILED,
                event=event,
                next_state=RegisteredState.AWAITING_FREE_TEXT,
                expected=ExpectedInputKind.FREE_TEXT,
            )

        answer_text = response.answer_text
        if response.app_link:
            answer_text = f"{answer_text}\n\n{response.app_link}"

        intents: tuple[OutboundIntent, ...]
        if response.query_nature == "scientific":
            ack = (
                build_text(
                    symbol=MessageSymbol.MSG_REGISTERED_ACK_THINKING,
                    full_phone_number=event.full_phone_number,
                )
                if response.send_processing_message
                else None
            )
            answer_intent = build_buttons(
                symbol=MessageSymbol.MSG_REGISTERED_ANSWER_WITH_BUTTONS,
                full_phone_number=event.full_phone_number,
                text_override=answer_text,
                buttons=(
                    (ButtonId.REGISTERED_ANSWER_SATISFIED, "Satisfied"),
                    (ButtonId.REGISTERED_ANSWER_CALL_HOTLINE, "Call hotline"),
                ),
            )
            intents = (ack, answer_intent) if ack is not None else (answer_intent,)
            return JourneyResult(
                next_journey=JourneyType.REGISTERED,
                next_registered_state=RegisteredState.AWAITING_ANSWER_BUTTON,
                expected_input_kind=ExpectedInputKind.BUTTON,
                retry_count=0,
                outbound_intents=intents,
            )

        # Non-scientific: plain text answer only.
        answer_intent = build_text(
            symbol=MessageSymbol.MSG_REGISTERED_ANSWER_TEXT,
            full_phone_number=event.full_phone_number,
            text_override=answer_text,
        )
        return JourneyResult(
            next_journey=JourneyType.REGISTERED,
            next_registered_state=RegisteredState.AWAITING_FREE_TEXT,
            expected_input_kind=ExpectedInputKind.FREE_TEXT,
            retry_count=0,
            outbound_intents=(answer_intent,),
        )

    # ------------------------------------------------------------------
    # AWAITING_ANSWER_BUTTON
    # ------------------------------------------------------------------
    async def _handle_answer_button(
        self,
        *,
        event: CanonicalInboundEvent,
        doctor: Doctor,
    ) -> JourneyResult:
        if event.event_kind == EventKind.USER_BUTTON_REPLY and event.button_text:
            title = event.button_text.strip().lower()
            if title == "satisfied":
                name = _doctor_display_name(doctor)
                return _result_text_simple(
                    full_phone_number=event.full_phone_number,
                    text=f"Thank you, {name}.\nGlad I could help.",
                    next_state=RegisteredState.AWAITING_FREE_TEXT,
                    expected=ExpectedInputKind.FREE_TEXT,
                )
            if title == "call hotline":
                return self._send_hotline_template(
                    full_phone_number=event.full_phone_number,
                    doctor=doctor,
                )
        # Free text post-answer → next query (per §11.5).
        return await self._handle_free_text(event=event, doctor=doctor)

    # ------------------------------------------------------------------
    # Hotline template
    # ------------------------------------------------------------------
    def _send_hotline_template(
        self,
        *,
        full_phone_number: str,
        doctor: Doctor,
    ) -> JourneyResult:
        settings = get_settings()
        intent = build_template(
            symbol=MessageSymbol.TEMPLATE_HOTLINE,
            full_phone_number=full_phone_number,
            template_name=settings.template_hotline,
            template_locale=settings.template_locale,
            body_values=(_doctor_display_name(doctor),),
        )
        return JourneyResult(
            next_journey=JourneyType.REGISTERED,
            next_registered_state=RegisteredState.HOTLINE_TEMPLATE_SENT,
            expected_input_kind=ExpectedInputKind.FREE_TEXT,
            retry_count=0,
            outbound_intents=(intent,),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _doctor_display_name(doctor: Doctor) -> str:
    first = doctor.first_name or "Doctor"
    last = doctor.last_name or ""
    name = f"{first} {last}".strip()
    return name or "Doctor"


def _safe_uuid(raw: str | None) -> _uuid.UUID | None:
    if not raw:
        return None
    try:
        return _uuid.UUID(raw)
    except ValueError:
        return None


def _result_consent_accepted(*, full_phone_number: str, doctor: Doctor) -> JourneyResult:
    name = _doctor_display_name(doctor)
    ack = build_text(
        symbol=MessageSymbol.MSG_REGISTERED_CONSENT_ACK,
        full_phone_number=full_phone_number,
        text_override=(f"Thank you, {name}.\nYour consent has been recorded successfully."),
    )
    icebreaker = build_buttons(
        symbol=MessageSymbol.MSG_REGISTERED_ICEBREAKER,
        full_phone_number=full_phone_number,
        text_override=(
            f"Thank you {name},\n"
            "You can now start asking your product or medical information "
            "queries here in chat, and I will assist you with the relevant "
            "information.\U0001f60a\n"
            "If you need immediate support, you may connect with hotline "
            "support.\U0001f4de"
        ),
        buttons=((ButtonId.REGISTERED_ICEBREAKER_CALL_HOTLINE, "Call hotline"),),
    )
    return JourneyResult(
        next_journey=JourneyType.REGISTERED,
        next_registered_state=RegisteredState.CONSENT_ACCEPTED,
        expected_input_kind=ExpectedInputKind.BUTTON,
        retry_count=0,
        outbound_intents=(ack, icebreaker),
    )


def _result_text(
    symbol: MessageSymbol,
    *,
    event: CanonicalInboundEvent,
    next_state: RegisteredState,
    expected: ExpectedInputKind,
) -> JourneyResult:
    intent = build_text(symbol=symbol, full_phone_number=event.full_phone_number)
    return JourneyResult(
        next_journey=JourneyType.REGISTERED,
        next_registered_state=next_state,
        expected_input_kind=expected,
        retry_count=0,
        outbound_intents=(intent,),
    )


def _result_text_simple(
    *,
    full_phone_number: str,
    text: str,
    next_state: RegisteredState,
    expected: ExpectedInputKind,
) -> JourneyResult:
    intent = build_text(
        symbol=MessageSymbol.MSG_REGISTERED_ANSWER_TEXT,
        full_phone_number=full_phone_number,
        text_override=text,
    )
    return JourneyResult(
        next_journey=JourneyType.REGISTERED,
        next_registered_state=next_state,
        expected_input_kind=expected,
        retry_count=0,
        outbound_intents=(intent,),
    )


register_journey_handler(JourneyType.REGISTERED, RegisteredJourneyHandler())


__all__ = ["RegisteredJourneyHandler"]
