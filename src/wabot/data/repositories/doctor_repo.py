"""Doctor repository — lookups + upserts by phone.

Phase 2 covers only the access patterns that downstream phases will
actually need (find by phone, create new shell, update profile fields).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from wabot.data.models.doctor import Doctor

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class DoctorRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_phone(self, full_phone_number: str) -> Doctor | None:
        stmt = select(Doctor).where(Doctor.full_phone_number == full_phone_number)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_id(self, doctor_id: uuid.UUID) -> Doctor | None:
        return await self._session.get(Doctor, doctor_id)

    async def create_shell(self, full_phone_number: str) -> Doctor:
        """Insert a brand-new doctor with phone only; profile fills in later."""
        doctor = Doctor(full_phone_number=full_phone_number, is_profile_complete=False)
        self._session.add(doctor)
        await self._session.flush()
        return doctor

    async def upsert_profile(
        self,
        *,
        full_phone_number: str,
        first_name: str | None,
        last_name: str | None,
        speciality: str | None,
        email: str | None,
        address: str | None,
        city: str | None,
        state: str | None,
        pincode: str | None,
        is_profile_complete: bool,
        mci_id: str | None = None,
    ) -> Doctor:
        doctor = await self.get_by_phone(full_phone_number)
        if doctor is None:
            doctor = Doctor(full_phone_number=full_phone_number)
            self._session.add(doctor)
        doctor.first_name = first_name
        doctor.last_name = last_name
        doctor.speciality = speciality
        doctor.email = email
        doctor.address = address
        doctor.city = city
        doctor.state = state
        doctor.pincode = pincode
        doctor.mci_id = mci_id
        doctor.is_profile_complete = is_profile_complete
        if is_profile_complete and doctor.registration_completed_at is None:
            doctor.registration_completed_at = datetime.now(tz=UTC)
        await self._session.flush()
        return doctor

    async def patch(self, doctor_id: uuid.UUID, **fields: Any) -> Doctor | None:
        doctor = await self.get_by_id(doctor_id)
        if doctor is None:
            return None
        for key, value in fields.items():
            if not hasattr(doctor, key):
                msg = f"Unknown Doctor attribute: {key}"
                raise AttributeError(msg)
            setattr(doctor, key, value)
        await self._session.flush()
        return doctor
