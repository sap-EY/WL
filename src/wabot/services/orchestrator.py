"""Inbound orchestrator (implementation_plan.md §6 Phase 5).

Responsibilities:

1. Pull a broker message (minimal pointer: webhook_event_raw.id +
   routing fields) and resolve it back to the durable raw row in
   Postgres.
2. Acquire the per-user Redis lock (`wabot:lock:user:{phone}`) so
   handlers are serialized per doctor.
3. Re-normalize the raw payload into a `CanonicalInboundEvent` (the
   normalizer is pure, so doing it here keeps the broker free of
   wire-shape coupling).
4. Branch:
   * **status / click events** → `OutboundStatusHandler` (Phase 10
     fills it; Phase 5 ships a no-op).
   * **user events** → load doctor + journey + onboarding rows,
     classify via `route_user_event`, dispatch to the registered
     `JourneyHandler` (Phases 7/8) and persist its `JourneyResult`.
5. Mark `webhook_event_raw.processed_at` and (for journey events)
   bump `journey_state.last_processed_event_id` so duplicates become
   no-ops on the next pass.

Design constraints (carried forward from earlier phases):

* The DB transaction is **short** and ends before any outbound work.
* Outbound dispatch happens *after* the session commits so a failure
  to send never rolls back persisted state. Phase 6 introduces the
  outbound dispatcher; Phase 5 collects intents and logs them.
* Idempotency: replay of the same `interakt_message_id` for the same
  doctor is detected via `journey_state.last_processed_event_id`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from wabot.adapters.interakt import NormalizationError, normalize
from wabot.cache.client import get_redis
from wabot.cache.locks import UserLock, UserLockUnavailableError
from wabot.data.db import session_scope
from wabot.data.models.onboarding import WhatsappOnboardingStatus
from wabot.data.models.webhook import WebhookEventRaw
from wabot.data.repositories.doctor_repo import DoctorRepository
from wabot.data.repositories.journey_repo import JourneyRepository
from wabot.domain.events import USER_EVENT_KINDS
from wabot.domain.journeys import (
    JourneyResult,
    get_journey_handler,
    get_outbound_status_handler,
)
from wabot.domain.router import RoutingDecision, route_user_event
from wabot.infra.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy.ext.asyncio import AsyncSession

    from wabot.adapters.broker.base import InboundMessage
    from wabot.data.models.doctor import Doctor
    from wabot.data.models.journey import JourneyState
    from wabot.domain.events import CanonicalInboundEvent
    from wabot.domain.outbound import OutboundIntent
    from wabot.infra.config import AppSettings
    from wabot.services.outbound_pipeline import OutboundPipeline

logger = get_logger(__name__)


class OrchestratorPoisonError(RuntimeError):
    """The message cannot be processed and should NOT be retried.

    Raised when the broker payload is missing required fields. The
    worker should ack the message to drain it (logging the failure)
    rather than spinning on a permanent error.
    """


@dataclass(frozen=True, slots=True)
class _DispatchPlan:
    """Outbound dispatch information captured during the locked
    transaction and consumed after it commits.
    """

    doctor_id: uuid.UUID
    state_when_sent: str | None
    intents: tuple[OutboundIntent, ...]


class Orchestrator:
    """Stateless coordinator. One instance per worker process."""

    def __init__(
        self,
        settings: AppSettings,
        *,
        pipeline: OutboundPipeline | None = None,
    ) -> None:
        self._settings = settings
        self._pipeline = pipeline

    async def handle_message(self, message: InboundMessage) -> bool:
        """Process one broker message.

        Returns:
            True if the broker entry should be acked (success or
            permanent skip). False if the entry should be left
            pending so the consumer-group machinery redelivers it
            (transient: lock contention, DB outage).
        """
        try:
            event_id = _required_uuid(message.payload, "event_id")
            full_phone_number = _required_str(message.payload, "full_phone_number")
        except OrchestratorPoisonError as exc:
            logger.error(
                "wabot.orchestrator.poison_payload",
                broker_message_id=message.message_id,
                error=str(exc),
            )
            return True

        correlation_id = str(message.payload.get("correlation_id") or message.message_id)
        log = logger.bind(
            broker_message_id=message.message_id,
            event_id=str(event_id),
            full_phone_number=full_phone_number,
            correlation_id=correlation_id,
        )

        try:
            async with UserLock(
                get_redis(self._settings),
                full_phone_number=full_phone_number,
                ttl_seconds=self._settings.redis_lock_ttl_seconds,
            ):
                plan = await self._handle_locked(
                    event_id=event_id,
                    correlation_id=correlation_id,
                    log=log,
                )
                if plan is not None and plan.intents and self._pipeline is not None:
                    await self._pipeline.dispatch(
                        plan.intents,
                        doctor_id=plan.doctor_id,
                        state_when_sent=plan.state_when_sent,
                        correlation_id=correlation_id,
                    )
                elif plan is not None and plan.intents:
                    log.info(
                        "wabot.orchestrator.outbound_intents_dropped_no_pipeline",
                        count=len(plan.intents),
                    )
        except UserLockUnavailableError:
            log.warning("wabot.orchestrator.lock_unavailable")
            return False
        except Exception as exc:
            log.error("wabot.orchestrator.unhandled_error", error=str(exc))
            return False
        return True

    async def _handle_locked(
        self,
        *,
        event_id: uuid.UUID,
        correlation_id: str,
        log: Any,
    ) -> _DispatchPlan | None:
        async with session_scope() as session:
            raw_row = await session.get(WebhookEventRaw, event_id)
            if raw_row is None:
                log.warning("wabot.orchestrator.raw_event_missing")
                return None
            if raw_row.processed_at is not None:
                log.info("wabot.orchestrator.raw_event_already_processed")
                return None

            try:
                event = normalize(
                    raw_event_id=raw_row.id,
                    correlation_id=correlation_id,
                    payload=raw_row.payload,
                )
            except NormalizationError as exc:
                log.warning("wabot.orchestrator.normalization_failed", error=str(exc))
                raw_row.processed_at = datetime.now(UTC)
                return None

            plan: _DispatchPlan | None = None
            if event.event_kind in USER_EVENT_KINDS:
                plan = await self._handle_user_event(session=session, event=event, log=log)
            else:
                await self._handle_status_event(session=session, event=event, log=log)

            raw_row.processed_at = datetime.now(UTC)
            return plan

    async def _handle_user_event(
        self,
        *,
        session: AsyncSession,
        event: CanonicalInboundEvent,
        log: Any,
    ) -> _DispatchPlan | None:
        doctor_repo = DoctorRepository(session)
        journey_repo = JourneyRepository(session)

        doctor = await doctor_repo.get_by_phone(event.full_phone_number)
        journey = await journey_repo.get(doctor.id) if doctor is not None else None
        onboarding = await _load_onboarding(session, doctor)

        if journey is not None and journey.last_processed_event_id == event.interakt_message_id:
            log.info(
                "wabot.orchestrator.duplicate_event",
                event_kind=event.event_kind.value,
                interakt_message_id=event.interakt_message_id,
            )
            return None

        decision = route_user_event(
            event=event,
            doctor=doctor,
            journey=journey,
            onboarding=onboarding,
        )
        log.info(
            "wabot.orchestrator.routed",
            case=decision.case.value,
            event_kind=event.event_kind.value,
            is_resume=decision.is_resume,
        )

        if decision.journey is None:
            # Should not happen for user events (router always picks a
            # journey), but keep the guard so a future router change
            # cannot silently drop messages.
            log.warning("wabot.orchestrator.no_journey_decision")
            return None

        handler = get_journey_handler(decision.journey)
        result = await handler.handle(
            event=event,
            decision=decision,
            journey=journey,
            doctor=doctor,
            session=session,
        )

        return await self._persist_result(
            session=session,
            event=event,
            decision=decision,
            doctor=doctor,
            journey=journey,
            result=result,
            log=log,
        )

    async def _handle_status_event(
        self,
        *,
        session: AsyncSession,
        event: CanonicalInboundEvent,
        log: Any,
    ) -> None:
        handler = get_outbound_status_handler()
        await handler.handle(event=event, session=session)
        log.info(
            "wabot.orchestrator.status_event_handled",
            event_kind=event.event_kind.value,
        )

    async def _persist_result(
        self,
        *,
        session: AsyncSession,
        event: CanonicalInboundEvent,
        decision: RoutingDecision,
        doctor: Doctor | None,
        journey: JourneyState | None,
        result: JourneyResult,
        log: Any,
    ) -> _DispatchPlan | None:
        # The handler may have created the doctor row inside its
        # transition (registration Case A). Reload if needed.
        if doctor is None:
            doctor = await DoctorRepository(session).get_by_phone(event.full_phone_number)
            if doctor is None:
                log.info("wabot.orchestrator.no_doctor_row_skipping_persistence")
                if result.outbound_intents:
                    log.info(
                        "wabot.orchestrator.outbound_intents_dropped_no_doctor",
                        count=len(result.outbound_intents),
                    )
                return None

        journey_repo = JourneyRepository(session)
        from_state = _journey_state_label(journey)
        to_state = _journey_state_label_from_result(result)

        await journey_repo.upsert(
            doctor_id=doctor.id,
            journey=result.next_journey,
            state_registration=result.next_registration_state,
            state_registered=result.next_registered_state,
            expected_input_kind=(
                result.expected_input_kind.value if result.expected_input_kind is not None else None
            ),
            expected_outbound_id=result.expected_outbound_id,
            retry_count=result.retry_count,
            context=dict(result.context_patch),
            last_processed_event_id=event.interakt_message_id,
        )
        if from_state != to_state:
            try:
                correlation_uuid = uuid.UUID(event.correlation_id)
            except (ValueError, AttributeError):
                correlation_uuid = None
            await journey_repo.append_history(
                doctor_id=doctor.id,
                from_state=from_state,
                to_state=to_state,
                event_id=event.interakt_message_id,
                correlation_id=correlation_uuid,
            )
        log.info(
            "wabot.orchestrator.journey_persisted",
            case=decision.case.value,
            from_state=from_state,
            to_state=to_state,
        )
        if not result.outbound_intents:
            return None
        return _DispatchPlan(
            doctor_id=doctor.id,
            state_when_sent=to_state,
            intents=result.outbound_intents,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _required_str(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        msg = f"Broker payload missing required field {key!r}"
        raise OrchestratorPoisonError(msg)
    return value


def _required_uuid(payload: Mapping[str, Any], key: str) -> uuid.UUID:
    raw = _required_str(payload, key)
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        msg = f"Broker payload field {key!r} is not a valid UUID: {raw!r}"
        raise OrchestratorPoisonError(msg) from exc


async def _load_onboarding(
    session: AsyncSession,
    doctor: Doctor | None,
) -> WhatsappOnboardingStatus | None:
    if doctor is None:
        return None
    stmt = select(WhatsappOnboardingStatus).where(WhatsappOnboardingStatus.doctor_id == doctor.id)
    return (await session.execute(stmt)).scalar_one_or_none()


def _journey_state_label(journey: JourneyState | None) -> str | None:
    if journey is None:
        return None
    if journey.state_registration is not None:
        return f"registration:{journey.state_registration.value}"
    if journey.state_registered is not None:
        return f"registered:{journey.state_registered.value}"
    return f"{journey.journey.value}:UNKNOWN"


def _journey_state_label_from_result(result: JourneyResult) -> str:
    if result.next_registration_state is not None:
        return f"registration:{result.next_registration_state.value}"
    if result.next_registered_state is not None:
        return f"registered:{result.next_registered_state.value}"
    return f"{result.next_journey.value}:UNKNOWN"
