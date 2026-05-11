"""Consent repository — current snapshot reads + transitions with history."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from wabot.data.models.consent import Consent, ConsentHistory
from wabot.domain.enums import ConsentStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class ConsentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, doctor_id: uuid.UUID) -> Consent | None:
        stmt = select(Consent).where(Consent.doctor_id == doctor_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def upsert_pending(
        self,
        *,
        doctor_id: uuid.UUID,
        last_template_msg_id: str | None = None,
    ) -> Consent:
        """Create the consent row with status=PENDING (or no-op if it exists)."""
        consent = await self.get(doctor_id)
        if consent is None:
            consent = Consent(
                doctor_id=doctor_id,
                status=ConsentStatus.PENDING,
                last_template_msg_id=last_template_msg_id,
            )
            self._session.add(consent)
            await self._session.flush()
        elif last_template_msg_id is not None:
            consent.last_template_msg_id = last_template_msg_id
            await self._session.flush()
        return consent

    async def set_status(
        self,
        *,
        doctor_id: uuid.UUID,
        status: ConsentStatus,
        correlation_id: uuid.UUID | None = None,
        reason: str | None = None,
    ) -> Consent:
        """Move consent into ``status``, stamping the appropriate timestamp."""
        now = datetime.now(tz=UTC)
        consent = await self.get(doctor_id)
        if consent is None:
            consent = Consent(doctor_id=doctor_id, status=status)
            self._session.add(consent)
        else:
            consent.status = status
        if status == ConsentStatus.ACCEPTED:
            consent.accepted_at = now
        elif status == ConsentStatus.DECLINED:
            consent.declined_at = now
        self._session.add(
            ConsentHistory(
                doctor_id=doctor_id,
                status=status,
                reason=reason,
                correlation_id=correlation_id,
            )
        )
        await self._session.flush()
        return consent
