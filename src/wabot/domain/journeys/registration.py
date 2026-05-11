"""Registration journey handler (implementation_plan.md §Phase 7).

Wires the routing decisions from `domain.router` (Cases A and D) into
the registration state machine declared in
`domain.enums.RegistrationState`.

The handler is **pure of wire-side effects**: it only mutates DB rows
through repositories and returns a `JourneyResult` whose
``outbound_intents`` the orchestrator dispatches after the journey
state transaction commits. It NEVER calls Interakt directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from wabot.data.repositories.doctor_repo import DoctorRepository
from wabot.domain.enums import (
    ExpectedInputKind,
    JourneyType,
    RegistrationState,
)
from wabot.domain.events import EventKind
from wabot.domain.journeys.base import (
    JourneyResult,
    register_journey_handler,
)
from wabot.domain.messages.builder import build_buttons, build_text
from wabot.domain.messages.catalog import ButtonId, MessageSymbol
from wabot.domain.parsers.registration import (
    RegistrationParseError,
    parse_registration,
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


# Button titles attached to MSG_REG_PARTIAL_CONFIRM_PROMPT. Kept here so
# the handler can also match on `event.button_text` for the inbound reply
# (Interakt echoes the title, not the id, in `message_received` events).
_PARTIAL_CONFIRM_YES_TITLE = "Yes"
_PARTIAL_CONFIRM_NO_TITLE = "No"

# States that consume a free-text registration payload.
_TEXT_INPUT_STATES = frozenset(
    {
        RegistrationState.AWAITING_FULL_DETAILS,
        RegistrationState.AWAITING_CORRECTED_FULL,
        RegistrationState.AWAITING_REMAINING_DETAILS,
    }
)


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
        # Fresh entry paths (Case A unknown, or defensive Case D no-journey)
        # ------------------------------------------------------------------
        if journey is None:
            return await self._handle_fresh_entry(
                event=event,
                doctor=doctor,
                repo=repo,
            )

        # ------------------------------------------------------------------
        # Resume — dispatch on current registration state
        # ------------------------------------------------------------------
        current_state = journey.state_registration
        if current_state is None:
            # Defensive: a registration journey row without a registration
            # state means data corruption; restart from the entry prompt
            # so the user is not stuck.
            logger.warning(
                "wabot.registration.missing_state",
                doctor_id=str(journey.doctor_id),
            )
            return _prompt_full_details(
                full_phone_number=event.full_phone_number,
                retry_count=0,
            )

        if current_state in _TEXT_INPUT_STATES:
            return await self._handle_text_input(
                event=event,
                journey=journey,
                repo=repo,
            )

        if current_state == RegistrationState.PARTIAL_CONFIRM_PENDING:
            return await self._handle_partial_confirm(
                event=event,
                journey=journey,
                doctor=doctor,
                repo=repo,
            )

        if current_state in {
            RegistrationState.REG_INITIATED,
        }:
            # The very first inbound after REG_INITIATED is the user's
            # opening message; respond with the prompt and advance.
            return _prompt_full_details(
                full_phone_number=event.full_phone_number,
                retry_count=0,
            )

        # Terminal states (REGISTRATION_COMPLETED / ASSISTED_SUPPORT) — no-op.
        # The router will pick a different journey on the next inbound once
        # the doctor row reflects completion.
        logger.info(
            "wabot.registration.terminal_noop",
            state=current_state.value,
            doctor_id=str(journey.doctor_id),
        )
        return JourneyResult(
            next_journey=JourneyType.REGISTRATION,
            next_registration_state=current_state,
            expected_input_kind=ExpectedInputKind.REGISTRATION_TEXT,
            retry_count=journey.retry_count,
        )

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
            # Case A — brand new phone. Create the shell row.
            await repo.create_shell(event.full_phone_number)
            return _prompt_full_details(
                full_phone_number=event.full_phone_number,
                retry_count=0,
            )

        # Case D defensive — doctor exists, profile incomplete, but no
        # journey row. If we have any preloaded fields (CSV seed), offer
        # the partial-confirm flow; otherwise treat as fresh.
        if _has_partial_data(doctor):
            return _prompt_partial_confirm(full_phone_number=event.full_phone_number)
        return _prompt_full_details(
            full_phone_number=event.full_phone_number,
            retry_count=0,
        )

    # ------------------------------------------------------------------
    # Text-input states
    # ------------------------------------------------------------------
    async def _handle_text_input(
        self,
        *,
        event: CanonicalInboundEvent,
        journey: JourneyState,
        repo: DoctorRepository,
    ) -> JourneyResult:
        try:
            parsed = parse_registration(event.text)
        except RegistrationParseError as exc:
            return self._handle_parse_failure(
                event=event,
                journey=journey,
                reason=exc.reason,
                field=exc.field,
            )

        await repo.upsert_profile(
            full_phone_number=event.full_phone_number,
            first_name=parsed.first_name,
            last_name=parsed.last_name,
            speciality=parsed.speciality,
            email=parsed.email,
            address=parsed.address,
            city=parsed.city,
            state=parsed.state,
            pincode=parsed.pincode,
            is_profile_complete=True,
        )
        logger.info(
            "wabot.registration.completed",
            full_phone_number=event.full_phone_number,
        )
        return _result_completed(full_phone_number=event.full_phone_number)

    def _handle_parse_failure(
        self,
        *,
        event: CanonicalInboundEvent,
        journey: JourneyState,
        reason: str,
        field: str | None,
    ) -> JourneyResult:
        settings = get_settings()
        next_retry = journey.retry_count + 1
        logger.info(
            "wabot.registration.parse_failed",
            reason=reason,
            field=field,
            retry_count=next_retry,
            max_retries=settings.registration_max_retries,
        )
        if next_retry > settings.registration_max_retries:
            return _result_assisted_support(full_phone_number=event.full_phone_number)
        intent = build_text(
            symbol=MessageSymbol.MSG_REG_RETRY_PROMPT,
            full_phone_number=event.full_phone_number,
        )
        return JourneyResult(
            next_journey=JourneyType.REGISTRATION,
            next_registration_state=RegistrationState.AWAITING_CORRECTED_FULL,
            expected_input_kind=ExpectedInputKind.REGISTRATION_TEXT,
            retry_count=next_retry,
            outbound_intents=(intent,),
        )

    # ------------------------------------------------------------------
    # PARTIAL_CONFIRM_PENDING
    # ------------------------------------------------------------------
    async def _handle_partial_confirm(
        self,
        *,
        event: CanonicalInboundEvent,
        journey: JourneyState,
        doctor: Doctor | None,
        repo: DoctorRepository,
    ) -> JourneyResult:
        if event.event_kind != EventKind.USER_BUTTON_REPLY or event.button_text is None:
            return _result_partial_confirm_fallback(
                full_phone_number=event.full_phone_number,
                retry_count=journey.retry_count,
            )

        title = event.button_text.strip().lower()
        if title == _PARTIAL_CONFIRM_YES_TITLE.lower():
            if doctor is None:
                logger.warning(
                    "wabot.registration.partial_confirm_no_doctor",
                    doctor_id=str(journey.doctor_id),
                )
                return _prompt_full_details(
                    full_phone_number=event.full_phone_number,
                    retry_count=0,
                )
            await repo.upsert_profile(
                full_phone_number=event.full_phone_number,
                first_name=doctor.first_name,
                last_name=doctor.last_name,
                speciality=doctor.speciality,
                email=doctor.email,
                address=doctor.address,
                city=doctor.city,
                state=doctor.state,
                pincode=doctor.pincode,
                is_profile_complete=True,
            )
            return _result_completed(full_phone_number=event.full_phone_number)

        if title == _PARTIAL_CONFIRM_NO_TITLE.lower():
            return _prompt_full_details(
                full_phone_number=event.full_phone_number,
                retry_count=0,
            )

        # Unknown button title — fall back to re-prompt.
        return _result_partial_confirm_fallback(
            full_phone_number=event.full_phone_number,
            retry_count=journey.retry_count,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_partial_data(doctor: Doctor) -> bool:
    return any(
        getattr(doctor, field) is not None
        for field in (
            "first_name",
            "last_name",
            "speciality",
            "email",
            "address",
            "city",
            "state",
            "pincode",
        )
    )


def _prompt_full_details(
    *,
    full_phone_number: str,
    retry_count: int,
) -> JourneyResult:
    intent: OutboundIntent = build_text(
        symbol=MessageSymbol.MSG_REG_FULL_DETAILS_PROMPT,
        full_phone_number=full_phone_number,
    )
    return JourneyResult(
        next_journey=JourneyType.REGISTRATION,
        next_registration_state=RegistrationState.AWAITING_FULL_DETAILS,
        expected_input_kind=ExpectedInputKind.REGISTRATION_TEXT,
        retry_count=retry_count,
        outbound_intents=(intent,),
    )


def _prompt_partial_confirm(*, full_phone_number: str) -> JourneyResult:
    intent = build_buttons(
        symbol=MessageSymbol.MSG_REG_PARTIAL_CONFIRM_PROMPT,
        full_phone_number=full_phone_number,
        buttons=(
            (ButtonId.REG_PARTIAL_CONFIRM_YES, _PARTIAL_CONFIRM_YES_TITLE),
            (ButtonId.REG_PARTIAL_CONFIRM_NO, _PARTIAL_CONFIRM_NO_TITLE),
        ),
    )
    return JourneyResult(
        next_journey=JourneyType.REGISTRATION,
        next_registration_state=RegistrationState.PARTIAL_CONFIRM_PENDING,
        expected_input_kind=ExpectedInputKind.BUTTON,
        retry_count=0,
        outbound_intents=(intent,),
    )


def _result_completed(*, full_phone_number: str) -> JourneyResult:
    intent = build_text(
        symbol=MessageSymbol.MSG_REG_COMPLETED,
        full_phone_number=full_phone_number,
    )
    return JourneyResult(
        next_journey=JourneyType.REGISTRATION,
        next_registration_state=RegistrationState.REGISTRATION_COMPLETED,
        expected_input_kind=ExpectedInputKind.FREE_TEXT,
        retry_count=0,
        outbound_intents=(intent,),
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
        retry_count=0,
        outbound_intents=(intent,),
    )


def _result_partial_confirm_fallback(
    *,
    full_phone_number: str,
    retry_count: int,
) -> JourneyResult:
    intent = build_text(
        symbol=MessageSymbol.MSG_REGISTERED_FALLBACK_CHOOSE_OPTION,
        full_phone_number=full_phone_number,
    )
    return JourneyResult(
        next_journey=JourneyType.REGISTRATION,
        next_registration_state=RegistrationState.PARTIAL_CONFIRM_PENDING,
        expected_input_kind=ExpectedInputKind.BUTTON,
        retry_count=retry_count,
        outbound_intents=(intent,),
    )


# Register on module import so any consumer that imports
# `wabot.domain.journeys` (which re-exports this module) auto-wires the
# handler into the registry.
register_journey_handler(JourneyType.REGISTRATION, RegistrationJourneyHandler())


__all__ = ["RegistrationJourneyHandler"]
