"""Journey handler framework.

Phases 7 (registration) and 8 (registered/consent) plug concrete
handlers into the registry exposed here. Phase 5 only wires the
*scaffolding* — the orchestrator can dispatch to a registered handler
or fall back to the no-op handler so the worker stays alive even
before the journey logic is implemented.

Contract (implementation_plan.md §7.4):

* Each handler receives the canonical event, the routing decision (so
  the handler knows whether it is a fresh entry or a resume), the
  current journey row (`None` if fresh), the doctor row (`None` only
  in Case A), and the active SQLAlchemy session for any reads/writes
  it needs to do.
* The handler returns a `JourneyResult` describing the next state, the
  expected next input kind, any context patch, and the list of
  outbound intents to dispatch.
* The orchestrator persists the next state and dispatches outbound
  intents **after** the handler returns (so handlers stay pure of
  side-effects on the wire).
"""

from wabot.domain.journeys.base import (
    JourneyHandler,
    JourneyResult,
    NoopJourneyHandler,
    NoopOutboundStatusHandler,
    OutboundStatusHandler,
    get_journey_handler,
    get_outbound_status_handler,
    register_journey_handler,
    register_outbound_status_handler,
    reset_handlers_for_tests,
)

__all__ = [
    "JourneyHandler",
    "JourneyResult",
    "NoopJourneyHandler",
    "NoopOutboundStatusHandler",
    "OutboundStatusHandler",
    "get_journey_handler",
    "get_outbound_status_handler",
    "register_journey_handler",
    "register_outbound_status_handler",
    "reset_handlers_for_tests",
]
