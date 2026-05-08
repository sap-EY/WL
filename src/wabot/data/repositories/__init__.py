"""Repositories — thin async wrappers around SQLAlchemy queries.

Each repository takes an `AsyncSession` and exposes intent-revealing
methods used by services and journey handlers. They never commit or
roll back; that responsibility lives in `data.db.session_scope` or the
calling service.
"""

from __future__ import annotations

from wabot.data.repositories.doctor_repo import DoctorRepository
from wabot.data.repositories.journey_repo import JourneyRepository
from wabot.data.repositories.outbound_repo import OutboundRepository
from wabot.data.repositories.webhook_repo import WebhookRepository

__all__ = [
    "DoctorRepository",
    "JourneyRepository",
    "OutboundRepository",
    "WebhookRepository",
]
