"""Remove obsolete partial-registration schema.

Revision ID: 0003_remove_partial_registration
Revises: 0002_mci_id
Create Date: 2026-05-18
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0003_remove_partial_registration"
down_revision: str | None = "0002_mci_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE_SQL = """
UPDATE wabot.journey_state
SET state_registration = 'AWAITING_FULL_DETAILS',
    expected_input_kind = COALESCE(expected_input_kind, 'REGISTRATION_TEXT')
WHERE state_registration::text IN (
    'PARTIAL_CONFIRM_PENDING',
    'AWAITING_REMAINING_DETAILS',
    'AWAITING_CORRECTED_FULL'
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_enum e
        JOIN pg_type t ON t.oid = e.enumtypid
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE n.nspname = 'wabot'
          AND t.typname = 'registration_state'
          AND e.enumlabel IN (
              'PARTIAL_CONFIRM_PENDING',
              'AWAITING_REMAINING_DETAILS',
              'AWAITING_CORRECTED_FULL'
          )
    ) THEN
        ALTER TABLE wabot.journey_state
            ALTER COLUMN state_registration TYPE TEXT
            USING state_registration::text;

        DROP TYPE wabot.registration_state;

        CREATE TYPE wabot.registration_state AS ENUM (
            'REG_INITIATED',
            'AWAITING_FULL_DETAILS',
            'REGISTRATION_COMPLETED',
            'ASSISTED_SUPPORT'
        );

        ALTER TABLE wabot.journey_state
            ALTER COLUMN state_registration TYPE wabot.registration_state
            USING state_registration::wabot.registration_state;
    END IF;
END $$;

ALTER TABLE wabot.journey_state DROP COLUMN IF EXISTS retry_count;

DROP TABLE IF EXISTS wabot.partial_profile_confirmation CASCADE;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'wabot'
          AND table_name = 'registration_attempt'
          AND column_name = 'raw_text'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'wabot'
          AND table_name = 'registration_attempt'
          AND column_name = 'raw_payload'
    ) THEN
        ALTER TABLE wabot.registration_attempt ADD COLUMN raw_payload JSONB;
        UPDATE wabot.registration_attempt
        SET raw_payload = jsonb_build_object('raw_text', raw_text)
        WHERE raw_payload IS NULL;
        ALTER TABLE wabot.registration_attempt ALTER COLUMN raw_payload SET NOT NULL;
        ALTER TABLE wabot.registration_attempt DROP COLUMN raw_text;
    ELSIF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'wabot'
          AND table_name = 'registration_attempt'
          AND column_name = 'raw_payload'
    ) THEN
        ALTER TABLE wabot.registration_attempt
            ADD COLUMN raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb;
        ALTER TABLE wabot.registration_attempt ALTER COLUMN raw_payload DROP DEFAULT;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'wabot'
          AND table_name = 'registration_attempt'
          AND column_name = 'attempt_no'
    ) THEN
        ALTER TABLE wabot.registration_attempt DROP COLUMN attempt_no;
    END IF;
END $$;
"""


_DOWNGRADE_SQL = """
ALTER TABLE wabot.journey_state ADD COLUMN IF NOT EXISTS retry_count INT NOT NULL DEFAULT 0;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'wabot'
          AND table_name = 'registration_attempt'
          AND column_name = 'raw_text'
    ) THEN
        ALTER TABLE wabot.registration_attempt ADD COLUMN raw_text TEXT NOT NULL DEFAULT '';
        ALTER TABLE wabot.registration_attempt ALTER COLUMN raw_text DROP DEFAULT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'wabot'
          AND table_name = 'registration_attempt'
          AND column_name = 'attempt_no'
    ) THEN
        ALTER TABLE wabot.registration_attempt ADD COLUMN attempt_no INT NOT NULL DEFAULT 1;
        ALTER TABLE wabot.registration_attempt ALTER COLUMN attempt_no DROP DEFAULT;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS wabot.partial_profile_confirmation (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doctor_id       UUID NOT NULL REFERENCES wabot.doctor(id),
    presented_data  JSONB NOT NULL,
    confirmed       BOOLEAN,
    responded_at    TIMESTAMPTZ(6),
    created_at      TIMESTAMPTZ(6) NOT NULL DEFAULT clock_timestamp()
);
"""


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)
