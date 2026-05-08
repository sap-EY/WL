"""Smoke tests for the Phase 2 ORM layer.

These do not connect to a database. They verify that:
- every model is registered on `Base.metadata` and bound to the
  `wabot` schema;
- enum columns reference the expected Postgres ENUM names;
- key columns / unique constraints / foreign keys are present.
"""

from __future__ import annotations

import sqlalchemy as sa

from wabot.data.base import WABOT_SCHEMA, Base
from wabot.data.models import (
    Consent,
    ConsentHistory,
    ConversationMessage,
    ConversationSession,
    Doctor,
    GenAIInteraction,
    JourneyState,
    JourneyStateHistory,
    OutboundMessage,
    PartialProfileConfirmation,
    RegistrationAttempt,
    WebhookEventRaw,
    WhatsappOnboardingStatus,
)

EXPECTED_TABLES = {
    "doctor",
    "consent",
    "consent_history",
    "whatsapp_onboarding_status",
    "journey_state",
    "journey_state_history",
    "conversation_session",
    "conversation_message",
    "outbound_message",
    "webhook_event_raw",
    "genai_interaction",
    "registration_attempt",
    "partial_profile_confirmation",
}


def test_all_tables_registered_in_wabot_schema() -> None:
    tables = Base.metadata.tables
    found = {name.split(".", 1)[1] for name in tables if name.startswith(f"{WABOT_SCHEMA}.")}
    assert EXPECTED_TABLES.issubset(found), EXPECTED_TABLES - found


def test_doctor_phone_unique_and_pk() -> None:
    table = Doctor.__table__
    assert table.schema == WABOT_SCHEMA
    pk = list(table.primary_key.columns)
    assert len(pk) == 1 and pk[0].name == "id"
    phone = table.c.full_phone_number
    assert phone.unique is True
    assert phone.nullable is False


def test_journey_state_check_constraint_present() -> None:
    constraints = {c.name for c in JourneyState.__table__.constraints}
    assert any("journey_state_consistency" in (n or "") for n in constraints)


def test_postgres_enum_column_names() -> None:
    enum_assertions = {
        Consent.__table__.c.status: "consent_status",
        ConsentHistory.__table__.c.status: "consent_status",
        JourneyState.__table__.c.journey: "journey_type",
        JourneyState.__table__.c.state_registration: "registration_state",
        JourneyState.__table__.c.state_registered: "registered_state",
        ConversationMessage.__table__.c.direction: "message_direction",
        OutboundMessage.__table__.c.kind: "outbound_kind",
        OutboundMessage.__table__.c.status: "outbound_status",
    }
    for column, expected_name in enum_assertions.items():
        col_type = column.type
        assert isinstance(col_type, sa.Enum), f"{column} is not Enum"
        assert col_type.name == expected_name
        assert col_type.schema == WABOT_SCHEMA


def test_outbound_idempotency_key_unique() -> None:
    col = OutboundMessage.__table__.c.idempotency_key
    assert col.unique is True
    assert col.nullable is False


def test_foreign_keys_target_doctor() -> None:
    fk_targets: dict[type, str] = {
        Consent: "wabot.doctor.id",
        ConsentHistory: "wabot.doctor.id",
        WhatsappOnboardingStatus: "wabot.doctor.id",
        JourneyState: "wabot.doctor.id",
        JourneyStateHistory: "wabot.doctor.id",
        ConversationSession: "wabot.doctor.id",
        ConversationMessage: "wabot.doctor.id",
        OutboundMessage: "wabot.doctor.id",
        GenAIInteraction: "wabot.doctor.id",
        RegistrationAttempt: "wabot.doctor.id",
        PartialProfileConfirmation: "wabot.doctor.id",
    }
    for model, target in fk_targets.items():
        fk_columns = [c for c in model.__table__.columns if c.foreign_keys]
        assert fk_columns, f"{model.__name__} has no foreign keys"
        assert any(
            any(fk.target_fullname == target for fk in c.foreign_keys) for c in fk_columns
        ), f"{model.__name__} missing FK to {target}"


def test_webhook_raw_columns() -> None:
    table = WebhookEventRaw.__table__
    assert table.c.event_type.nullable is False
    assert table.c.payload.nullable is False
    assert table.c.received_at.nullable is False
