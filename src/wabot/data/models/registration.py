"""`wabot.registration_attempt` and `wabot.partial_profile_confirmation`."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from wabot.data.base import Base
from wabot.data.models._columns import (
    JsonB,
    TimestampTZ,
    UuidPg,
    created_at_column,
    uuid_pk_column,
)


class RegistrationAttempt(Base):
    __tablename__ = "registration_attempt"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UuidPg, ForeignKey("wabot.doctor.id"), nullable=False
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    parsed: Mapped[dict[str, Any] | None] = mapped_column(JsonB, nullable=True)
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    errors: Mapped[dict[str, Any] | None] = mapped_column(JsonB, nullable=True)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = created_at_column()


class PartialProfileConfirmation(Base):
    __tablename__ = "partial_profile_confirmation"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UuidPg, ForeignKey("wabot.doctor.id"), nullable=False
    )
    presented_data: Mapped[dict[str, Any]] = mapped_column(JsonB, nullable=False)
    confirmed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(TimestampTZ, nullable=True)
    created_at: Mapped[datetime] = created_at_column()
