"""`wabot.webhook_event_raw` — replay log + dedupe substrate."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from wabot.data.base import Base
from wabot.data.models._columns import (
    JsonB,
    TimestampTZ,
    created_at_column,
    uuid_pk_column,
)


class WebhookEventRaw(Base):
    __tablename__ = "webhook_event_raw"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    interakt_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_phone_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonB, nullable=False)
    received_at: Mapped[datetime] = created_at_column()
    processed_at: Mapped[datetime | None] = mapped_column(TimestampTZ, nullable=True)
