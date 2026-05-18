-- Remove obsolete partial-registration schema from an already-created database.
-- Run in DBeaver against the target PostgreSQL database.

BEGIN;

-- Move any old in-flight partial-registration states to the only active
-- registration waiting state before recreating the enum without obsolete values.
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
        ALTER TABLE wabot.registration_attempt ADD COLUMN raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb;
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

COMMIT;

-- Optional verification after commit:
-- SELECT enumlabel
-- FROM pg_enum e
-- JOIN pg_type t ON t.oid = e.enumtypid
-- JOIN pg_namespace n ON n.oid = t.typnamespace
-- WHERE n.nspname = 'wabot' AND t.typname = 'registration_state'
-- ORDER BY enumsortorder;
--
-- SELECT table_name
-- FROM information_schema.tables
-- WHERE table_schema = 'wabot'
-- ORDER BY table_name;
