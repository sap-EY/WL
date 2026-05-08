"""`wabot.conversation_session` and `wabot.conversation_message`."""

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
from wabot.domain.enums import MessageDirection


class ConversationSession(Base):
    __tablename__ = "conversation_session"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UuidPg, ForeignKey("wabot.doctor.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = created_at_column()
    last_activity_at: Mapped[datetime] = created_at_column()
    ended_at: Mapped[datetime | None] = mapped_column(TimestampTZ, nullable=True)


class ConversationMessage(Base):
    __tablename__ = "conversation_message"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    session_id: Mapped[uuid.UUID] = mapped_column(
        UuidPg, ForeignKey("wabot.conversation_session.id"), nullable=False
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UuidPg, ForeignKey("wabot.doctor.id"), nullable=False
    )
    direction: Mapped[MessageDirection] = mapped_column(
        pg_enum(MessageDirection, "message_direction"), nullable=False
    )
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JsonB, nullable=True)
    interakt_msg_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    callback_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UuidPg, nullable=True)
    created_at: Mapped[datetime] = created_at_column()
