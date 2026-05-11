"""WhatsApp onboarding status repository."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from wabot.data.models.onboarding import WhatsappOnboardingStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class OnboardingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, doctor_id: uuid.UUID) -> WhatsappOnboardingStatus | None:
        stmt = select(WhatsappOnboardingStatus).where(
            WhatsappOnboardingStatus.doctor_id == doctor_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def mark_onboarded(self, doctor_id: uuid.UUID) -> WhatsappOnboardingStatus:
        """Set ``is_onboarded=True`` on first consent-template send.

        Idempotent: if already onboarded the timestamp is preserved.
        """
        row = await self.get(doctor_id)
        now = datetime.now(tz=UTC)
        if row is None:
            row = WhatsappOnboardingStatus(
                doctor_id=doctor_id,
                is_onboarded=True,
                onboarded_at=now,
            )
            self._session.add(row)
        elif not row.is_onboarded:
            row.is_onboarded = True
            row.onboarded_at = now
        await self._session.flush()
        return row
