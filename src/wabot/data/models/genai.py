"""`wabot.genai_interaction` — request/response audit for the GenAI gateway."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from wabot.data.base import Base
from wabot.data.models._columns import (
    JsonB,
    UuidPg,
    created_at_column,
    uuid_pk_column,
)


class GenAIInteraction(Base):
    __tablename__ = "genai_interaction"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UuidPg, ForeignKey("wabot.doctor.id"), nullable=False
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidPg, ForeignKey("wabot.conversation_session.id"), nullable=True
    )
    request: Mapped[dict[str, Any]] = mapped_column(JsonB, nullable=False)
    response: Mapped[dict[str, Any] | None] = mapped_column(JsonB, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UuidPg, nullable=True)
    created_at: Mapped[datetime] = created_at_column()
