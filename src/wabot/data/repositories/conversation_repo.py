"""Conversation session + message log repository.

Persists every inbound and outbound WhatsApp message into
`wabot.conversation_session` / `wabot.conversation_message`.

Concurrency: callers are expected to hold the per-user Redis lock
(``UserLock``) so concurrent active-session creation for the same
doctor is impossible in practice. The schema does not enforce
single-active-session uniqueness; we rely on the orchestrator's
serial dispatch instead.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from wabot.data.models.conversation import (
    ConversationMessage,
    ConversationSession,
)
from wabot.domain.enums import MessageDirection

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create_active_session(self, doctor_id: uuid.UUID) -> ConversationSession:
        stmt = (
            select(ConversationSession)
            .where(
                ConversationSession.doctor_id == doctor_id,
                ConversationSession.ended_at.is_(None),
            )
            .order_by(ConversationSession.started_at.desc())
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is not None:
            return row
        row = ConversationSession(id=uuid.uuid4(), doctor_id=doctor_id)
        self._session.add(row)
        # Flush so the FK target exists before any message rows that
        # reference this session.id are inserted in the same transaction.
        await self._session.flush()
        return row

    async def touch(self, session_id: uuid.UUID) -> None:
        row = await self._session.get(ConversationSession, session_id)
        if row is not None:
            row.last_activity_at = datetime.now(UTC)

    async def log_inbound(
        self,
        *,
        session_id: uuid.UUID,
        doctor_id: uuid.UUID,
        text: str | None,
        payload: dict[str, Any] | None,
        interakt_msg_id: str | None,
        correlation_id: uuid.UUID | None,
    ) -> ConversationMessage:
        row = ConversationMessage(
            id=uuid.uuid4(),
            session_id=session_id,
            doctor_id=doctor_id,
            direction=MessageDirection.INBOUND,
            text=text,
            payload=payload,
            interakt_msg_id=interakt_msg_id,
            callback_data=None,
            correlation_id=correlation_id,
        )
        self._session.add(row)
        return row

    async def log_outbound(
        self,
        *,
        session_id: uuid.UUID,
        doctor_id: uuid.UUID,
        text: str | None,
        payload: dict[str, Any] | None,
        interakt_msg_id: str | None,
        callback_data: str | None,
        correlation_id: uuid.UUID | None,
    ) -> ConversationMessage:
        row = ConversationMessage(
            id=uuid.uuid4(),
            session_id=session_id,
            doctor_id=doctor_id,
            direction=MessageDirection.OUTBOUND,
            text=text,
            payload=payload,
            interakt_msg_id=interakt_msg_id,
            callback_data=callback_data,
            correlation_id=correlation_id,
        )
        self._session.add(row)
        return row


__all__ = ["ConversationRepository"]
