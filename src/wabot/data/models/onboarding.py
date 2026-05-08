"""`wabot.whatsapp_onboarding_status`."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column

from wabot.data.base import Base
from wabot.data.models._columns import TimestampTZ, UuidPg


class WhatsappOnboardingStatus(Base):
    __tablename__ = "whatsapp_onboarding_status"

    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UuidPg, ForeignKey("wabot.doctor.id", ondelete="CASCADE"), primary_key=True
    )
    is_onboarded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    onboarded_at: Mapped[datetime | None] = mapped_column(TimestampTZ, nullable=True)
