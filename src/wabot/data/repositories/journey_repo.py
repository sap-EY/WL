"""Journey-state repository.

Reads/writes a single canonical row per doctor in `journey_state`, plus an
append-only entry in `journey_state_history` whenever the state changes.
Optimistic-locking is implemented via the `version` column.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from wabot.data.models.journey import JourneyState, JourneyStateHistory

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from wabot.domain.enums import JourneyType, RegisteredState, RegistrationState


class JourneyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, doctor_id: uuid.UUID) -> JourneyState | None:
        return await self._session.get(JourneyState, doctor_id)

    async def get_for_update(self, doctor_id: uuid.UUID) -> JourneyState | None:
        stmt = select(JourneyState).where(JourneyState.doctor_id == doctor_id).with_for_update()
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def upsert(
        self,
        *,
        doctor_id: uuid.UUID,
        journey: JourneyType,
        state_registration: RegistrationState | None = None,
        state_registered: RegisteredState | None = None,
        expected_input_kind: str | None = None,
        expected_outbound_id: uuid.UUID | None = None,
        context: dict[str, Any] | None = None,
        last_processed_event_id: str | None = None,
    ) -> JourneyState:
        row = await self.get(doctor_id)
        if row is None:
            row = JourneyState(
                doctor_id=doctor_id,
                journey=journey,
                state_registration=state_registration,
                state_registered=state_registered,
                expected_input_kind=expected_input_kind,
                expected_outbound_id=expected_outbound_id,
                context=context or {},
                last_processed_event_id=last_processed_event_id,
            )
            self._session.add(row)
        else:
            row.journey = journey
            row.state_registration = state_registration
            row.state_registered = state_registered
            row.expected_input_kind = expected_input_kind
            row.expected_outbound_id = expected_outbound_id
            row.context = context or {}
            row.last_processed_event_id = last_processed_event_id
            row.version = row.version + 1
        await self._session.flush()
        return row

    async def append_history(
        self,
        *,
        doctor_id: uuid.UUID,
        from_state: str | None,
        to_state: str,
        event_id: str | None = None,
        correlation_id: uuid.UUID | None = None,
    ) -> JourneyStateHistory:
        entry = JourneyStateHistory(
            doctor_id=doctor_id,
            from_state=from_state,
            to_state=to_state,
            event_id=event_id,
            correlation_id=correlation_id,
        )
        self._session.add(entry)
        await self._session.flush()
        return entry
