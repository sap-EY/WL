# Claude Memory — Wockhardt WhatsApp Bot

> Living tracker for the 15-day build. Update after every meaningful checkpoint. This file is the single place to look up: where we are, what's done, what's next, and why we made each non-obvious decision. **Read this before starting a new working session.**

---

## 0. Quick status board

| Phase | Title | Status | Notes |
|------:|-------|--------|-------|
| —    | Plan v1                                          | ✅ Done | Initial implementation_plan.md authored |
| —    | Plan v2 (architecture review)                    | ✅ Done | Aligned with user feedback; companion files added |
| 0    | Repository bootstrap                             | ✅ Done | pyproject, Dockerfile, compose, lint, /healthz, smoke tests |
| 1    | Config, logging, correlation                     | 🟡 Partial | `infra/config.py` final; logging+correlation in next phase |
| 2    | DB models + Alembic                              | ✅ DDL applied (DBeaver); SQLAlchemy models pending | DDL applied via `models.txt`; ORM mapping next |
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
4. Move into **Phase 1** (structlog JSON logging + correlation-id middleware + error envelope).
5. Then **Phase 2** (SQLAlchemy ORM models mirroring `models.txt`, Alembic env, seed script).

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
