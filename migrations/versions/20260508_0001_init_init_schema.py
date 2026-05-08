"""Initial schema — wabot v2.

Mirrors `models.txt` exactly. The DDL is idempotent (uses
`IF NOT EXISTS` and `DO $$ ... $$` blocks for ENUM creation), so
`alembic upgrade head` is safe whether run against a brand-new
database or the already-initialised Azure Postgres instance.

Revision ID: 0001_init
Revises:
Create Date: 2026-05-08
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_init"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SCHEMA_DDL = """
-- 0. Schema + extensions ------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS wabot;
SET search_path TO wabot;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 1. Enums --------------------------------------------------------------------
DO $$ BEGIN
    CREATE TYPE wabot.journey_type AS ENUM ('registration', 'registered');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE wabot.registration_state AS ENUM (
        'REG_INITIATED','AWAITING_FULL_DETAILS','PARTIAL_CONFIRM_PENDING',
        'AWAITING_REMAINING_DETAILS','AWAITING_CORRECTED_FULL',
        'REGISTRATION_COMPLETED','ASSISTED_SUPPORT'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE wabot.registered_state AS ENUM (
        'CONSENT_PENDING','CONSENT_DECLINED','CONSENT_ACCEPTED',
        'AWAITING_FREE_TEXT','GENAI_PROCESSING','AWAITING_ANSWER_BUTTON',
        'HOTLINE_TEMPLATE_SENT'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE wabot.consent_status AS ENUM ('PENDING','ACCEPTED','DECLINED');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE wabot.message_direction AS ENUM ('INBOUND','OUTBOUND');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE wabot.outbound_status AS ENUM (
        'PENDING_SEND','SENT','DELIVERED','READ','FAILED','CLICKED'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE wabot.outbound_kind AS ENUM ('TEXT','BUTTONS','TEMPLATE');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 2. Helper trigger -----------------------------------------------------------
CREATE OR REPLACE FUNCTION wabot.set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := clock_timestamp();
    RETURN NEW;
END $$;

-- 3. Doctor -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS wabot.doctor (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_phone_number           VARCHAR(20) NOT NULL UNIQUE,
    first_name                  TEXT,
    last_name                   TEXT,
    speciality                  TEXT,
    email                       TEXT,
    address                     TEXT,
    city                        TEXT,
    state                       TEXT,
    pincode                     VARCHAR(10),
    is_profile_complete         BOOLEAN NOT NULL DEFAULT FALSE,
    registration_completed_at   TIMESTAMPTZ(6),
    source                      TEXT NOT NULL DEFAULT 'whatsapp',
    created_at                  TIMESTAMPTZ(6) NOT NULL DEFAULT clock_timestamp(),
    updated_at                  TIMESTAMPTZ(6) NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS idx_doctor_phone      ON wabot.doctor(full_phone_number);
CREATE INDEX IF NOT EXISTS idx_doctor_complete   ON wabot.doctor(is_profile_complete);
CREATE INDEX IF NOT EXISTS idx_doctor_speciality ON wabot.doctor(speciality);

DROP TRIGGER IF EXISTS trg_doctor_updated_at ON wabot.doctor;
CREATE TRIGGER trg_doctor_updated_at
    BEFORE UPDATE ON wabot.doctor
    FOR EACH ROW EXECUTE FUNCTION wabot.set_updated_at();

-- 4. Consent + history --------------------------------------------------------
CREATE TABLE IF NOT EXISTS wabot.consent (
    doctor_id            UUID PRIMARY KEY REFERENCES wabot.doctor(id) ON DELETE CASCADE,
    status               wabot.consent_status NOT NULL DEFAULT 'PENDING',
    accepted_at          TIMESTAMPTZ(6),
    declined_at          TIMESTAMPTZ(6),
    last_template_msg_id TEXT,
    updated_at           TIMESTAMPTZ(6) NOT NULL DEFAULT clock_timestamp()
);

DROP TRIGGER IF EXISTS trg_consent_updated_at ON wabot.consent;
CREATE TRIGGER trg_consent_updated_at
    BEFORE UPDATE ON wabot.consent
    FOR EACH ROW EXECUTE FUNCTION wabot.set_updated_at();

CREATE TABLE IF NOT EXISTS wabot.consent_history (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doctor_id      UUID NOT NULL REFERENCES wabot.doctor(id) ON DELETE CASCADE,
    status         wabot.consent_status NOT NULL,
    occurred_at    TIMESTAMPTZ(6) NOT NULL DEFAULT clock_timestamp(),
    reason         TEXT,
    correlation_id UUID
);
CREATE INDEX IF NOT EXISTS idx_consent_history_doctor
    ON wabot.consent_history(doctor_id, occurred_at DESC);

-- 5. Onboarding flag ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS wabot.whatsapp_onboarding_status (
    doctor_id     UUID PRIMARY KEY REFERENCES wabot.doctor(id) ON DELETE CASCADE,
    is_onboarded  BOOLEAN NOT NULL DEFAULT FALSE,
    onboarded_at  TIMESTAMPTZ(6)
);

-- 6. Journey state + history --------------------------------------------------
CREATE TABLE IF NOT EXISTS wabot.journey_state (
    doctor_id               UUID PRIMARY KEY REFERENCES wabot.doctor(id) ON DELETE CASCADE,
    journey                 wabot.journey_type NOT NULL,
    state_registration      wabot.registration_state,
    state_registered        wabot.registered_state,
    expected_input_kind     TEXT,
    expected_outbound_id    UUID,
    retry_count             INT NOT NULL DEFAULT 0,
    context                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_event_received_at  TIMESTAMPTZ(6),
    last_processed_event_id TEXT,
    version                 INT NOT NULL DEFAULT 0,
    updated_at              TIMESTAMPTZ(6) NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT chk_journey_state_consistency CHECK (
       (journey='registration' AND state_registration IS NOT NULL AND state_registered IS NULL)
    OR (journey='registered'   AND state_registered   IS NOT NULL AND state_registration IS NULL)
    )
);
CREATE INDEX IF NOT EXISTS idx_journey_state_journey ON wabot.journey_state(journey);

DROP TRIGGER IF EXISTS trg_journey_state_updated_at ON wabot.journey_state;
CREATE TRIGGER trg_journey_state_updated_at
    BEFORE UPDATE ON wabot.journey_state
    FOR EACH ROW EXECUTE FUNCTION wabot.set_updated_at();

CREATE TABLE IF NOT EXISTS wabot.journey_state_history (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doctor_id       UUID NOT NULL REFERENCES wabot.doctor(id) ON DELETE CASCADE,
    from_state      TEXT,
    to_state        TEXT NOT NULL,
    event_id        TEXT,
    correlation_id  UUID,
    occurred_at     TIMESTAMPTZ(6) NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS idx_jsh_doctor_time
    ON wabot.journey_state_history(doctor_id, occurred_at DESC);

-- 7. Conversation session + messages -----------------------------------------
CREATE TABLE IF NOT EXISTS wabot.conversation_session (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doctor_id        UUID NOT NULL REFERENCES wabot.doctor(id) ON DELETE CASCADE,
    started_at       TIMESTAMPTZ(6) NOT NULL DEFAULT clock_timestamp(),
    last_activity_at TIMESTAMPTZ(6) NOT NULL DEFAULT clock_timestamp(),
    ended_at         TIMESTAMPTZ(6)
);
CREATE INDEX IF NOT EXISTS idx_conv_doctor_active
    ON wabot.conversation_session(doctor_id) WHERE ended_at IS NULL;

CREATE TABLE IF NOT EXISTS wabot.conversation_message (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES wabot.conversation_session(id),
    doctor_id       UUID NOT NULL REFERENCES wabot.doctor(id),
    direction       wabot.message_direction NOT NULL,
    text            TEXT,
    payload         JSONB,
    interakt_msg_id TEXT,
    callback_data   TEXT,
    correlation_id  UUID,
    created_at      TIMESTAMPTZ(6) NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS idx_conv_msg_session_time
    ON wabot.conversation_message(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_conv_msg_interakt
    ON wabot.conversation_message(interakt_msg_id);

-- 8. Outbound message log -----------------------------------------------------
CREATE TABLE IF NOT EXISTS wabot.outbound_message (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doctor_id           UUID NOT NULL REFERENCES wabot.doctor(id),
    kind                wabot.outbound_kind NOT NULL,
    template_name       TEXT,
    payload             JSONB NOT NULL,
    idempotency_key     TEXT NOT NULL UNIQUE,
    callback_data       TEXT NOT NULL,
    interakt_message_id TEXT,
    state_when_sent     TEXT,
    status              wabot.outbound_status NOT NULL DEFAULT 'PENDING_SEND',
    sent_at             TIMESTAMPTZ(6),
    delivered_at        TIMESTAMPTZ(6),
    read_at             TIMESTAMPTZ(6),
    failed_at           TIMESTAMPTZ(6),
    failure_reason      TEXT,
    clicked_at          TIMESTAMPTZ(6),
    clicked_button_text TEXT,
    correlation_id      UUID,
    created_at          TIMESTAMPTZ(6) NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS idx_outbound_doctor_time
    ON wabot.outbound_message(doctor_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_outbound_status
    ON wabot.outbound_message(status) WHERE status IN ('PENDING_SEND','FAILED');
CREATE INDEX IF NOT EXISTS idx_outbound_interakt
    ON wabot.outbound_message(interakt_message_id);

-- 9. Webhook raw event log ----------------------------------------------------
CREATE TABLE IF NOT EXISTS wabot.webhook_event_raw (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type           TEXT NOT NULL,
    interakt_message_id  TEXT,
    full_phone_number    VARCHAR(20),
    payload              JSONB NOT NULL,
    received_at          TIMESTAMPTZ(6) NOT NULL DEFAULT clock_timestamp(),
    processed_at         TIMESTAMPTZ(6)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_webhook_event_dedupe
    ON wabot.webhook_event_raw (
        event_type, interakt_message_id,
        (payload->'data'->'message'->>'message_status')
    );
CREATE INDEX IF NOT EXISTS idx_webhook_raw_phone
    ON wabot.webhook_event_raw(full_phone_number, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_webhook_unprocessed
    ON wabot.webhook_event_raw(received_at) WHERE processed_at IS NULL;

-- 10. GenAI interaction log ---------------------------------------------------
CREATE TABLE IF NOT EXISTS wabot.genai_interaction (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doctor_id       UUID NOT NULL REFERENCES wabot.doctor(id),
    session_id      UUID REFERENCES wabot.conversation_session(id),
    request         JSONB NOT NULL,
    response        JSONB,
    status          TEXT NOT NULL,
    latency_ms      INT,
    correlation_id  UUID,
    created_at      TIMESTAMPTZ(6) NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS idx_genai_doctor_time
    ON wabot.genai_interaction(doctor_id, created_at DESC);

-- 11. Registration parsing log ------------------------------------------------
CREATE TABLE IF NOT EXISTS wabot.registration_attempt (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doctor_id       UUID NOT NULL REFERENCES wabot.doctor(id),
    raw_text        TEXT NOT NULL,
    parsed          JSONB,
    is_valid        BOOLEAN NOT NULL,
    errors          JSONB,
    attempt_no      INT NOT NULL,
    created_at      TIMESTAMPTZ(6) NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS idx_reg_attempt_doctor
    ON wabot.registration_attempt(doctor_id, created_at DESC);

CREATE TABLE IF NOT EXISTS wabot.partial_profile_confirmation (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doctor_id       UUID NOT NULL REFERENCES wabot.doctor(id),
    presented_data  JSONB NOT NULL,
    confirmed       BOOLEAN,
    responded_at    TIMESTAMPTZ(6),
    created_at      TIMESTAMPTZ(6) NOT NULL DEFAULT clock_timestamp()
);
"""


_DOWNGRADE_DDL = """
DROP TABLE IF EXISTS wabot.partial_profile_confirmation CASCADE;
DROP TABLE IF EXISTS wabot.registration_attempt CASCADE;
DROP TABLE IF EXISTS wabot.genai_interaction CASCADE;
DROP TABLE IF EXISTS wabot.webhook_event_raw CASCADE;
DROP TABLE IF EXISTS wabot.outbound_message CASCADE;
DROP TABLE IF EXISTS wabot.conversation_message CASCADE;
DROP TABLE IF EXISTS wabot.conversation_session CASCADE;
DROP TABLE IF EXISTS wabot.journey_state_history CASCADE;
DROP TABLE IF EXISTS wabot.journey_state CASCADE;
DROP TABLE IF EXISTS wabot.whatsapp_onboarding_status CASCADE;
DROP TABLE IF EXISTS wabot.consent_history CASCADE;
DROP TABLE IF EXISTS wabot.consent CASCADE;
DROP TABLE IF EXISTS wabot.doctor CASCADE;
DROP FUNCTION IF EXISTS wabot.set_updated_at();
DROP TYPE IF EXISTS wabot.outbound_kind;
DROP TYPE IF EXISTS wabot.outbound_status;
DROP TYPE IF EXISTS wabot.message_direction;
DROP TYPE IF EXISTS wabot.consent_status;
DROP TYPE IF EXISTS wabot.registered_state;
DROP TYPE IF EXISTS wabot.registration_state;
DROP TYPE IF EXISTS wabot.journey_type;
"""


def upgrade() -> None:
    op.execute(_SCHEMA_DDL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_DDL)
