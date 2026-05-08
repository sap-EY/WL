"""`wabot.doctor` — owned master + canonical user record."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from wabot.data.base import Base
from wabot.data.models._columns import (
    TimestampTZ,
    created_at_column,
    updated_at_column,
    uuid_pk_column,
)


class Doctor(Base):
    __tablename__ = "doctor"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    full_phone_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    first_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    speciality: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str | None] = mapped_column(Text, nullable=True)
    pincode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    is_profile_complete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    registration_completed_at: Mapped[datetime | None] = mapped_column(TimestampTZ, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'whatsapp'"))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Doctor id={self.id} phone={self.full_phone_number}>"
