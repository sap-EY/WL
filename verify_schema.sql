-- =============================================================================
-- Wockhardt WhatsApp Bot — Schema Verification Script
-- Run this in DBeaver against the same DB after executing models.txt.
-- Every query should return the expected result shown in the comment above it.
-- A final summary section gives a pass/fail count at the end.
-- =============================================================================

SET search_path TO wabot, public;

-- =============================================================================
-- SECTION 1 — Schema
-- =============================================================================

-- Expected: 1 row  (schema_name = 'wabot')
SELECT schema_name
FROM information_schema.schemata
WHERE schema_name = 'wabot';

-- =============================================================================
-- SECTION 2 — Extension
-- =============================================================================

-- Expected: 1 row  (extname = 'pgcrypto')
SELECT extname
FROM pg_extension
WHERE extname = 'pgcrypto';

-- =============================================================================
-- SECTION 3 — Enum types (7 expected)
-- =============================================================================

-- Expected: 7 rows
SELECT typname
FROM pg_type
WHERE typtype = 'e'
  AND typnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'wabot')
ORDER BY typname;

-- Expected values per enum:
SELECT typname, enumlabel
FROM pg_type t
JOIN pg_enum e ON e.enumtypid = t.oid
WHERE typnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'wabot')
ORDER BY typname, enumsortorder;

-- =============================================================================
-- SECTION 4 — Tables (12 expected)
-- =============================================================================

-- Expected: exactly 12 rows
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'wabot'
  AND table_type = 'BASE TABLE'
ORDER BY table_name;

-- =============================================================================
-- SECTION 5 — Column-level checks per table
-- =============================================================================

-- Helper: all columns for wabot tables (scan for anything missing)
SELECT table_name, column_name, data_type, character_maximum_length,
       column_default, is_nullable
FROM information_schema.columns
WHERE table_schema = 'wabot'
ORDER BY table_name, ordinal_position;

-- ---- wabot.doctor — expected columns: id, full_phone_number, first_name,
--                     last_name, speciality, email, address, city, state,
--                     pincode, is_profile_complete, registration_completed_at,
--                     source, created_at, updated_at  (15 columns)
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'wabot' AND table_name = 'doctor'
ORDER BY ordinal_position;

-- ---- Confirm full_name does NOT exist (was removed in v2.1)
-- Expected: 0 rows
SELECT column_name
FROM information_schema.columns
WHERE table_schema = 'wabot' AND table_name = 'doctor'
  AND column_name = 'full_name';

-- ---- wabot.consent
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'wabot' AND table_name = 'consent'
ORDER BY ordinal_position;

-- ---- wabot.consent_history
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'wabot' AND table_name = 'consent_history'
ORDER BY ordinal_position;

-- ---- wabot.whatsapp_onboarding_status
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'wabot' AND table_name = 'whatsapp_onboarding_status'
ORDER BY ordinal_position;

-- ---- wabot.journey_state  (includes expected_outbound_id and version)
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'wabot' AND table_name = 'journey_state'
ORDER BY ordinal_position;

-- ---- wabot.journey_state_history
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'wabot' AND table_name = 'journey_state_history'
ORDER BY ordinal_position;

-- ---- wabot.conversation_session
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'wabot' AND table_name = 'conversation_session'
ORDER BY ordinal_position;

-- ---- wabot.conversation_message  (must have callback_data)
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'wabot' AND table_name = 'conversation_message'
ORDER BY ordinal_position;

-- ---- wabot.outbound_message  (must have callback_data NOT NULL, state_when_sent)
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'wabot' AND table_name = 'outbound_message'
ORDER BY ordinal_position;

-- ---- wabot.webhook_event_raw
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'wabot' AND table_name = 'webhook_event_raw'
ORDER BY ordinal_position;

-- ---- wabot.genai_interaction
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'wabot' AND table_name = 'genai_interaction'
ORDER BY ordinal_position;

-- ---- wabot.registration_attempt
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'wabot' AND table_name = 'registration_attempt'
ORDER BY ordinal_position;

-- ---- wabot.partial_profile_confirmation
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'wabot' AND table_name = 'partial_profile_confirmation'
ORDER BY ordinal_position;

-- =============================================================================
-- SECTION 6 — Indexes (all regular + unique indexes)
-- =============================================================================

-- Expected: 19 index entries (including PK indexes + explicit indexes)
-- Key ones to spot: uq_webhook_event_dedupe, idx_doctor_speciality, idx_outbound_status (partial)
SELECT
    t.relname  AS table_name,
    i.relname  AS index_name,
    ix.indisunique AS is_unique,
    ix.indisprimary AS is_primary,
    pg_get_indexdef(ix.indexrelid) AS definition
FROM pg_index ix
JOIN pg_class t ON t.oid = ix.indrelid
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE n.nspname = 'wabot'
  AND t.relkind = 'r'
ORDER BY t.relname, i.relname;

-- Spot-check: the expression-based dedupe unique index on webhook_event_raw
-- Expected: 1 row
SELECT indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'wabot'
  AND indexname = 'uq_webhook_event_dedupe';

-- =============================================================================
-- SECTION 7 — Triggers (3 expected: doctor, consent, journey_state)
-- =============================================================================

-- Expected: 3 rows
SELECT trigger_name, event_object_table, event_manipulation, action_timing
FROM information_schema.triggers
WHERE trigger_schema = 'wabot'
ORDER BY event_object_table, trigger_name;

-- =============================================================================
-- SECTION 8 — Trigger function
-- =============================================================================

-- Expected: 1 row  (proname = 'set_updated_at')
SELECT proname, prosrc
FROM pg_proc
WHERE proname = 'set_updated_at'
  AND pronamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'wabot');

-- =============================================================================
-- SECTION 9 — Foreign keys
-- =============================================================================

-- Expected: 14 FK relationships (all child tables reference wabot.doctor)
SELECT
    tc.table_name        AS child_table,
    kcu.column_name      AS child_column,
    ccu.table_name       AS parent_table,
    ccu.column_name      AS parent_column,
    rc.delete_rule
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
    ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
JOIN information_schema.referential_constraints rc
    ON tc.constraint_name = rc.constraint_name AND tc.table_schema = rc.constraint_schema
JOIN information_schema.key_column_usage ccu
    ON rc.unique_constraint_name = ccu.constraint_name AND rc.unique_constraint_schema = ccu.table_schema
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND tc.table_schema = 'wabot'
ORDER BY child_table, child_column;

-- =============================================================================
-- SECTION 10 — Check constraints
-- =============================================================================

-- Expected: 1 row  (chk_journey_state_consistency on journey_state)
SELECT tc.constraint_name, tc.table_name, cc.check_clause
FROM information_schema.table_constraints tc
JOIN information_schema.check_constraints cc
    ON tc.constraint_name = cc.constraint_name
WHERE tc.table_schema = 'wabot'
  AND tc.constraint_type = 'CHECK'
  AND tc.constraint_name NOT LIKE '%not_null%'   -- suppress auto NOT NULL checks
ORDER BY tc.table_name;

-- =============================================================================
-- SECTION 11 — NOT NULL spot checks (critical business rules)
-- =============================================================================

-- outbound_message.callback_data must be NOT NULL
-- Expected: 'NO'
SELECT is_nullable
FROM information_schema.columns
WHERE table_schema = 'wabot' AND table_name = 'outbound_message'
  AND column_name = 'callback_data';

-- doctor.is_profile_complete must be NOT NULL
-- Expected: 'NO'
SELECT is_nullable
FROM information_schema.columns
WHERE table_schema = 'wabot' AND table_name = 'doctor'
  AND column_name = 'is_profile_complete';

-- journey_state.version must be NOT NULL
-- Expected: 'NO'
SELECT is_nullable
FROM information_schema.columns
WHERE table_schema = 'wabot' AND table_name = 'journey_state'
  AND column_name = 'version';

-- =============================================================================
-- SECTION 12 — UNIQUE constraints (spot-check key columns)
-- =============================================================================

-- doctor.full_phone_number must be UNIQUE
-- Expected: 1 row
SELECT tc.constraint_name, kcu.column_name
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
    ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
WHERE tc.table_schema = 'wabot'
  AND tc.table_name = 'doctor'
  AND kcu.column_name = 'full_phone_number'
  AND tc.constraint_type = 'UNIQUE';

-- outbound_message.idempotency_key must be UNIQUE
-- Expected: 1 row
SELECT tc.constraint_name, kcu.column_name
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
    ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
WHERE tc.table_schema = 'wabot'
  AND tc.table_name = 'outbound_message'
  AND kcu.column_name = 'idempotency_key'
  AND tc.constraint_type = 'UNIQUE';

-- =============================================================================
-- SECTION 13 — Functional smoke test (insert + read + delete, no side-effects)
-- =============================================================================

BEGIN;

-- Insert a test doctor
INSERT INTO wabot.doctor (full_phone_number, first_name, last_name, speciality, source)
VALUES ('919999999999', 'Test', 'Doctor', 'Cardiology', 'verify_script')
RETURNING id, full_phone_number, first_name, last_name, speciality, is_profile_complete, created_at;

-- Confirm the trigger sets updated_at on UPDATE
UPDATE wabot.doctor
SET city = 'Mumbai'
WHERE full_phone_number = '919999999999'
RETURNING full_phone_number, city, updated_at;

-- Confirm UUID is being generated (non-null)
SELECT id IS NOT NULL AS uuid_generated, left(id::text, 8) AS uuid_prefix
FROM wabot.doctor
WHERE full_phone_number = '919999999999';

-- Confirm cascade tables got no orphan rows
SELECT COUNT(*) AS consent_rows    FROM wabot.consent             WHERE doctor_id IN (SELECT id FROM wabot.doctor WHERE full_phone_number = '919999999999');
SELECT COUNT(*) AS onboarding_rows FROM wabot.whatsapp_onboarding_status WHERE doctor_id IN (SELECT id FROM wabot.doctor WHERE full_phone_number = '919999999999');

ROLLBACK;   -- ← rolls back everything; DB is unchanged after this block

-- =============================================================================
-- SECTION 14 — Summary counts
-- =============================================================================

SELECT 'tables'   AS object_type, COUNT(*) AS found, 12 AS expected,
       CASE WHEN COUNT(*) = 12 THEN 'PASS' ELSE 'FAIL' END AS result
FROM information_schema.tables
WHERE table_schema = 'wabot' AND table_type = 'BASE TABLE'

UNION ALL

SELECT 'enums', COUNT(*), 7,
       CASE WHEN COUNT(*) = 7 THEN 'PASS' ELSE 'FAIL' END
FROM pg_type
WHERE typtype = 'e'
  AND typnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'wabot')

UNION ALL

SELECT 'triggers', COUNT(*), 3,
       CASE WHEN COUNT(*) = 3 THEN 'PASS' ELSE 'FAIL' END
FROM information_schema.triggers
WHERE trigger_schema = 'wabot'

UNION ALL

SELECT 'trigger_function', COUNT(*), 1,
       CASE WHEN COUNT(*) = 1 THEN 'PASS' ELSE 'FAIL' END
FROM pg_proc
WHERE proname = 'set_updated_at'
  AND pronamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'wabot')

UNION ALL

SELECT 'foreign_keys', COUNT(*), 14,
       CASE WHEN COUNT(*) = 14 THEN 'PASS' ELSE 'FAIL' END
FROM information_schema.table_constraints
WHERE table_schema = 'wabot' AND constraint_type = 'FOREIGN KEY'

UNION ALL

SELECT 'check_constraints', COUNT(*), 1,
       CASE WHEN COUNT(*) = 1 THEN 'PASS' ELSE 'FAIL' END
FROM information_schema.table_constraints tc
JOIN information_schema.check_constraints cc
    ON tc.constraint_name = cc.constraint_name
WHERE tc.table_schema = 'wabot'
  AND tc.constraint_type = 'CHECK'
  AND tc.constraint_name NOT LIKE '%not_null%'

UNION ALL

SELECT 'dedupe_index', COUNT(*), 1,
       CASE WHEN COUNT(*) = 1 THEN 'PASS' ELSE 'FAIL' END
FROM pg_indexes
WHERE schemaname = 'wabot' AND indexname = 'uq_webhook_event_dedupe'

ORDER BY object_type;

-- =============================================================================
-- All PASS in Section 14 = schema is correct and complete.
-- =============================================================================
