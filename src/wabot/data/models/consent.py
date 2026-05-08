"""`wabot.consent` (current snapshot) and `wabot.consent_history`."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from wabot.data.base import Base
from wabot.data.models._columns import (
    TimestampTZ,
    UuidPg,
    created_at_column,
    pg_enum,
    updated_at_column,
    uuid_pk_column,
)
from wabot.domain.enums import ConsentStatus


class Consent(Base):
    __tablename__ = "consent"

    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UuidPg, ForeignKey("wabot.doctor.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[ConsentStatus] = mapped_column(
        pg_enum(ConsentStatus, "consent_status"),
        nullable=False,
        server_default=ConsentStatus.PENDING.value,
    )
    accepted_at: Mapped[datetime | None] = mapped_column(TimestampTZ, nullable=True)
    declined_at: Mapped[datetime | None] = mapped_column(TimestampTZ, nullable=True)
    last_template_msg_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = updated_at_column()


class ConsentHistory(Base):
    __tablename__ = "consent_history"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UuidPg, ForeignKey("wabot.doctor.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[ConsentStatus] = mapped_column(
        pg_enum(ConsentStatus, "consent_status"), nullable=False
    )
    occurred_at: Mapped[datetime] = created_at_column()
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UuidPg, nullable=True)
