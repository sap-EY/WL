"""`wabot.journey_state` and `wabot.journey_state_history`."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from wabot.data.base import Base
from wabot.data.models._columns import (
    JsonB,
    TimestampTZ,
    UuidPg,
    created_at_column,
    pg_enum,
    updated_at_column,
    uuid_pk_column,
)
from wabot.domain.enums import JourneyType, RegisteredState, RegistrationState


class JourneyState(Base):
    __tablename__ = "journey_state"
    __table_args__ = (
        CheckConstraint(
            "(journey='registration' AND state_registration IS NOT NULL"
            " AND state_registered IS NULL)"
            " OR (journey='registered' AND state_registered IS NOT NULL"
            " AND state_registration IS NULL)",
            name="journey_state_consistency",
        ),
    )

    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UuidPg, ForeignKey("wabot.doctor.id", ondelete="CASCADE"), primary_key=True
    )
    journey: Mapped[JourneyType] = mapped_column(
        pg_enum(JourneyType, "journey_type"), nullable=False
    )
    state_registration: Mapped[RegistrationState | None] = mapped_column(
        pg_enum(RegistrationState, "registration_state"), nullable=True
    )
    state_registered: Mapped[RegisteredState | None] = mapped_column(
        pg_enum(RegisteredState, "registered_state"), nullable=True
    )
    expected_input_kind: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_outbound_id: Mapped[uuid.UUID | None] = mapped_column(UuidPg, nullable=True)
    context: Mapped[dict[str, Any]] = mapped_column(
        JsonB, nullable=False, server_default=text("'{}'::jsonb")
    )
    last_event_received_at: Mapped[datetime | None] = mapped_column(TimestampTZ, nullable=True)
    last_processed_event_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = updated_at_column()


class JourneyStateHistory(Base):
    __tablename__ = "journey_state_history"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UuidPg, ForeignKey("wabot.doctor.id", ondelete="CASCADE"), nullable=False
    )
    from_state: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_state: Mapped[str] = mapped_column(Text, nullable=False)
    event_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UuidPg, nullable=True)
    occurred_at: Mapped[datetime] = created_at_column()
