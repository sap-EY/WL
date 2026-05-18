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

    async def get_by_id(self, outbound_id: uuid.UUID) -> OutboundMessage | None:
        return await self._session.get(OutboundMessage, outbound_id)

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
        self.apply_status(
            row,
            status=status,
            at=at,
            failure_reason=failure_reason,
            clicked_button_text=clicked_button_text,
        )
        return row

    def apply_status(
        self,
        row: OutboundMessage,
        *,
        status: OutboundStatus,
        at: datetime,
        failure_reason: str | None = None,
        clicked_button_text: str | None = None,
    ) -> None:
        """Apply a provider status without regressing the lifecycle.

        Interakt may deliver status webhooks out of order. Timestamp
        columns are filled idempotently, while the aggregate `status`
        only moves forward according to `_STATUS_RANK`.
        """
        current_rank = _STATUS_RANK[row.status]
        next_rank = _STATUS_RANK[status]
        if next_rank >= current_rank:
            row.status = status
        if status is OutboundStatus.SENT:
            row.sent_at = row.sent_at or at
        elif status is OutboundStatus.DELIVERED:
            row.delivered_at = row.delivered_at or at
        elif status is OutboundStatus.READ:
            row.read_at = row.read_at or at
        elif status is OutboundStatus.FAILED:
            row.failed_at = row.failed_at or at
            row.failure_reason = failure_reason or row.failure_reason
        elif status is OutboundStatus.CLICKED:
            row.clicked_at = row.clicked_at or at
            row.clicked_button_text = clicked_button_text or row.clicked_button_text


_STATUS_RANK: dict[OutboundStatus, int] = {
    OutboundStatus.PENDING_SEND: 0,
    OutboundStatus.SENT: 1,
    OutboundStatus.DELIVERED: 2,
    OutboundStatus.READ: 3,
    OutboundStatus.CLICKED: 4,
    OutboundStatus.FAILED: 5,
}
