"""Free-text router (implementation_plan.md §6).

Given an inbound user-originated event together with whatever the DB
currently knows about the doctor (doctor record, journey state,
onboarding status), decide which **journey + initial state** the
orchestrator should dispatch into.

The router is a **pure function** - it takes already-loaded snapshots
and returns a `RoutingDecision`. All DB access is the orchestrator's
responsibility (so this module stays trivially unit-testable and free
of session lifecycle concerns).

Out of scope here:

* Status events (``outbound_sent`` / ``delivered`` / ``read`` /
  ``failed`` / ``clicked``) - those are routed to the outbound-status
  updater (Phase 10), not a journey handler.
* Resolving stale historical button clicks via `callback_data` - that
  belongs inside the registered-journey handler (§7.8).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from wabot.domain.enums import (
    ExpectedInputKind,
    JourneyType,
    RegisteredState,
    RegistrationState,
)
from wabot.domain.events import USER_EVENT_KINDS

if TYPE_CHECKING:
    from wabot.data.models.doctor import Doctor
    from wabot.data.models.journey import JourneyState
    from wabot.data.models.onboarding import WhatsappOnboardingStatus
    from wabot.domain.events import CanonicalInboundEvent


class RoutingCase(StrEnum):
    """Identifier for the implemented routing branches."""

    A_UNKNOWN_USER = "case_a_unknown_user"
    """Phone is not in `doctor`. Start a new registration journey."""

    B_RESUME_REGISTERED = "case_b_resume_registered"
    """Profile complete + already onboarded. Resume the registered journey."""

    C_TRIGGER_CONSENT = "case_c_trigger_consent"
    """Profile complete but never onboarded. Send the consent template."""

    RESUME_REGISTRATION = "resume_registration"
    """Active registration journey exists. Resume it where it stopped."""

    NON_USER_EVENT = "non_user_event"
    """Status / click event - caller routes to the outbound-status updater."""


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """Result of `route_user_event` consumed by the orchestrator.

    Attributes:
        case: Which route branch this is, for observability.
        journey: Which top-level journey the handler dispatch table
            should index into.
        initial_registration_state / initial_registered_state: The
            state to enter **only when there is no existing journey
            row** (Cases A/C and defensive registered resume).
            When `is_resume` is True the orchestrator must keep the
            current journey row's state and only update
            `last_processed_event_id`.
        expected_input_kind: What the next inbound from this user is
            expected to look like - drives validation / fallback
            messaging in the journey handler.
        is_resume: True iff the caller should continue the existing
            journey row instead of resetting it.
    """

    case: RoutingCase
    journey: JourneyType | None
    initial_registration_state: RegistrationState | None = None
    initial_registered_state: RegisteredState | None = None
    expected_input_kind: ExpectedInputKind | None = None
    is_resume: bool = False


_NON_USER_DECISION = RoutingDecision(
    case=RoutingCase.NON_USER_EVENT,
    journey=None,
)


def route_user_event(
    *,
    event: CanonicalInboundEvent,
    doctor: Doctor | None,
    journey: JourneyState | None,
    onboarding: WhatsappOnboardingStatus | None,
) -> RoutingDecision:
    """Classify an inbound event into the active journey branch.

    Status / click events return `RoutingCase.NON_USER_EVENT` and the
    caller must route them to the outbound-status updater rather than
    a journey handler.
    """
    if event.event_kind not in USER_EVENT_KINDS:
        return _NON_USER_DECISION

    # If registration is already active, keep it active. This covers a
    # brand-new user who has a shell doctor row but has not submitted the
    # WhatsApp Flow form yet.
    if journey is not None and journey.journey == JourneyType.REGISTRATION:
        return RoutingDecision(
            case=RoutingCase.RESUME_REGISTRATION,
            journey=JourneyType.REGISTRATION,
            is_resume=True,
        )

    # Case A - phone unknown. The registration handler will create the
    # `doctor` shell row inside its first transition.
    if doctor is None:
        return RoutingDecision(
            case=RoutingCase.A_UNKNOWN_USER,
            journey=JourneyType.REGISTRATION,
            initial_registration_state=RegistrationState.REG_INITIATED,
            expected_input_kind=ExpectedInputKind.REGISTRATION_TEXT,
            is_resume=False,
        )

    # Known doctor - either trigger consent or resume registered journey.
    is_onboarded = bool(onboarding is not None and onboarding.is_onboarded)

    if not is_onboarded:
        # Case C - first time we are talking to this fully-registered
        # doctor on WhatsApp. Send the consent template.
        return RoutingDecision(
            case=RoutingCase.C_TRIGGER_CONSENT,
            journey=JourneyType.REGISTERED,
            initial_registered_state=RegisteredState.CONSENT_PENDING,
            expected_input_kind=ExpectedInputKind.BUTTON,
            is_resume=False,
        )

    # Case B - fully registered, already onboarded.
    if journey is not None and journey.journey == JourneyType.REGISTERED:
        decision_b = RoutingDecision(
            case=RoutingCase.B_RESUME_REGISTERED,
            journey=JourneyType.REGISTERED,
            is_resume=True,
        )
    else:
        # Defensive: registered + onboarded but no journey row. Default to
        # the free-text waiting state so the handler picks it up.
        decision_b = RoutingDecision(
            case=RoutingCase.B_RESUME_REGISTERED,
            journey=JourneyType.REGISTERED,
            initial_registered_state=RegisteredState.AWAITING_FREE_TEXT,
            expected_input_kind=ExpectedInputKind.FREE_TEXT,
            is_resume=False,
        )
    return decision_b
