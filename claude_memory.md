# Claude Memory — Wockhardt WhatsApp Bot

> Living tracker for the 15-day build. Update after every meaningful checkpoint. This file is the single place to look up: where we are, what's done, what's next, and why we made each non-obvious decision. **Read this before starting a new working session.**

---

## 0. Quick status board

| Phase | Title | Status | Notes |
|------:|-------|--------|-------|
| —    | Plan v1                                          | ✅ Done | Initial implementation_plan.md authored |
| —    | Plan v2 (architecture review)                    | ✅ Done | Aligned with user feedback; companion files added |
| 0    | Repository bootstrap                             | ✅ Done | pyproject, Dockerfile, compose, lint, /healthz, smoke tests |
| 1    | Config, logging, correlation                     | ✅ Done | structlog JSON + `X-Correlation-Id` middleware + stable error envelope wired |
| 2    | DB models + Alembic                              | ✅ Done | ORM mapped, Alembic env + idempotent `0001_init`, seed script, /readyz now pings DB |
| 3    | Interakt webhook ingestion                       | ⬜ Not started | |
| 4    | Webhook normalizer + canonical event             | ⬜ Not started | |
| 5    | Orchestrator + per-user lock + free-text router  | ⬜ Not started | Use Redis `user:{full_phone}` snapshot |
| 6    | Outbound dispatcher + Interakt adapter           | ⬜ Not started | `fullPhoneNumber`, `callbackData` mandatory |
| 7    | User registration journey engine                 | ⬜ Not started | |
| 8    | Registered users journey engine + consent        | ⬜ Not started | |
| 9    | GenAI gateway (async)                            | ⬜ Not started | Worker awaits; never the webhook hot path |
| 10   | Status webhook consumer                          | ⬜ Not started | |
| 11   | Observability                                    | ⬜ Not started | |
| 12   | Testing harness                                  | ⬜ Not started | |
| 13   | Deployment readiness                             | ⬜ Not started | |

Legend: ✅ done · 🟡 in progress · ⏳ blocked / waiting · ⬜ not started

---

## 1. Immediate next actions

1. **User**: copy `.env.example` → `.env`, fill in `DB_PASSWORD`, `INTERAKT_API_KEY`, `INTERAKT_WEBHOOK_PATH_SECRET`.
2. **User**: `pip install -e ".[dev]"` → `pre-commit install` → `pytest` (smoke tests should pass).
3. **User**: `docker compose build && docker compose up` → verify `http://127.0.0.1:8000/healthz` returns 200.
4. Move into **Phase 3** (Interakt webhook ingestion: shared-secret URL, raw event persist + dedupe + enqueue, sub-100 ms ack).

---

## 2. Locked decisions (do not revisit without strong reason)

- **No session/idle timeout.** WhatsApp is open-ended; users may resume hours/days later.
- **No `template_category` field** in any send-template call (revisit only when template count grows).
- **`fullPhoneNumber` is the only Interakt phone field used.** Never `countryCode + phoneNumber`.
- **`callbackData = "{outbound_message_id}|{correlation_id}"`** on every outbound. The dispatcher rejects sends without it.
- **Timestamps**: `TIMESTAMPTZ(6)` + `clock_timestamp()` in DB; `datetime.now(UTC)` (microsecond) in Python. Never seconds-only.
- **We own the `doctor` table.** No client DB read-through; one-shot import script will load client-supplied profile data.
- **GenAI is async HTTP**, awaited only inside the worker (after the "please wait" ack has been sent).
- **Webhook auth = shared-secret in URL path.** No HMAC for v1.
- **Local API testing via Thunder Client** (`scripts/thunderclient/`). Postman blocked on dev machine.
- **Modular monolith** with two process roles (`api` and `worker`) sharing one container image.
- **Broker abstraction**: Redis Streams local default, Azure Service Bus (with sessions) for cloud. Per-user FIFO via partition/session = `full_phone_number`.
- **Retries everywhere** = exponential backoff with jitter via `tenacity`.
- **STOP / UNSUBSCRIBE** keywords handled at the router level → set consent declined.
- **Stale historical button click handling** uses `callbackData` chain, not a time window.
- **Registration form (v2.1)**: 7 fields, `#`-delimited single message, order = `Full Name#Speciality#Address#Email#City#State#Pincode`. `Full Name` is split on first whitespace into `first_name` and `last_name`. `doctor` table stores `first_name`, `last_name`, `speciality` (no `full_name`).
- **Repository instruction policy**: `.github/instructions.md` is now the default instruction file and requires `claude_memory.md` updates for every code change or significant decision.

---

## 3. Open questions / awaiting info

| # | Question | Owner | Blocker? |
|---|---|---|---|
| Q1 | Final hotline phone number(s) for `hotline_v1` — confirmed configured inside Interakt template; we just send doctor name. | User | No |
| Q2 | Final list of STOP/UNSUBSCRIBE keywords (English only? Hindi too?) | User | No, default to `STOP`, `UNSUBSCRIBE`, `OPT OUT` |
| Q3 | Exact GenAI base URL + auth token for local dev | GenAI team | Phase 9 only |
| Q4 | Production Azure resource names (RG, Service Bus namespace, Postgres FQDN) | Platform team | Phase 13 only |
| Q5 | One-shot import script: does the client provide a CSV/Excel and what columns? | User | Before go-live, not for code |

---

## 4. Per-phase progress log

Append a dated entry whenever a phase moves forward. Keep entries short (what shipped, what surprised, what's next).

### 2026-05-07 — Plan v2 finalized
- Updated `implementation_plan.md` with all v2 changes (see §22 of the plan for the full diff).
- Created `models.txt` with consolidated PostgreSQL DDL.
- Created this file.
- Next: user runs `models.txt` in DBeaver.

### 2026-05-08 — v2.1 client update: registration form
- Added **Speciality** field to registration (Cardiology / Diabetes / Neurology / Radiology / etc.).
- Switched registration delimiter from newline to `#`. Single-line input, all tokens `.strip()`-ed.
- Replaced `doctor.full_name` with `first_name` + `last_name`; `Full Name` is split on first whitespace at parse time.
- Updated `context_final.md` §6.6/§6.7/§6.8/§6.9/§6.11 copy, `implementation_plan.md` §12 doctor DDL + Phase 7 parser contract + §22 revision log, and `models.txt` doctor table + new `idx_doctor_speciality` index.
- **If `models.txt` was already executed in DBeaver before this change**, run this small migration:
  ```sql
  ALTER TABLE wabot.doctor ADD COLUMN IF NOT EXISTS first_name TEXT;
  ALTER TABLE wabot.doctor ADD COLUMN IF NOT EXISTS last_name  TEXT;
  ALTER TABLE wabot.doctor ADD COLUMN IF NOT EXISTS speciality TEXT;
  -- Optional backfill from existing full_name, then drop:
  -- UPDATE wabot.doctor SET first_name = split_part(full_name,' ',1),
  --        last_name = NULLIF(substring(full_name from position(' ' in full_name)+1), '')
  --        WHERE full_name IS NOT NULL;
  ALTER TABLE wabot.doctor DROP COLUMN IF EXISTS full_name;
  CREATE INDEX IF NOT EXISTS idx_doctor_speciality ON wabot.doctor(speciality);
  ```

<!-- New entries go below this line. Newest first. -->

### 2026-05-08 — Phase 2 complete (data layer, Alembic, seed script)
- **Data layer**: `src/wabot/data/base.py` (`Base(DeclarativeBase)` with `MetaData(schema="wabot", naming_convention=…)`); `src/wabot/data/db.py` (lazy async engine + sessionmaker singletons; `pool_pre_ping=True`, `pool_recycle=1800`, connect-event hook setting `search_path` and `statement_timeout`; `session_scope()` commit-on-success/rollback-on-error; FastAPI `get_session` dep; `ping(timeout_seconds=2.0)` using `asyncio.timeout`; `dispose_engine()`).
- **Domain enums** (`src/wabot/domain/enums.py`): `JourneyType`, `RegistrationState`, `RegisteredState`, `ConsentStatus`, `MessageDirection`, `OutboundStatus`, `OutboundKind`, `ExpectedInputKind` — all `str` enums with values matching the DDL exactly.
- **ORM models** (`src/wabot/data/models/*`): all 12 `wabot` tables mapped — `Doctor`, `Consent`, `ConsentHistory`, `WhatsappOnboardingStatus`, `JourneyState`, `JourneyStateHistory`, `ConversationSession`, `ConversationMessage`, `OutboundMessage`, `WebhookEventRaw`, `GenAIInteraction`, `RegistrationAttempt`, `PartialProfileConfirmation`. Postgres ENUMs are owned by SQL: SA helper `pg_enum()` uses `create_type=False`, `values_callable=lambda e: [m.value for m in e]`. `JourneyState` carries the `journey_state_consistency` `CheckConstraint`. `OutboundMessage.idempotency_key` unique; `OutboundMessage.callback_data` NOT NULL with `PENDING_SEND` default.
- **Repositories** (`src/wabot/data/repositories/*`): `DoctorRepository` (`get_by_phone`, `create_shell`, `upsert_profile` setting `registration_completed_at` when `is_profile_complete` flips true, `patch`); `JourneyStateRepository` (`get_for_update()`, `upsert` bumps `version`, `append_history`); `OutboundMessageRepository` (insert via `pg_insert(...).on_conflict_do_nothing(["idempotency_key"])` + re-read; `mark_sent`, `mark_status` for DELIVERED/READ/FAILED/CLICKED); `WebhookEventRawRepository` (`record_if_new` returning `(row, is_new)` keyed off `(event_type, interakt_message_id, payload->'data'->'message'->>'message_status')`, `mark_processed`).
- **Alembic**: `alembic.ini` (script_location=migrations, prepend_sys_path=src, no DB URL), `migrations/env.py` (online via `async_engine_from_config(..., poolclass=NullPool)`, `version_table_schema=WABOT_SCHEMA`, `_include_object` filters to `wabot` schema), `migrations/script.py.mako`, and **`migrations/versions/20260508_0001_init_init_schema.py`** — `revision="0001_init"`, `down_revision=None`. Because the schema was already applied via DBeaver, `upgrade()` runs `op.execute(_SCHEMA_DDL)` containing the full idempotent DDL from `models.txt` (CREATE SCHEMA / extension / 7 ENUMs in DO blocks / `wabot.set_updated_at()` function / 12 tables with `IF NOT EXISTS` + indexes + triggers, including `uq_webhook_event_dedupe` partial unique index). `downgrade()` drops all 12 tables CASCADE + the trigger function + 7 ENUM types.
- **Seed script**: `scripts/seed_doctors.py` — CLI `python scripts/seed_doctors.py path/to/doctors.csv [--dry-run]`. Validates required columns, normalizes `full_phone_number` (digits-only, len ≥ 10), upserts via `DoctorRepository.upsert_profile`, returns `(inserted, updated)`. Calls `dispose_engine()` in `finally`.
- **App wiring**:
  - `src/wabot/api/routers/health.py`: `/readyz` now `await db_ping()`. On success → 200 with `dependencies={"db": True}`. On failure → 503 with `status="degraded"` and `dependencies={"db": False}`. `HealthResponse.dependencies: DependencyStatus | None`.
  - `src/wabot/main.py`: lifespan now primes the engine on startup and `await dispose_engine()` on shutdown.
  - `src/wabot/workers/inbound_worker.py`: same engine lifecycle in the worker.
- **Tests**: 22 new assertions across `tests/unit/test_models.py` (12 tables registered, `wabot` schema, Doctor PK + phone uniqueness, `journey_state_consistency` constraint, ENUM column names + schema, OutboundMessage idempotency key, FK targets, webhook raw NOT NULLs), `tests/unit/test_db.py` (engine singleton caching, dispose clears singletons, `ping` returns False against unreachable DB without raising), `tests/unit/test_seed_doctors.py` (`_normalize_phone`, `_coerce_bool`, `_row_to_kwargs`). `tests/unit/test_health.py` extended with monkeypatched `/readyz` ok + 503 degraded paths.
- **Test isolation**: `tests/conftest.py` now **forces** test env vars (overriding any developer `.env`) and clears `get_settings.cache_clear()` so the suite can never accidentally talk to the production Azure DB. Caught a bug where `setdefault` left the real DB config in place and the ping test opened a socket to Azure.
- **Toolchain**: Added `pythonpath = ["src", "."]` to `[tool.pytest.ini_options]` so `tests/unit/test_seed_doctors.py` can import the script module. Removed the `WL-wabot-journey-flowchart-v1.png` exclude from `check-added-large-files` in `.pre-commit-config.yaml` (file no longer in the repo).
- **Key decisions**:
  - Initial migration uses `op.execute(...)` against the canonical idempotent DDL rather than autogenerated `op.create_table` calls — this is the single source of truth and stays safe to re-run on the already-provisioned Azure DB.
  - SA ENUMs declared with `create_type=False` so Alembic never tries to create or drop them; lifecycle is owned entirely by the SQL DDL.
  - `clock_timestamp()` + DB trigger `wabot.set_updated_at()` keep `updated_at` accurate without app-side bookkeeping; ORM models therefore omit `onupdate=`.
  - `JourneyStateRepository.get_for_update` uses `with_for_update()` to align with the per-user lock contract from §8 of the plan.
  - Outbound and webhook upserts go through `on_conflict_do_nothing` for race-safe idempotency.
- **Validation**: `pre-commit run --all-files` ✅ all hooks (ruff/format/black/mypy/bandit/yaml/toml/large-files); `pytest -q` ✅ **32 passed**.
- **Next**: Phase 3 — `POST /webhooks/interakt` with shared-secret URL, raw event persist via `WebhookEventRawRepository.record_if_new`, dedupe key `(event_type, interakt_message_id, message_status)`, broker enqueue, ≤100 ms ack, structured error envelope on auth failures.

### 2026-05-08 — Phase 1 complete (logging, correlation, error envelope)
- Added `src/wabot/infra/logging.py`: structlog configured with `merge_contextvars`, `add_log_level`, ISO-8601 UTC timestamps with microseconds (`ts` key), `StackInfoRenderer`, `format_exc_info`, `UnicodeDecoder`. JSON output via `orjson` when `APP_LOG_JSON=true` (prod default), `dev.ConsoleRenderer` otherwise. Stdlib root logger bridged with one StreamHandler so uvicorn/gunicorn lines also flow through. `app`, `env`, `version` bound to contextvars at startup. Idempotent via `_CONFIGURED` guard.
- Added `src/wabot/infra/correlation.py`: `CorrelationMiddleware` reads or mints `X-Correlation-Id` (UUID4), stores it on `request.state.correlation_id`, binds `correlation_id`/`method`/`path` via `structlog.contextvars.bind_contextvars`, resets the tokens in `finally`, and echoes the header on the response. Helpers `new_correlation_id()` and `get_current_correlation_id()`.
- Added `src/wabot/infra/errors.py`: stable envelope `{"error":{"code","message","correlation_id","details"}}`. Typed exceptions `WabotError`, `ValidationFailedError` (400), `NotFoundError` (404), `ConflictError` (409), `DependencyUnavailableError` (503). Handlers registered for `WabotError`, `StarletteHTTPException`, `RequestValidationError`, and unhandled `Exception` (logged via `logger.exception`). HTTP status → code map covers 400/401/403/404/405/409/413/415/422/429 with fallback `http_<status>`. Used `typing.cast` for narrowing (no asserts → bandit B101 clean).
- Wired into `src/wabot/main.py`: `configure_logging(settings)` runs in both `create_app` and `_lifespan`; `CorrelationMiddleware` and `register_exception_handlers` registered before route inclusion. Startup log is now structured: `wabot.startup db=… broker=… log_json=…`.
- Updated `src/wabot/workers/inbound_worker.py` to use `configure_logging` + `get_logger`; removed stdlib `logging.basicConfig`.
- Tests: `tests/unit/test_correlation.py` (auto-generated UUID echo, supplied header echo, distinct ids per request), `tests/unit/test_errors.py` (404 envelope shape + `not_found` code; 405 envelope shape + `method_not_allowed` code; correlation_id matches response header), `tests/unit/test_logging.py` (JSON output with `event`, `level`, `ts`, `app`, `env`, custom field).
- Toolchain: pre-commit mypy hook gained `structlog==25.5.0` and `orjson==3.11.9` in `additional_dependencies`. Replaced two deprecated Starlette status names (`HTTP_413_REQUEST_ENTITY_TOO_LARGE` → `HTTP_413_CONTENT_TOO_LARGE`, `HTTP_422_UNPROCESSABLE_ENTITY` → `HTTP_422_UNPROCESSABLE_CONTENT`) — `pyproject.toml` keeps `filterwarnings = ["error"]`, so DeprecationWarnings break tests.
- Validation: `pre-commit run --all-files` ✅ all hooks; `pytest -q` ✅ 10 passed.
- Next: Phase 2 (SQLAlchemy ORM models mirroring `models.txt`, async engine, Alembic env, seed script).

### 2026-05-08 — Repo instruction baseline added
- Created `.github/instructions.md` with mandatory memory-management rules.
- Locked process rule: every code change and major architecture decision must include a corresponding update in `claude_memory.md` without waiting for a user prompt.
- This is intended to preserve continuity across model switches and keep progress/decisions synchronized.

### 2026-05-08 — Phase 0 complete (repo bootstrap)
- Schema applied to Azure PG (`docbotdatabase.postgres.database.azure.com`, schema `wabot`, user `drbot_admin`) via DBeaver using `models.txt` + verified with `verify_schema.sql`.
- Created: `pyproject.toml` (final dep set, ruff/black/mypy strict), `.env.example` (component-based DB config — password never embedded in URL), `.gitignore`, `.dockerignore`, `.pre-commit-config.yaml`.
- Container: multi-stage `docker/Dockerfile` (python:3.12.6-slim, non-root, tini), `docker/entrypoints/api.sh` and `worker.sh`, `docker-compose.yml` (api + worker + redis; optional `local-db` profile for offline Postgres).
- App skeleton: `src/wabot/__init__.py`, `src/wabot/main.py` (FastAPI factory + lifespan), `src/wabot/api/routers/health.py` (`/healthz`, `/readyz`), `src/wabot/infra/config.py` (final pydantic-settings schema with computed `db_dsn` + masked `db_dsn_for_logging`), `src/wabot/workers/inbound_worker.py` (Phase-0 idle stub with proper signal handling).
- Tests: `tests/conftest.py`, `tests/unit/test_health.py`, `tests/unit/test_config.py`.
- README updated with setup + run instructions.
- Plan §15 `.env` block updated to component DB settings; §17 ops note updated to reference Azure host.
- Next: Phase 1 (structlog JSON, correlation-id middleware, error envelope).

---

## 5. Lessons / gotchas captured during build

(Empty for now. Add anything that caused a >30 min delay so future-us doesn't repeat it.)

---

## 6. File-creation order reference

Mirrored from `implementation_plan.md` §21 for quick reference:

1. `pyproject.toml`, `Dockerfile`, `docker-compose.yml`, `.env.example`
2. `src/wabot/main.py`, `infra/config.py`, `infra/logging.py`, `infra/correlation.py`
3. `data/db.py`, `data/base.py`, `migrations/env.py`, `migrations/versions/0001_init.py`
4. `api/routers/health.py`, `api/routers/webhooks.py`
5. `api/schemas/interakt_webhook.py`, `adapters/interakt/normalizer.py`
6. `cache/client.py`, `cache/locks.py`, `cache/dedupe.py`
7. `adapters/broker/base.py`, `adapters/broker/redis_streams.py`
8. `services/orchestrator.py`, `domain/router.py`, `domain/enums.py`, `domain/events.py`
9. `domain/journeys/base.py`, `domain/journeys/registration.py`
10. `domain/messages/catalog.py`, `domain/messages/builder.py`
11. `adapters/interakt/client.py`, `services/outbound_pipeline.py`
12. `domain/journeys/registered.py`, `domain/consent.py`
13. `adapters/genai/client.py`, `adapters/genai/schemas.py`
14. `workers/inbound_worker.py`, `workers/status_worker.py`
15. Tests, fixtures, Thunder Client collection
