"""Journey handler protocols + registry + no-op fallbacks.

See `wabot.domain.journeys.__init__` for the contract overview.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from wabot.domain.enums import (
    ExpectedInputKind,
    JourneyType,
    RegisteredState,
    RegistrationState,
)
from wabot.infra.logging import get_logger

if TYPE_CHECKING:
    import uuid
    from collections.abc import Mapping

    from sqlalchemy.ext.asyncio import AsyncSession

    from wabot.data.models.doctor import Doctor
    from wabot.data.models.journey import JourneyState
    from wabot.domain.events import CanonicalInboundEvent
    from wabot.domain.router import RoutingDecision

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class JourneyResult:
    """Output of a journey handler. Persisted by the orchestrator.

    `outbound_intents` is loosely typed (`tuple[Any, ...]`) at this
    phase because Phase 6 introduces the concrete `OutboundIntent`
    model. The orchestrator treats the tuple opaquely and forwards it
    to the outbound dispatcher.
    """

    next_journey: JourneyType
    next_registration_state: RegistrationState | None = None
    next_registered_state: RegisteredState | None = None
    expected_input_kind: ExpectedInputKind | None = None
    expected_outbound_id: uuid.UUID | None = None
    retry_count: int = 0
    context_patch: Mapping[str, Any] = field(default_factory=dict)
    outbound_intents: tuple[Any, ...] = ()


@runtime_checkable
class JourneyHandler(Protocol):
    """Stateless transition function for one user-event."""

    async def handle(
        self,
        *,
        event: CanonicalInboundEvent,
        decision: RoutingDecision,
        journey: JourneyState | None,
        doctor: Doctor | None,
        session: AsyncSession,
    ) -> JourneyResult: ...


@runtime_checkable
class OutboundStatusHandler(Protocol):
    """Applies an outbound status / click event to `outbound_message`.

    Phase 10 supplies the real implementation. Phase 5 ships a no-op
    that just logs so the orchestrator's status-event branch is
    exercised end-to-end.
    """

    async def handle(
        self,
        *,
        event: CanonicalInboundEvent,
        session: AsyncSession,
    ) -> None: ...


# ---------------------------------------------------------------------------
# Default handlers
# ---------------------------------------------------------------------------


class NoopJourneyHandler:
    """Handler that simply persists the routed initial / current state.

    Used as the registry fallback before Phases 7/8 land. It returns
    the state implied by the routing decision (or, on resume, the
    current journey row) and emits no outbound intents — the worker
    can therefore drain the broker without crashing while the journey
    logic is still under construction.
    """

    async def handle(
        self,
        *,
        event: CanonicalInboundEvent,
        decision: RoutingDecision,
        journey: JourneyState | None,
        doctor: Doctor | None,
        session: AsyncSession,
    ) -> JourneyResult:
        del event, doctor, session  # unused in the no-op
        if decision.is_resume and journey is not None:
            logger.info(
                "wabot.journey.noop_resume",
                case=decision.case.value,
                journey=journey.journey.value,
            )
            return JourneyResult(
                next_journey=journey.journey,
                next_registration_state=journey.state_registration,
                next_registered_state=journey.state_registered,
                expected_input_kind=_coerce_expected(journey.expected_input_kind),
                expected_outbound_id=journey.expected_outbound_id,
                retry_count=journey.retry_count,
                context_patch=dict(journey.context or {}),
            )
        if decision.journey is None:
            msg = "NoopJourneyHandler called without a target journey"
            raise RuntimeError(msg)
        logger.info(
            "wabot.journey.noop_fresh",
            case=decision.case.value,
            journey=decision.journey.value,
        )
        return JourneyResult(
            next_journey=decision.journey,
            next_registration_state=decision.initial_registration_state,
            next_registered_state=decision.initial_registered_state,
            expected_input_kind=decision.expected_input_kind,
        )


class NoopOutboundStatusHandler:
    """Logs the status event and does nothing else.

    Phase 10 replaces this with a real `outbound_message` updater.
    """

    async def handle(
        self,
        *,
        event: CanonicalInboundEvent,
        session: AsyncSession,
    ) -> None:
        del session
        logger.info(
            "wabot.outbound_status.noop",
            event_kind=event.event_kind.value,
            interakt_message_id=event.interakt_message_id,
            referenced_outbound_message_id=(
                str(event.referenced_outbound_message_id)
                if event.referenced_outbound_message_id
                else None
            ),
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


_journey_handlers: dict[JourneyType, JourneyHandler] = {}
_outbound_status_handler: OutboundStatusHandler = NoopOutboundStatusHandler()
_default_journey_handler: JourneyHandler = NoopJourneyHandler()


def register_journey_handler(journey: JourneyType, handler: JourneyHandler) -> None:
    """Register `handler` for `journey`. Phases 7 and 8 call this on import."""
    _journey_handlers[journey] = handler


def get_journey_handler(journey: JourneyType) -> JourneyHandler:
    """Return the handler for `journey`, falling back to the no-op."""
    return _journey_handlers.get(journey, _default_journey_handler)


def register_outbound_status_handler(handler: OutboundStatusHandler) -> None:
    """Register the outbound-status handler. Phase 10 calls this."""
    global _outbound_status_handler  # noqa: PLW0603 - module-level registry
    _outbound_status_handler = handler


def get_outbound_status_handler() -> OutboundStatusHandler:
    """Return the registered outbound-status handler (or the no-op)."""
    return _outbound_status_handler


def reset_handlers_for_tests() -> None:
    """Clear the registries to defaults. Test-only seam."""
    global _outbound_status_handler  # noqa: PLW0603 - module-level registry
    _journey_handlers.clear()
    _outbound_status_handler = NoopOutboundStatusHandler()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_expected(value: str | None) -> ExpectedInputKind | None:
    if value is None:
        return None
    try:
        return ExpectedInputKind(value)
    except ValueError:
        return None
