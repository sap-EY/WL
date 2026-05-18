"""ORM models for the `wabot` schema.

Each module under this package defines one logical group of tables.
Importing the package is enough to register every mapper on
`Base.metadata`, which is what Alembic and the test suite rely on.

The Postgres ENUM types referenced here are created by the SQL
migration (and `models.txt`); the ORM is configured with
`create_type=False` so SQLAlchemy never tries to (re)issue them.
"""

from __future__ import annotations

from wabot.data.models.consent import Consent, ConsentHistory
from wabot.data.models.conversation import ConversationMessage, ConversationSession
from wabot.data.models.doctor import Doctor
from wabot.data.models.genai import GenAIInteraction
from wabot.data.models.journey import JourneyState, JourneyStateHistory
from wabot.data.models.onboarding import WhatsappOnboardingStatus
from wabot.data.models.outbound import OutboundMessage
from wabot.data.models.registration import RegistrationAttempt
from wabot.data.models.webhook import WebhookEventRaw

__all__ = [
    "Consent",
    "ConsentHistory",
    "ConversationMessage",
    "ConversationSession",
    "Doctor",
    "GenAIInteraction",
    "JourneyState",
    "JourneyStateHistory",
    "OutboundMessage",
    "RegistrationAttempt",
    "WebhookEventRaw",
    "WhatsappOnboardingStatus",
]
