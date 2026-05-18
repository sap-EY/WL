"""Registration journey handler (implementation_plan.md §Phase 7).

Wires the routing decisions from `domain.router` (Cases A and D) into
the simplified, form-based registration state machine declared in
`domain.enums.RegistrationState`.

Flow summary:

1. **Case A (fresh entry)** \u2014 a brand-new phone hits the webhook. We
   create the `doctor` shell row and dispatch the
   ``user_registration_v1`` template (CTA opens a WhatsApp Flow form
   inside the chat). Journey state advances to
   ``AWAITING_FULL_DETAILS`` \u2014 reused as "awaiting form submission".
2. **Form submission** \u2014 Interakt sends a
   ``message_api_flow_response`` webhook; the normalizer turns it into
   an ``EventKind.USER_FORM_REPLY``. The handler parses the
   ``response_json`` dict, upserts the profile (with email / address /
   city / state / pincode left ``NULL``), marks consent pending +
   onboarding initiated, and emits BOTH the completion text and the
   ``doctor_welcome_consent_v1`` template in a single dispatch.
   Journey transitions directly to ``REGISTERED / CONSENT_PENDING``
   so the next inbound (the consent button reply) is handled by
   `RegisteredJourneyHandler`.
3. **Non-form inbound while awaiting form** \u2014 user typed text
   instead of submitting the form. Re-send the form template so the
   user can tap "Register Now" again.

The handler is **pure of wire-side effects**: it only mutates DB rows
through repositories and returns a `JourneyResult` whose
``outbound_intents`` the orchestrator dispatches after the journey
state transaction commits. It NEVER calls Interakt directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from wabot.data.repositories.consent_repo import ConsentRepository
from wabot.data.repositories.doctor_repo import DoctorRepository
from wabot.data.repositories.onboarding_repo import OnboardingRepository
from wabot.domain.enums import (
    ExpectedInputKind,
    JourneyType,
    RegisteredState,
    RegistrationState,
)
from wabot.domain.events import EventKind
from wabot.domain.journeys.base import (
    JourneyResult,
    register_journey_handler,
)
from wabot.domain.messages.builder import build_template, build_text
from wabot.domain.messages.catalog import MessageSymbol
from wabot.domain.parsers.registration import (
    RegistrationParseError,
    parse_form_response,
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


class RegistrationJourneyHandler:
    """State-machine handler for `JourneyType.REGISTRATION`."""

    async def handle(
        self,
        *,
        event: CanonicalInboundEvent,
        decision: RoutingDecision,
        journey: JourneyState | None,
        doctor: Doctor | None,
        session: AsyncSession,
    ) -> JourneyResult:
        repo = DoctorRepository(session)

        # ------------------------------------------------------------------
        # Form-submission event \u2014 valid in any state, completes registration.
        # ------------------------------------------------------------------
        if event.event_kind == EventKind.USER_FORM_REPLY:
            return await self._handle_form_submission(
                event=event,
                repo=repo,
                consent_repo=ConsentRepository(session),
                onboarding_repo=OnboardingRepository(session),
            )

        # ------------------------------------------------------------------
        # Fresh entry paths (Case A unknown, or defensive Case D no-journey)
        # ------------------------------------------------------------------
        if journey is None:
            return await self._handle_fresh_entry(event=event, doctor=doctor, repo=repo)

        # ------------------------------------------------------------------
        # Resume \u2014 dispatch on current registration state
        # ------------------------------------------------------------------
        current_state = journey.state_registration

        # Terminal states are no-ops; the next router pass will pick a
        # different journey once the doctor row reflects completion.
        if current_state in {
            RegistrationState.REGISTRATION_COMPLETED,
            RegistrationState.ASSISTED_SUPPORT,
        }:
            logger.info(
                "wabot.registration.terminal_noop",
                state=current_state.value if current_state else None,
                doctor_id=str(journey.doctor_id),
            )
            return JourneyResult(
                next_journey=JourneyType.REGISTRATION,
                next_registration_state=current_state,
                expected_input_kind=ExpectedInputKind.REGISTRATION_TEXT,
            )

        # Any other state \u2014 user typed text instead of submitting the
        # form. Re-send the template so they can tap "Register Now".
        return _send_form_template(full_phone_number=event.full_phone_number)

    # ------------------------------------------------------------------
    # Fresh entry
    # ------------------------------------------------------------------
    async def _handle_fresh_entry(
        self,
        *,
        event: CanonicalInboundEvent,
        doctor: Doctor | None,
        repo: DoctorRepository,
    ) -> JourneyResult:
        if doctor is None:
            # Case A \u2014 brand new phone. Create the shell row so future
            # events have a doctor to attach to.
            await repo.create_shell(event.full_phone_number)
        return _send_form_template(full_phone_number=event.full_phone_number)

    # ------------------------------------------------------------------
    # Form submission
    # ------------------------------------------------------------------
    async def _handle_form_submission(
        self,
        *,
        event: CanonicalInboundEvent,
        repo: DoctorRepository,
        consent_repo: ConsentRepository,
        onboarding_repo: OnboardingRepository,
    ) -> JourneyResult:
        try:
            parsed = parse_form_response(event.form_response)
        except RegistrationParseError as exc:
            logger.warning(
                "wabot.registration.form_parse_failed",
                reason=exc.reason,
                field=exc.field,
                full_phone_number=event.full_phone_number,
            )
            # The Flow form is validated by WhatsApp itself, so a parse
            # failure here is essentially impossible \u2014 escalate so a
            # human can investigate rather than re-prompt.
            return _result_assisted_support(full_phone_number=event.full_phone_number)

        await repo.upsert_profile(
            full_phone_number=event.full_phone_number,
            first_name=parsed.first_name,
            last_name=parsed.last_name,
            speciality=parsed.speciality,
            mci_id=parsed.mci_id,
            # Email / address / city / state / pincode are NOT collected
            # by the Flow form. Persist as NULL so we can re-introduce
            # them later without a DB migration.
            email=None,
            address=None,
            city=None,
            state=None,
            pincode=None,
            is_profile_complete=True,
        )
        logger.info(
            "wabot.registration.completed",
            full_phone_number=event.full_phone_number,
        )

        # Per context_final.md §4 Case A: "on successful update, mark
        # registration completed → then initiate registered_users journey
        # by sending the consent template". We chain both intents in a
        # single dispatch so the user sees consent immediately after the
        # completion text, without needing another inbound to trigger
        # Case C.
        doctor = await repo.get_by_phone(event.full_phone_number)
        if doctor is not None:
            await consent_repo.upsert_pending(doctor_id=doctor.id)
            await onboarding_repo.mark_onboarded(doctor.id)

        return _result_completed(
            full_phone_number=event.full_phone_number,
            first_name=parsed.first_name,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _send_form_template(*, full_phone_number: str) -> JourneyResult:
    """Build the ``user_registration_v1`` flow-template intent."""
    settings = get_settings()
    intent: OutboundIntent = build_template(
        symbol=MessageSymbol.TEMPLATE_USER_REGISTRATION,
        full_phone_number=full_phone_number,
        template_name=settings.template_user_registration,
        template_locale=settings.template_locale,
        is_flow_template=True,
    )
    return JourneyResult(
        next_journey=JourneyType.REGISTRATION,
        next_registration_state=RegistrationState.AWAITING_FULL_DETAILS,
        expected_input_kind=ExpectedInputKind.REGISTRATION_TEXT,
        outbound_intents=(intent,),
    )


def _result_completed(*, full_phone_number: str, first_name: str | None = None) -> JourneyResult:
    settings = get_settings()
    name = (first_name or "").strip() or "Doctor"
    completion_intent = build_text(
        symbol=MessageSymbol.MSG_REG_COMPLETED,
        full_phone_number=full_phone_number,
        text_override=(
            f"Thank you, Dr. {name}.\nYour registration has been completed successfully."
        ),
    )
    consent_intent = build_template(
        symbol=MessageSymbol.TEMPLATE_DOCTOR_WELCOME_CONSENT,
        full_phone_number=full_phone_number,
        template_name=settings.template_doctor_welcome_consent,
        template_locale=settings.template_locale,
        body_values=(name,),
    )
    return JourneyResult(
        next_journey=JourneyType.REGISTERED,
        next_registered_state=RegisteredState.CONSENT_PENDING,
        expected_input_kind=ExpectedInputKind.BUTTON,
        outbound_intents=(completion_intent, consent_intent),
    )


def _result_assisted_support(*, full_phone_number: str) -> JourneyResult:
    intent = build_text(
        symbol=MessageSymbol.MSG_REG_ASSISTED_SUPPORT,
        full_phone_number=full_phone_number,
    )
    return JourneyResult(
        next_journey=JourneyType.REGISTRATION,
        next_registration_state=RegistrationState.ASSISTED_SUPPORT,
        expected_input_kind=ExpectedInputKind.FREE_TEXT,
        outbound_intents=(intent,),
    )


# Register on module import so any consumer that imports
# `wabot.domain.journeys` (which re-exports this module) auto-wires the
# handler into the registry.
register_journey_handler(JourneyType.REGISTRATION, RegistrationJourneyHandler())


__all__ = ["RegistrationJourneyHandler"]
