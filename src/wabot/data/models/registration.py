"""`wabot.registration_attempt` malformed Flow payload log."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from wabot.data.base import Base
from wabot.data.models._columns import (
    JsonB,
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
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JsonB, nullable=False)
    parsed: Mapped[dict[str, Any] | None] = mapped_column(JsonB, nullable=True)
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    errors: Mapped[dict[str, Any] | None] = mapped_column(JsonB, nullable=True)
    created_at: Mapped[datetime] = created_at_column()
