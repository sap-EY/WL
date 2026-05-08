"""`wabot.outbound_message` — idempotent, chain-aware outbound log."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from wabot.data.base import Base
from wabot.data.models._columns import (
    JsonB,
    TimestampTZ,
    UuidPg,
    created_at_column,
    pg_enum,
    uuid_pk_column,
)
from wabot.domain.enums import OutboundKind, OutboundStatus


class OutboundMessage(Base):
    __tablename__ = "outbound_message"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UuidPg, ForeignKey("wabot.doctor.id"), nullable=False
    )
    kind: Mapped[OutboundKind] = mapped_column(
        pg_enum(OutboundKind, "outbound_kind"), nullable=False
    )
    template_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonB, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    callback_data: Mapped[str] = mapped_column(Text, nullable=False)
    interakt_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    state_when_sent: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[OutboundStatus] = mapped_column(
        pg_enum(OutboundStatus, "outbound_status"),
        nullable=False,
        server_default=OutboundStatus.PENDING_SEND.value,
    )
    sent_at: Mapped[datetime | None] = mapped_column(TimestampTZ, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(TimestampTZ, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(TimestampTZ, nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(TimestampTZ, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    clicked_at: Mapped[datetime | None] = mapped_column(TimestampTZ, nullable=True)
    clicked_button_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UuidPg, nullable=True)
    created_at: Mapped[datetime] = created_at_column()
