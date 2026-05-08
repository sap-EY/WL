"""Domain enums shared by the ORM, services, and API schemas.

These mirror the Postgres ENUM types declared in `models.txt` (§1) and the
state machines documented in `implementation_plan.md` §7.3. Values are
quoted exactly as they appear in DDL — do **not** rename without a
matching DB migration.
"""

from __future__ import annotations

from enum import StrEnum


class JourneyType(StrEnum):
    REGISTRATION = "registration"
    REGISTERED = "registered"


class RegistrationState(StrEnum):
    REG_INITIATED = "REG_INITIATED"
    AWAITING_FULL_DETAILS = "AWAITING_FULL_DETAILS"
    PARTIAL_CONFIRM_PENDING = "PARTIAL_CONFIRM_PENDING"
    AWAITING_REMAINING_DETAILS = "AWAITING_REMAINING_DETAILS"
    AWAITING_CORRECTED_FULL = "AWAITING_CORRECTED_FULL"
    REGISTRATION_COMPLETED = "REGISTRATION_COMPLETED"
    ASSISTED_SUPPORT = "ASSISTED_SUPPORT"


class RegisteredState(StrEnum):
    CONSENT_PENDING = "CONSENT_PENDING"
    CONSENT_DECLINED = "CONSENT_DECLINED"
    CONSENT_ACCEPTED = "CONSENT_ACCEPTED"
    AWAITING_FREE_TEXT = "AWAITING_FREE_TEXT"
    GENAI_PROCESSING = "GENAI_PROCESSING"
    AWAITING_ANSWER_BUTTON = "AWAITING_ANSWER_BUTTON"
    HOTLINE_TEMPLATE_SENT = "HOTLINE_TEMPLATE_SENT"


class ConsentStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class MessageDirection(StrEnum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class OutboundStatus(StrEnum):
    PENDING_SEND = "PENDING_SEND"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    READ = "READ"
    FAILED = "FAILED"
    CLICKED = "CLICKED"


class OutboundKind(StrEnum):
    TEXT = "TEXT"
    BUTTONS = "BUTTONS"
    TEMPLATE = "TEMPLATE"


class ExpectedInputKind(StrEnum):
    """Free-form discriminator stored as TEXT in `journey_state.expected_input_kind`.

    Not a Postgres ENUM (the DDL stores it as TEXT) so we can extend it
    without a migration. Treat any unknown string as `UNKNOWN`.
    """

    BUTTON = "BUTTON"
    FREE_TEXT = "FREE_TEXT"
    REGISTRATION_TEXT = "REGISTRATION_TEXT"
