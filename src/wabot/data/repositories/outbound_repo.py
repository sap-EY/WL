"""Outbound message repository.

Handles `outbound_message` inserts (idempotent on `idempotency_key`) and
status transitions driven by Interakt status webhooks.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from wabot.data.models.outbound import OutboundMessage
from wabot.domain.enums import OutboundKind, OutboundStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class OutboundRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_idempotency_key(self, key: str) -> OutboundMessage | None:
        stmt = select(OutboundMessage).where(OutboundMessage.idempotency_key == key)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_interakt_id(self, interakt_message_id: str) -> OutboundMessage | None:
        stmt = select(OutboundMessage).where(
            OutboundMessage.interakt_message_id == interakt_message_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create_pending(
        self,
        *,
        doctor_id: uuid.UUID,
        kind: OutboundKind,
        template_name: str | None,
        payload: dict[str, Any],
        idempotency_key: str,
        callback_data: str,
        state_when_sent: str | None,
        correlation_id: uuid.UUID | None,
    ) -> OutboundMessage:
        """Insert a new outbound row in `PENDING_SEND`, idempotent on `idempotency_key`.

        Returns the existing row when the key collides (replay-safe).
        """
        existing = await self.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            return existing

        stmt = (
            pg_insert(OutboundMessage)
            .values(
                doctor_id=doctor_id,
                kind=kind.value,
                template_name=template_name,
                payload=payload,
                idempotency_key=idempotency_key,
                callback_data=callback_data,
                state_when_sent=state_when_sent,
                correlation_id=correlation_id,
                status=OutboundStatus.PENDING_SEND.value,
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(OutboundMessage.id)
        )
        await self._session.execute(stmt)
        # Re-read by key to pick up the canonical row (covers conflict paths too).
        row = await self.get_by_idempotency_key(idempotency_key)
        if row is None:  # pragma: no cover - immediately re-read after upsert
            msg = f"Outbound message vanished after upsert: idempotency_key={idempotency_key!r}"
            raise RuntimeError(msg)
        return row

    async def mark_sent(
        self, outbound_id: uuid.UUID, *, interakt_message_id: str, sent_at: datetime
    ) -> None:
        row = await self._session.get(OutboundMessage, outbound_id)
        if row is None:
            return
        row.interakt_message_id = interakt_message_id
        row.status = OutboundStatus.SENT
        row.sent_at = sent_at

    async def mark_status(
        self,
        *,
        interakt_message_id: str,
        status: OutboundStatus,
        at: datetime,
        failure_reason: str | None = None,
        clicked_button_text: str | None = None,
    ) -> OutboundMessage | None:
        row = await self.get_by_interakt_id(interakt_message_id)
        if row is None:
            return None
        row.status = status
        if status is OutboundStatus.DELIVERED:
            row.delivered_at = at
        elif status is OutboundStatus.READ:
            row.read_at = at
        elif status is OutboundStatus.FAILED:
            row.failed_at = at
            row.failure_reason = failure_reason
        elif status is OutboundStatus.CLICKED:
            row.clicked_at = at
            row.clicked_button_text = clicked_button_text
        return row
