"""Webhook raw-event repository — durable replay log + dedupe.

The unique index on (event_type, interakt_message_id, message_status) in
the DDL backs `record_if_new`: the insert is attempted with
`ON CONFLICT DO NOTHING`, and the row id is fetched afterwards to learn
whether we just stored a fresh event or a duplicate.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from wabot.data.models.webhook import WebhookEventRaw

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class WebhookRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_if_new(
        self,
        *,
        event_type: str,
        interakt_message_id: str | None,
        full_phone_number: str | None,
        payload: dict[str, Any],
    ) -> tuple[WebhookEventRaw, bool]:
        """Insert (or no-op if duplicate). Returns (row, is_new)."""
        stmt = (
            pg_insert(WebhookEventRaw)
            .values(
                event_type=event_type,
                interakt_message_id=interakt_message_id,
                full_phone_number=full_phone_number,
                payload=payload,
            )
            .on_conflict_do_nothing()
            .returning(WebhookEventRaw.id)
        )
        result = await self._session.execute(stmt)
        new_id = result.scalar_one_or_none()
        is_new = new_id is not None

        if is_new:
            row = await self._session.get(WebhookEventRaw, new_id)
            if row is None:  # pragma: no cover - just inserted
                msg = f"Webhook row vanished after insert: id={new_id!r}"
                raise RuntimeError(msg)
            return row, True

        # Duplicate; locate the canonical row (matches the unique index).
        message_status = (
            payload.get("data", {}).get("message", {}).get("message_status")
            if isinstance(payload, dict)
            else None
        )
        lookup = select(WebhookEventRaw).where(
            WebhookEventRaw.event_type == event_type,
            WebhookEventRaw.interakt_message_id == interakt_message_id,
        )
        rows = (await self._session.execute(lookup)).scalars().all()
        if message_status is not None:
            for r in rows:
                ms = r.payload.get("data", {}).get("message", {}).get("message_status")
                if ms == message_status:
                    return r, False
        if rows:
            return rows[0], False
        msg = "Webhook conflict reported but no row found"
        raise RuntimeError(msg)

    async def mark_processed(self, event_id: uuid.UUID, *, at: datetime) -> None:
        row = await self._session.get(WebhookEventRaw, event_id)
        if row is not None:
            row.processed_at = at
