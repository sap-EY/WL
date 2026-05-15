# Wockhardt WhatsApp Bot — Implementation Plan

> Master engineering blueprint for the Wockhardt LifeSciences WhatsApp bot. This document is the single source of truth for architecture, sequencing, schema, queues, contracts, and operational design. Code generation must follow this plan.

> **Document version: v2 (post architecture review).** Major changes vs v1 are summarized at the end in §22 "Revision Log". When v1 and v2 disagree, v2 wins. Companion files maintained alongside this plan:
> - [models.txt](models.txt) — canonical, copy-paste-ready PostgreSQL DDL for all tables (DBeaver-runnable).
> - [claude_memory.md](claude_memory.md) — living progress tracker (phase status, completed/pending tasks, decisions, open questions).

### Hard constraints baked into v2
- **15-day delivery**: prefer the simplest design that satisfies correctness and the principles in §3. No speculative complexity.
- **No session expiry / no idle timeout**: WhatsApp is open-ended; a user reply hours or days later resumes the journey exactly where it was left.
- **Interakt API field convention**: always use `fullPhoneNumber` (E.164 with country code, no `+`); never `countryCode + phoneNumber`.
- **`template_category` is omitted** in send-template calls (only 2 templates today; revisit if/when more are added).
- **`callbackData` is the cross-message correlation primitive** for outbound→reply chaining (carries our internal outbound_message_id and correlation_id). See §7.8 and §9.
- **Timestamps everywhere**: `TIMESTAMPTZ` with microsecond precision (6 decimals), UTC only — matches the precision Interakt uses in its payloads. Critical for race-condition forensics.
- **Local API testing via Thunder Client** (Postman is blocked on the dev's machine). Collection lives at `scripts/thunderclient/` instead of `scripts/postman/`.
- **We own the master user table**. There is no separate "client master" mirror or read-only view — the `doctor` table in our DB is the canonical source of profile-completeness. Client-supplied data is loaded into it once via a one-shot import script.
- **GenAI is exposed as an async HTTP API** by the GenAI team. We integrate using `await` on a non-blocking `httpx.AsyncClient` call with a hard timeout; the orchestrator worker (not the webhook hot path) is the only place that blocks on it, so frontend message latency is never affected.

---

## 1. Executive Summary

### What is being built
A production-grade, asynchronous, container-deployable **WhatsApp orchestration layer** that connects:
- **Interakt** (WhatsApp BSP) — inbound webhooks + outbound message/template APIs
- **GenAI layer** (external, owned by another team) — free-text intent classification + RAG-backed answer generation
- **Registration backend** (internal services in this codebase) — user identification, registration parsing, consent capture
- **PostgreSQL + Redis + a Service Bus–compatible queue** as the runtime substrate

The system supports two business journeys:
1. **`registered_users`** — free-flow conversational chat (consent → free-text → GenAI → text-only answer with optional buttons).
2. **`user_registration`** — deterministic onboarding for new/partial users that converges into the registered-user journey.

### Core goals
- **Correctness under concurrency**: per-user serial processing, idempotent webhook handling, replay-safe state machine.
- **Sub-3s webhook ack** (Interakt requirement) via accept-then-process pattern.
- **Provider-agnostic core**: Interakt, GenAI, and the message-broker are isolated behind adapters.
- **Local-first** today, **Azure-ready** tomorrow (no rework for Service Bus, App Service / AKS, Azure PostgreSQL Flex, Azure Cache for Redis, Azure Monitor).
- **Observability and auditability** built in from day one (correlation IDs, structured logs, full inbound/outbound audit).
- **Designed for 10⁶+ users**: stateless app tier, partition-aware queue consumption, indexed DB access, hot-path Redis caching.

### Core constraints
- FastAPI + Python only; fully async stack.
- No Azure provisioning right now; PostgreSQL is the only Azure-hosted dep available (via DBeaver to the client environment).
- Interakt = WhatsApp gateway. Templates are pre-created in Interakt (we send by name).
- All outbound to user is **text-only**; supporting media is conveyed via deep links produced by GenAI.
- Thunder Client (vscode extension) is the only client for now. (Postman is blocked in system)

### Why this architecture
- **Modular monolith with strong ports & adapters** gives the speed of a single deployable while preserving clean seams to split into services later (webhook ingestor / orchestrator worker / GenAI gateway).
- **Queue-mediated worker pipeline** decouples webhook ack latency from business processing and gives natural per-user ordering.
- **Redis is for hot state and locks, never the system of record** — Postgres is durable truth.

---

## 2. Source Context Summary

### `context_final.md`
- Two journeys (`registered_users`, `user_registration`); free-flow chat for registered users; all free text → GenAI; text-only outbound; deep links for media.
- Consent decline is a **soft halt** — the user record stays, and re-entry is allowed.
- Free-text router runs phone-number lookup against master data and branches into 4 cases (not-found, fully-registered+onboarded, fully-registered+not-onboarded, partial).
- Registration parser allows max 2 retries before assisted-support escalation.
- Templates referenced: `doctor_welcome_consent_v1`, `hotline_v1` (codenames; created in Interakt).
- Suggested entities and journey states are listed in the context — used as a starting baseline below.

### `interakt_apis.md`
- One unified send endpoint: `POST https://api.interakt.ai/v1/public/message/`.
- Auth: `Authorization: Basic {{API_KEY}}`.
- Supported `type` values used here: `Text`, `InteractiveButton`, `InteractiveList`, `Template`.
- Template payload supports `headerValues`, `bodyValues`, `buttonValues` (indexed), and `template_category` guard (e.g., `utility`).
- Successful response returns `{ result, message, id }` — `id` is the Interakt-assigned message id and must be persisted to correlate downstream status webhooks.

### `interakt_webhook.md`
- Webhook event types we must handle:
  - **Inbound user msg**: `message_received` (look at `data.message.message_content_type`: `Text`, possibly `Interactive`/button replies).
  - **Outbound lifecycle**: `message_api_sent`, `message_api_delivered`, `message_api_read`, `message_api_failed`, `message_api_clicked` (QR vs CTA).
- Performance contract: **HTTPS, 200 OK within 3s**.
- Click events come in two shapes (QR via `meta_data.button_payload.payload.text`; CTA via top-level `event.button_text`/`button_link`). The webhook normalizer must unify these.
- Customer is keyed by `data.customer.channel_phone_number` and an Interakt customer `id`. We must use phone number as the canonical user key, but store Interakt `customer.id` for adapter use.

### `flowchart.txt`
- Per the workspace listing, this file is present at `flowchart.txt` in the workspace root and contains the textual journey already inlined inside `context_final.md` §7 and §8. We treat the inlined flowchart as authoritative; if `flowchart.txt` differs, `context_final.md` wins (and §20 lists this as a follow-up to verify).

### Inferred assumptions / ambiguities
| # | Assumption | Why |
|---|---|---|
| A1 | Interakt webhook does not currently expose an HMAC signature; we will add an **IP allowlist + shared secret in URL path or header** as best-effort verification, and design code to accept HMAC later. | Interakt docs in workspace don't document signature. |
| A2 | Phone numbers are normalized to E.164 without `+` (e.g., `919999999999`) — same shape Interakt uses in `channel_phone_number`. | Consistency with Interakt payloads. |
| A3 | "Onboarded into WhatsApp journey" = `whatsapp_onboarding_status.is_onboarded = true` (set the moment we send the consent template the first time; flips to `consent_accepted` after acceptance). | Context implies a flag; not explicitly modeled. |
| A4 *(revised v2)* | **We own the master user table**. The `doctor` table in our DB is the only source of profile completeness. Client-provided data is loaded once via a one-shot import script. There is no live dependency on any client database or read-replica. | Confirmed by user; removes external read-path latency and cross-system consistency concerns. |
| A5 | Template names and button labels are pre-approved in Interakt and immutable from our side. | Stated in context. |
| A6 *(revised v2)* | **GenAI exposes async HTTP endpoints**. We call them with `httpx.AsyncClient` + `await` from inside the worker (never from the webhook hot path), with a hard timeout and circuit breaker. No streaming required (one user query → one full answer). Frontend latency is fully isolated from GenAI latency. | Confirmed by GenAI team. |
| A7 *(new v2)* | `callbackData` round-trips faithfully on every Interakt event including button-click webhooks. We will pack `outbound_message_id|correlation_id` into it (≤512 chars per Interakt) and use it as the **primary chain-of-context primitive** when a user clicks a button — independent of current journey state. | Verified from `interakt_webhook.md` payloads. |
| A8 *(new v2)* | The `hotline_v1` template takes one body variable (doctor name). The `Call` CTA button is pre-configured inside Interakt to open the user's dialer with the hotline number; our send call does not need to set `buttonValues` for it. | Clarified by user. |
| A9 *(new v2)* | `template_category` field is omitted from all send-template calls during this 15-day build. | Confirmed by user testing — field is optional. |

### Conflicts detected
- Context §5.6 says "Session text + button message" for the post-consent ice-breaker. Interakt's session message API is `Text` only out-of-the-box; **interactive button** session messages use `InteractiveButton`. We will use `InteractiveButton` for any session message that needs buttons (consistent with §5.10 scientific answer with `Satisfied` / `Call hotline`). Documented as a recommended improvement in §20.

---

## 3. Architecture Recommendations

### 3.1 High-level system view

```
                     ┌─────────────────────────────────────────────────────────┐
                     │                       Interakt                          │
                     │   (WhatsApp BSP: send APIs + outbound webhooks)         │
                     └──────────────┬──────────────────────────▲───────────────┘
                                    │ webhooks (HTTPS, ≤3s)    │ outbound API calls
                                    ▼                          │
                ┌──────────────────────────────────────────────┴───────────┐
                │  FastAPI App (modular monolith, async)                   │
                │                                                          │
                │  ┌────────────────────┐   ┌────────────────────────────┐ │
                │  │ Webhook Ingestor   │──►│ Inbound Queue              │ │
                │  │ (HTTP boundary)    │   │ (per-user partitioned)     │ │
                │  └────────────────────┘   └────────────┬───────────────┘ │
                │           ▲                            │                 │
                │           │                            ▼                 │
                │  ┌────────┴───────┐   ┌────────────────────────────────┐ │
                │  │ Status         │   │ Orchestrator Worker            │ │
                │  │ Webhook        │   │ (state machine + journey eng.) │ │
                │  │ Consumer       │   └─┬──────────┬─────────┬────────┘ │
                │  └────────────────┘     │          │         │          │
                │                         ▼          ▼         ▼          │
                │             ┌────────────┐ ┌──────────┐ ┌────────────┐  │
                │             │ Registration│ │ GenAI    │ │ Outbound   │ │
                │             │ Engine     │  │ Gateway  │ │ Dispatcher │ │
                │             └─────┬──────┘ └────┬─────┘ └─────┬──────┘ │
                │                   │             │             │         │
                │  ┌─────────────────────────────────────────────────────┐│
                │  │     Ports & Adapters (Interakt, GenAI, Broker)      ││
                │  └─────┬──────────────────┬───────────────────┬────────┘│
                │        │                  │                   │         │
                │        ▼                  ▼                   ▼         │
                │   PostgreSQL          Redis           Queue (local SB / │
                │   (truth)             (hot state,     Azure SB)         │
                │                        locks, dedupe)                   │
                └──────────────────────────────────────────────────────────┘
```

### 3.2 Component boundaries (logical modules)

| Module | Responsibility | Knows about |
|---|---|---|
| `api.webhooks` | HTTP boundary for Interakt; validate, persist raw, enqueue, ack 200. | Webhook DTOs, raw event store, queue producer |
| `api.health` / `api.admin` | Liveness, readiness, ops endpoints. | None business |
| `domain.journeys.registered` | State machine + transitions for registered-user journey. | Journey state, Redis lock, GenAI port, outbound port |
| `domain.journeys.registration` | State machine for onboarding; partial-data flow. | Master data port, parser, outbound port |
| `domain.router` | Free-text router (Cases A–D). | DB lookups, Redis cache |
| `domain.parsers` | Registration text parsing/validation. | Pure functions |
| `domain.consent` | Consent capture, decline, re-entry. | Consent table |
| `services.orchestrator` | The worker's main `handle_event` entrypoint; per-user serialization. | All journeys |
| `adapters.interakt` | Outbound API client + webhook normalizer. | HTTP, Interakt schemas |
| `adapters.genai` | Sync HTTP client to GenAI. | HTTP, GenAI contract |
| `adapters.broker` | Queue port; impls: `local_sqlite_broker`, `azure_servicebus_broker`. | Queue ports |
| `data.repositories` | One repo per aggregate; async SQLAlchemy. | DB |
| `data.cache` | Redis helpers (locks, dedupe, hot read-through). | Redis |
| `infra.config` | Pydantic settings, env loading. | None |
| `infra.logging` | Structured logging, correlation IDs. | None |
| `workers.entrypoints` | Worker process entrypoints (run_inbound_worker, etc.). | Orchestrator |

### 3.3 Modular monolith vs services
**Recommended: modular monolith** with two **process roles** (web + worker) sharing the codebase:
- **Web role** → FastAPI app: receives webhooks, persists raw event, enqueues, returns 200. Tiny, hot path only.
- **Worker role** → consumes queue, runs orchestrator, calls GenAI, calls Interakt outbound, writes DB.

Both share modules; deployed as the same container image with different `CMD`. This gives:
- Independent horizontal scaling of ingestion vs processing.
- Zero IPC complexity until we actually need to split.
- A clean future path to two separate services when the GenAI gateway needs its own scaling profile or rate-limit handling.

---

## 4. Recommended Tech Stack

| Concern | Choice | Rationale |
|---|---|---|
| Web framework | **FastAPI** | Async, Pydantic-native, OpenAPI for free. |
| ASGI server | **Uvicorn** behind **Gunicorn** with `uvicorn.workers.UvicornWorker` (prod) | Industry standard for FastAPI on containers. |
| Validation | **Pydantic v2** | Strict v2 models, faster, better discriminated unions for webhook variants. |
| ORM | **SQLAlchemy 2.0 async** (Core + ORM) | Mature, async-first, works with asyncpg. |
| DB driver | **asyncpg** | Best async perf for Postgres. |
| Migrations | **Alembic** (async env) | De-facto standard. |
| Redis client | **redis-py >= 5** with `redis.asyncio` | Official, async, supports Lua and Streams. |
| HTTP client | **httpx (AsyncClient)** with retry+timeouts via **tenacity** | Async, connection pooling, mature. |
| Queue (local) | **In-process broker over Redis Streams** with consumer groups (or `aio-pika` + RabbitMQ in compose) | Mirrors Service Bus semantics: ack/nack, ordering by stream, DLQ via separate stream. |
| Queue (cloud) | **Azure Service Bus** via `azure-servicebus.aio` | Already targeted; sessions enable per-user FIFO. |
| Background jobs | Native worker process consuming the broker (no Celery) | Avoids extra moving parts; keeps async story consistent. |
| Logging | **structlog** + stdlib logging, JSON renderer | Structured, correlation-id friendly. |
| Config | **pydantic-settings** | Validates env at startup. |
| Testing | **pytest**, **pytest-asyncio**, **httpx.AsyncClient**, **testcontainers-python** for PG & Redis | Real integration tests without flakiness. |
| Lint/format | **ruff**, **black**, **mypy --strict**, **isort** (via ruff) | Modern, fast, opinionated. |
| Static security | **bandit**, **pip-audit** | Catches obvious issues. |
| Container | Multi-stage **Docker** (python:3.12-slim) + **docker-compose** for local | Reproducible. |
| Docs | FastAPI auto-OpenAPI + `mkdocs-material` for engineering docs | Both API + ADRs. |
| UUIDs | **UUIDv7** (time-ordered) via `uuid-utils` | Index-friendly, replaces UUIDv4 for primary keys. |
| Time/TZ | All UTC, `datetime.now(tz=UTC)`; never naive | Avoids classic bugs. |
| Correlation IDs | `X-Correlation-Id` header, propagated through structlog contextvars and queue message headers | End-to-end tracing pre-OpenTelemetry. |
| Idempotency | Composite: webhook event id + a hash of payload, persisted in `webhook_event_raw` with unique index | Safe re-delivery. |
| Timestamp precision | `TIMESTAMPTZ(6)` on all temporal columns; `datetime.now(UTC)` (microsecond precision) in Python; never naive datetimes; never seconds-only logs | Matches Interakt payload precision; essential for race-condition forensics. |
| Tracing (later) | **OpenTelemetry SDK** (Azure Monitor exporter) — wired as no-op locally | Zero rework to enable in Azure. |

---

## 5. Project Structure

```
./
├── pyproject.toml
├── README.md
├── .env.example
├── .gitignore
├── .dockerignore
├── docker/
│   ├── Dockerfile
│   └── entrypoints/
│       ├── api.sh
│       └── worker.sh
├── docker-compose.yml                # local: app, worker, redis, (optional rabbitmq), pgadmin
├── alembic.ini
├── migrations/
│   ├── env.py
│   └── versions/
├── models.txt                        # canonical PostgreSQL DDL (DBeaver-runnable)
├── claude_memory.md                  # progress + decisions tracker
├── scripts/
│   ├── seed_dev_data.py
│   ├── send_test_webhook.py          # posts sample Interakt payloads to /webhooks/interakt
│   └── thunderclient/
│       └── wabot.thunder-collection.json
├── src/
│   └── wabot/
│       ├── __init__.py
│       ├── main.py                   # FastAPI app factory + lifespan
│       ├── api/
│       │   ├── __init__.py
│       │   ├── deps.py
│       │   ├── routers/
│       │   │   ├── webhooks.py       # POST /webhooks/interakt
│       │   │   ├── health.py
│       │   │   └── admin.py          # internal: replay, fetch state, force send
│       │   └── schemas/              # request/response Pydantic
│       │       ├── interakt_webhook.py
│       │       └── admin.py
│       ├── domain/
│       │   ├── enums.py              # JourneyType, JourneyState, EventKind, ...
│       │   ├── events.py             # CanonicalInboundEvent, OutboundIntent, ...
│       │   ├── router.py             # free-text router (Cases A–D)
│       │   ├── consent.py
│       │   ├── parsers/
│       │   │   ├── registration.py
│       │   │   └── validators.py
│       │   ├── journeys/
│       │   │   ├── base.py           # AbstractJourney
│       │   │   ├── registered.py
│       │   │   └── registration.py
│       │   └── messages/
│       │       ├── catalog.py        # message templates / copy strings keyed by symbol
│       │       └── builder.py        # builds Interakt payloads from intents
│       ├── services/
│       │   ├── orchestrator.py       # worker entry: handle_event(canonical_event)
│       │   ├── inbound_pipeline.py   # raw → canonical → dispatch
│       │   ├── outbound_pipeline.py
│       │   └── locks.py              # per-user serialization
│       ├── adapters/
│       │   ├── interakt/
│       │   │   ├── client.py         # outbound HTTP
│       │   │   ├── normalizer.py     # webhook → canonical event
│       │   │   └── schemas.py
│       │   ├── genai/
│       │   │   ├── client.py
│       │   │   └── schemas.py
│       │   └── broker/
│       │       ├── base.py           # Broker port
│       │       ├── redis_streams.py  # local default
│       │       ├── rabbitmq.py       # optional local
│       │       └── azure_servicebus.py
│       ├── data/
│       │   ├── db.py                 # engine, session
│       │   ├── base.py               # SQLAlchemy Base
│       │   ├── models/
│       │   │   ├── doctor.py         # owned master + profile-completeness flag
│       │   │   ├── consent.py
│       │   │   ├── journey_state.py
│       │   │   ├── conversation.py
│       │   │   ├── messages.py
│       │   │   ├── webhook_event.py
│       │   │   ├── genai_log.py
│       │   │   └── registration.py
│       │   └── repositories/
│       │       ├── doctor_repo.py
│       │       ├── journey_repo.py
│       │       ├── message_repo.py
│       │       ├── webhook_repo.py
│       │       └── ...
│       ├── cache/
│       │   ├── client.py             # redis async client factory
│       │   ├── locks.py              # SET NX PX based per-user lock
│       │   └── dedupe.py
│       ├── infra/
│       │   ├── config.py             # pydantic-settings
│       │   ├── logging.py            # structlog
│       │   ├── correlation.py        # contextvars + middleware
│       │   ├── errors.py             # typed exceptions
│       │   └── telemetry.py          # OTel hooks (no-op local)
│       └── workers/
│           ├── inbound_worker.py
│           └── status_worker.py
└── tests/
    ├── unit/
    ├── integration/
    ├── contract/                     # interakt + genai contract tests
    ├── fixtures/
    │   ├── interakt_webhooks/        # JSON files mirrored from interakt_webhook.md
    │   └── genai/
    └── conftest.py
```

---

## 6. Development Sequence / Roadmap

> Phases are sized so each phase ends in something demoable. "Complexity" is qualitative (S/M/L).

### Phase 0 — Repository bootstrap (S)
- **Objective**: Project skeleton, tooling, CI hooks.
- **Outputs**: `pyproject.toml`, ruff/mypy/black config, pre-commit, `Dockerfile`, `docker-compose.yml`, base `src/wabot/main.py` with `/healthz`.
- **Dependencies**: none.
- **Risks**: tooling churn; mitigated by pinning versions.

### Phase 1 — Config, logging, correlation (S)
- **Objective**: Environment-driven config, structured logs, correlation middleware, error envelope.
- **Outputs**: `infra/config.py`, `infra/logging.py`, `infra/correlation.py`, exception handlers.
- **Dependencies**: Phase 0.
- **Risks**: getting structlog binding right with FastAPI deps.

### Phase 2 — DB models + Alembic (M)
- **Objective**: Full schema as in §12 plus initial migration.
- **Outputs**: SQLAlchemy models, alembic env, migration `0001_init.py`, seed script.
- **Dependencies**: Phase 1.
- **Risks**: master-data shape uncertain — encapsulate via a read-only repo so we can adapt.

### Phase 3 — Interakt webhook ingestion (M)
- **Objective**: `POST /webhooks/interakt` endpoint that validates, persists raw event, dedupes, enqueues, returns 200 in <100ms.
- **Outputs**: webhook router, raw-event repo, dedupe via `webhook_event_dedupe` unique index + Redis short-TTL set, enqueue via broker port (impl: Redis Streams locally).
- **Dependencies**: Phase 2.
- **Risks**: missing signature → mitigated with shared-secret URL token + IP allowlist toggle.

### Phase 4 — Webhook normalizer + canonical event model (S)
- **Objective**: Turn every Interakt event (`message_received`, `message_api_*`) into a canonical event.
- **Outputs**: `adapters/interakt/normalizer.py`, `domain/events.py`.
- **Dependencies**: Phase 3.

### Phase 5 — Orchestrator + per-user lock + free-text router (M)
- **Objective**: Worker that consumes queue, takes a per-user Redis lock, loads journey state, routes to journey handler.
- **Outputs**: `services/orchestrator.py`, `cache/locks.py`, `domain/router.py`.
- **Dependencies**: Phase 4.
- **Risks**: lock leases vs long GenAI calls — handle with watchdog refresh.

### Phase 6 — Outbound dispatcher + Interakt adapter (M)
- **Objective**: Send text, button, and template messages to Interakt with retries; persist outbound log; correlate Interakt-returned `id`.
- **Outputs**: `adapters/interakt/client.py`, `services/outbound_pipeline.py`, `domain/messages/builder.py`, `domain/messages/catalog.py`.
- **Dependencies**: Phase 1.

### Phase 7 — User registration journey engine (M)
- **Objective**: Single-path onboarding via a WhatsApp Flow form. Bot
  sends `user_registration_v1` template on first inbound from an
  unregistered phone; user fills the in-app form; backend stores the
  profile.
- **Outputs**: `domain/parsers/registration.py`,
  `domain/journeys/registration.py`, repo updates,
  `migrations/versions/...add_mci_id.py`.
- **Dependencies**: Phases 5–6.
- **Form schema** (configured in Interakt, flow id `985469590600160`):
  - `first_name` — required text
  - `last_name`  — required text
  - `mci_id`     — optional text (new `doctor.mci_id` column, see §13
    of `models.txt`)
  - `speciality` — required multi-select; backend joins values with
    `", "` before storage
- **Parser contract** (binding):
  - Input: `data.message.message.nfm_reply.response_json` dict from a
    `message_api_flow_response` webhook.
  - Keys are matched by **case-insensitive substring** against the
    field markers (`first_name`, `last_name`, `mci_id`, `speciality`)
    so Interakt's `screen_<n>_` prefix is transparent to us.
  - Empty payload or any missing required field raises
    `RegistrationParseError`, which the handler turns into an
    `ASSISTED_SUPPORT` transition — there is **no retry counter and
    no partial-data confirmation step**.
  - `email`, `address`, `city`, `state`, `pincode` are persisted as
    `NULL` (the columns remain in the schema for future use).
- **Catalog symbols**: `TEMPLATE_USER_REGISTRATION` (Flow template,
  `is_flow_template = true`), `MSG_REG_COMPLETED`,
  `MSG_REG_ASSISTED_SUPPORT`.

### Phase 8 — Registered users journey engine + consent (L)
- **Objective**: Welcome+consent template, accept/decline, ice-breaker (interactive button), free-text → GenAI loop, scientific vs non-scientific branches, hotline template, fallbacks.
- **Outputs**: `domain/journeys/registered.py`, `domain/consent.py`.
- **Dependencies**: Phase 7.

### Phase 9 — GenAI gateway (M)
- **Objective**: Sync client with timeouts, retries (idempotent), circuit breaker (simple), trace IDs, contract enforcement.
- **Outputs**: `adapters/genai/client.py`, `adapters/genai/schemas.py`, `genai_log` repo.
- **Dependencies**: Phase 8.

### Phase 10 — Status webhook consumer (S)
- **Objective**: Update outbound message log on `message_api_sent/delivered/read/failed/clicked`; triggers state transitions (e.g., user clicked `Satisfied`).
- **Dependencies**: Phase 4.

### Phase 11 — Observability (S/M)
- **Objective**: Structured logs everywhere, basic Prometheus-compat `/metrics` (via `prometheus-fastapi-instrumentator`), OTel hooks.
- **Dependencies**: Phase 1.

### Phase 12 — Testing harness (M)
- **Objective**: Unit/integration/contract tests; replay test using fixtures from `interakt_webhook.md`.
- **Dependencies**: All prior.

### Phase 13 — Deployment readiness (S)
- **Objective**: Production Dockerfile, healthz/readyz, graceful shutdown, secrets via env, sample `azure-pipelines.yml` / `bicep` left as TODO doc.
- **Dependencies**: All prior.

---

## 7. Journey Engine / State Management Design

### 7.1 Storage strategy
- Each user has at most **one active journey** at a time, modeled as a row in `journey_state` keyed by `doctor_id`.
- Each row has: `journey_type`, `state`, `state_entered_at`, `expected_input_kind` (e.g., `BUTTON`, `FREE_TEXT`, `REGISTRATION_TEXT`), `retry_count`, `context_jsonb` (small per-state scratchpad — e.g., `pending_fields`, `last_template_msg_id`).
- All transitions go through the journey handler; **no journey state mutation outside handlers**.

### 7.2 Why not JSON-driven state machine files
A JSON state-machine *looks* attractive but the journey logic here is non-trivially tied to:
- Repository lookups (master data, consent, partial fields).
- External calls (GenAI, Interakt).
- Side-effects ordering (send ack → send answer → update state).

A declarative JSON would push that complexity into runtime interpreters, hurting readability and testability. **Recommendation: code-as-state-machine** using `enum`-typed states and explicit handler classes (`AbstractJourney`). Keep the *copy text* and *button labels* in `domain/messages/catalog.py` (data-driven), but the transitions in code.

### 7.3 State enums

```python
class JourneyType(str, Enum):
    REGISTRATION = "registration"
    REGISTERED = "registered"

class RegistrationState(str, Enum):
    REG_INITIATED = "REG_INITIATED"
    AWAITING_FULL_DETAILS = "AWAITING_FULL_DETAILS"
    PARTIAL_CONFIRM_PENDING = "PARTIAL_CONFIRM_PENDING"
    AWAITING_REMAINING_DETAILS = "AWAITING_REMAINING_DETAILS"
    AWAITING_CORRECTED_FULL = "AWAITING_CORRECTED_FULL"
    REGISTRATION_COMPLETED = "REGISTRATION_COMPLETED"
    ASSISTED_SUPPORT = "ASSISTED_SUPPORT"

class RegisteredState(str, Enum):
    CONSENT_PENDING = "CONSENT_PENDING"
    CONSENT_DECLINED = "CONSENT_DECLINED"
    CONSENT_ACCEPTED = "CONSENT_ACCEPTED"
    AWAITING_FREE_TEXT = "AWAITING_FREE_TEXT"
    GENAI_PROCESSING = "GENAI_PROCESSING"
    AWAITING_ANSWER_BUTTON = "AWAITING_ANSWER_BUTTON"   # Satisfied / Call hotline
    HOTLINE_TEMPLATE_SENT = "HOTLINE_TEMPLATE_SENT"
```

### 7.4 Transition contract
Each handler receives `(canonical_event, journey_row, repos)` and returns a `JourneyResult`:
- `next_state`
- `outbound_intents` (list — sent in order via outbound dispatcher)
- `expected_input_kind` (informs router for next inbound)
- `context_patch`

The orchestrator persists state **after** outbound dispatch succeeds (or after a "soft" success — see §11 idempotency).

### 7.5 Resuming sessions (no expiry)
- On every inbound event, the orchestrator **reloads the journey row from DB inside the per-user lock** (with a Redis read-through — see §13). No in-memory cache across events.
- **There is no idle/session timeout.** A reply hours, days, or weeks later resumes exactly where the journey was left. WhatsApp is an open-ended channel and we deliberately do not block users on time.
- The only "reset" paths are explicit: registration completion, consent decline (followed by future re-entry), and a successful `Satisfied` click (which simply transitions back to `AWAITING_FREE_TEXT`).

### 7.6 Onboarding detection
- `whatsapp_onboarding_status.is_onboarded` is `true` once **the consent template has been sent at least once** (regardless of accept/decline). This prevents resending the consent template on every inbound.

### 7.7 Consent re-entry rules
- Decline → set `consent.status = DECLINED`, `is_onboarded = true`. The next inbound free-text from this user re-triggers the consent template (no cooldown by default; we removed the cooldown env var to keep the build simple — context says "future inbound message can trigger consent template message again").
- Accept → set `consent.status = ACCEPTED`, persist `accepted_at`, send acknowledgement + ice-breaker.

### 7.8 Chain-of-context via `callbackData` (replaces "stale click" timeout logic)
WhatsApp lets users scroll back and click buttons on **any** historical bot message. We resolve this without time windows by exploiting Interakt's `callbackData` round-trip:

- On every outbound send (text, buttons, template), we set:
  ```
  callbackData = f"{outbound_message_id}|{correlation_id}"
  ```
  (≤512 chars; UUIDv7s + a separator fit comfortably.)
- Interakt echoes this back in `message_api_clicked` events under `data.event.callbackData` (CTA) or `data.message.meta_data.source_data.callback_data` (QR/quick-reply). The webhook normalizer extracts it.
- On a button click event the orchestrator looks up `outbound_message_id` in `outbound_message` and decides:
  1. **Genuine current-step click** — the referenced outbound is the latest expectation row for this user → process the click and advance state.
  2. **Stale historical click** (e.g., user scrolled up and clicked an old `Satisfied`) — the referenced outbound is older than the user's last forward action → treat as a no-op (optionally send Fallback 1 "please continue with your latest question"). No state mutation.
  3. **Unknown** (callbackData missing or unparseable) — fall back to current journey-state expectation. Log and metric.
- Free-text replies have **no callbackData linkage** (WhatsApp doesn't carry it). For free text we rely solely on `journey_state` + `expected_input_kind` + `conversation_message` history.

---

## 8. Inbound Webhook Processing Design

### 8.1 Endpoint
- `POST /webhooks/interakt/{shared_secret}` — secret in path lets us rotate keys per Interakt config without redeploying routes.
- Request size cap: 256 KB (FastAPI middleware).

### 8.2 Fast-ack pattern
1. Parse minimally (just `type` + `data.message.id` + `data.customer.channel_phone_number`).
2. Compute `event_id = data.message.id` (Interakt provides it). Fallback: `sha256(type|raw_body)`.
3. **Insert** into `webhook_event_raw` with `UNIQUE (event_type, interakt_message_id, message_status)`. On unique-violation → already seen → return 200 immediately.
4. Push **canonical event reference** (`webhook_event_raw.id`) onto inbound queue with **partition key = `fullPhoneNumber`**.
5. Return `200 OK` with empty body. Target P95 < 80ms.

> Heavy work (validation, normalization, journey routing, GenAI, outbound) happens in the worker.

### 8.3 Authentication / verification (kept simple for v2)
- Use a **shared-secret in the webhook URL path** (configured in Interakt's webhook settings). That is sufficient for the 15-day build and is what Interakt's docs support today.
- Do **not** log the secret. Do **not** invent HMAC schemes — once the project is live and stable we will revisit if Interakt adds signature support.

### 8.4 Idempotency keys
- Primary: `data.message.id` (per Interakt).
- Secondary: `(event_type, message_id, message_status)` because the same message id appears across `sent`/`delivered`/`read`/`clicked`. Unique index = composite.
- Tertiary defensive: a Redis SETNX on `dedupe:webhook:{event_id}:{event_type}` with TTL 10 min — saves a DB hit when retries hit within that window.

### 8.5 Sequencing concerns
- Interakt may deliver `delivered` before `sent` in rare cases. Status updates are **monotonic over `received_at_utc`**: outbound message status only advances to a "later" status; never regresses. Worker enforces this when applying status updates.
- Inbound user messages from the same number must be processed **strictly in arrival order** — guaranteed by:
  - Single-stream Redis Streams partitioned by phone number (locally), or Service Bus **sessions** with `SessionId = phone_number` (cloud).
  - Per-user Redis lock as a defensive layer.

### 8.6 Canonical event model
```python
class CanonicalInboundEvent(BaseModel):
    correlation_id: UUID
    raw_event_id: UUID                          # FK -> webhook_event_raw.id
    interakt_message_id: str
    interakt_customer_id: str
    full_phone_number: str                      # canonical user key (E.164, no '+')
    event_kind: Literal[
        "user_text", "user_button_reply", "user_list_reply",
        "outbound_sent", "outbound_delivered", "outbound_read",
        "outbound_failed", "outbound_clicked"
    ]
    text: str | None
    button_text: str | None                     # 'Satisfied' | 'Call hotline' | etc.
    click_type: Literal["QR", "CTA"] | None     # from message_api_clicked variants
    callback_data: str | None                   # round-tripped from outbound; chain-of-context
    referenced_outbound_message_id: UUID | None # parsed from callback_data when present
    received_at: datetime                       # microsecond precision UTC
```

### 8.7 Raw event persistence
- Every webhook is stored verbatim in `webhook_event_raw(payload jsonb)` keyed by the dedupe composite. This is our **replay log** and the basis for incident debugging. Retention: 90 days (configurable; later move to cold storage).

### 8.8 Error handling
- If queue enqueue fails after 3 fast retries → still respond 200 (we have the raw row), and a janitor job replays unprocessed `webhook_event_raw` rows older than 30s.
- If raw insert fails (DB outage) → respond 503 so Interakt retries. This is the only path that breaks the 3s SLA acceptably; alarms fire instantly.

---

## 9. Outbound Messaging Design

### 9.1 Outbound intent → adapter call
Journey handlers emit **`OutboundIntent`** objects, never call Interakt directly:

```python
class OutboundIntent(BaseModel):
    kind: Literal["TEXT", "BUTTONS", "TEMPLATE"]
    full_phone_number: str                   # E.164 without '+'  -> Interakt 'fullPhoneNumber'
    template_name: str | None
    template_locale: str | None = "en"
    body_values: list[str] | None            # template bodyValues
    header_values: list[str] | None          # template headerValues
    button_values: dict[str, list[str]] | None  # template buttonValues (only when CTA needs vars)
    text: str | None                         # for TEXT / BUTTONS
    buttons: list[InteractiveButton] | None  # for BUTTONS (session interactive)
    # callback_data is set by the dispatcher just before send:
    #   f"{outbound_message_id}|{correlation_id}"
    idempotency_key: str                     # see §9.2
```

Notes:
- `template_category` is **never** sent (per A9).
- We always send `fullPhoneNumber`; we never split into `countryCode + phoneNumber`.
- `hotline_v1` template only needs `body_values=[doctor_name]`; the `Call` CTA is configured inside Interakt and needs no `button_values` from us (per A8).

### 9.2 Outbound idempotency
Interakt does not deduplicate sends server-side. We compute an `idempotency_key = sha256(doctor_id|journey_state|outbound_seq|payload_hash)` and store an `outbound_message` row with `UNIQUE(idempotency_key)` **before** calling Interakt. If the call succeeds, we store the returned Interakt id. If the call fails after the row was written, a retry uses the same idempotency_key — so the row is reused, not duplicated.

### 9.3 Catalog & builder
- `domain/messages/catalog.py` — single source of truth for the user-facing copy from §5–§6 and the template/button identifiers. Keys are symbolic (`MSG_REG_FULL_DETAILS_PROMPT`, `BTN_SATISFIED`, `TEMPLATE_DOCTOR_WELCOME_CONSENT`).
- `domain/messages/builder.py` — pure functions: `(intent_symbol, params) -> OutboundIntent`. Easy to unit-test and translate later.

### 9.4 Adapter responsibilities
- Translate `OutboundIntent.kind` to the right Interakt JSON shape (`Text`, `InteractiveButton`, `Template`).
- Always include `fullPhoneNumber` and `callbackData`. Never include `template_category`.
- Send with retry policy:
  - Network errors / 5xx: **exponential backoff with jitter** — `min(2^n * 0.5s, 8s)` with ±20% jitter, max 4 tries (n=0..3) via `tenacity`.
  - 4xx: do **not** retry; mark message `FAILED`, surface to journey so the handler can choose a fallback.
- Timeout: 5s connect, 10s read. Configurable.
- **Rate limiting**: the adapter does **not** enforce a client-side
  request-per-second cap. Interakt's quota is the source of truth; a
  `429 Too Many Requests` response is reclassified as a transient
  error and retried under the same tenacity policy as 5xx/network
  errors. No Redis token bucket is used.

### 9.5 Status correlation
Webhook events `message_api_*` are joined back to `outbound_message` via `interakt_message_id` returned at send time. The status worker updates lifecycle columns: `sent_at`, `delivered_at`, `read_at`, `failed_at`, `failure_reason`, `clicked_at`, `clicked_button_text`.

---

## 10. Queue Design / Service Bus Planning

### 10.1 Queues we will introduce

| Logical Queue | Purpose | Partition / Session key | Ordering | DLQ |
|---|---|---|---|---|
| `inbound.user-events` | All user-originated events (text, button replies). Drives journey transitions. | `phone_e164` | **Strict per-user FIFO** | yes |
| `outbound.delivery-status` | All `message_api_*` (sent/delivered/read/failed/clicked). Updates outbound logs and may trigger flows (e.g., click on `Satisfied`). | `phone_e164` | best-effort FIFO; idempotent applier | yes |
| `genai.requests` *(optional, deferred)* | If we move GenAI calls async to ride out spikes. Initially we keep GenAI sync inside the inbound worker. | — | — | yes |
| `outbound.send-retry` | Failed outbound that needs delayed retry beyond the fast in-process retry. | `phone_e164` | best-effort | yes |
| `housekeeping` | Janitor jobs (replay stuck raw events, idle session sweeps). | none | none | yes |

### 10.2 Why per-user sessions
A doctor sending `text → button → text` quickly must not have those events processed in parallel — that creates state-race nightmares. Service Bus **sessions** (or Redis Streams partitioned by phone) give us message-level FIFO **per-user** with concurrency **across users**.

### 10.3 Local broker plan
- **Default**: Redis Streams + consumer groups.
  - One stream per logical queue: `stream:inbound:user-events`.
  - Partitioning: we add field `session_id = phone_e164`. Worker uses **a hash partitioner on session_id** to assign one of N internal coroutines, each owning a stable subset — this preserves per-user order without needing per-key streams (which would explode for 10⁶ users).
  - Acks via `XACK`; retries via `XPENDING`/`XCLAIM`; DLQ = a sibling `:dlq` stream after `MAX_DELIVERY_COUNT`.
- **Alternative**: RabbitMQ with consistent-hash exchange (`x-consistent-hash`) — wire-compatible mental model with Service Bus sessions; we keep this as an optional compose service for stress testing.

### 10.4 Cloud (Azure) broker plan
- Azure Service Bus **queues with sessions enabled** for `inbound.user-events` and `outbound.delivery-status`.
- `SessionId = phone_e164`. Consumers use `ServiceBusSessionReceiver`.
- Built-in DLQ on max delivery count (default 5); we also set TTL = 24h.
- **Duplicate detection** enabled (10-min window) using `MessageId = canonical_event_id`.

### 10.5 Broker abstraction (port)

```python
class Broker(Protocol):
    async def publish(self, topic: str, key: str, payload: bytes,
                      message_id: str, headers: dict[str, str]) -> None: ...
    async def consume(self, topic: str, group: str,
                      handler: Callable[[BrokerMessage], Awaitable[None]]) -> None: ...
```

Concrete impls: `RedisStreamsBroker`, `AzureServiceBusBroker`, `InMemoryBroker` (tests). Code never imports the concrete class directly.

### 10.6 Retry / DLQ / poison handling
- 3 in-broker redeliveries with exponential backoff (1s, 5s, 30s).
- After max delivery count → DLQ with full headers, including the failing exception class and last-known journey state.
- An admin endpoint `POST /admin/dlq/replay` re-queues DLQ items by ids (RBAC-gated).

### 10.7 Local development simulation
- `docker-compose.yml` brings up Redis. The `RedisStreamsBroker` is the default `BROKER_DRIVER=redis_streams`. Switching to `BROKER_DRIVER=azure_servicebus` requires only env changes — no code changes.

---

## 11. Concurrency, Ordering, and Idempotency

### 11.1 The three layers
1. **Queue-level FIFO per user** (sessions / partitioned streams) — primary ordering guarantee.
2. **Per-user Redis lock** inside the worker — defensive, also serializes against the rare case of two workers competing on the same session due to rebalance.
3. **DB-level optimistic concurrency** — `journey_state` has `version` integer; updates do `WHERE version = :v`; mismatch raises and the message is nacked for retry.

### 11.2 Per-user lock
- Key: `lock:user:{phone_e164}`.
- Acquire: `SET key worker_id NX PX 30000`.
- Heartbeat: a watchdog refreshes the TTL every 10s while the handler runs (extends to 30s) — important because GenAI calls can take 5–15s.
- Release on success/failure via Lua script that checks owner.

### 11.3 Duplicate webhook defense
- DB unique on `(interakt_message_id, event_type, message_status)` in `webhook_event_raw`.
- Redis SETNX dedupe with 10-min TTL.
- Worker handler is **idempotent by construction**: every state change is keyed off `last_processed_event_id` on `journey_state`. If the same event arrives twice, the second is a no-op.

### 11.4 Out-of-order user messages
- Queue per-user FIFO is the primary guarantee. We do **not** add a time-window rejection (no expiry — see §7.5). Instead, the handler combines two cheap checks before mutating state:
  1. `last_processed_event_id` on `journey_state` — if the incoming `interakt_message_id` was already processed → no-op.
  2. For button clicks, `callback_data` resolves to an `outbound_message_id`; if it is older than the user's latest forward action → treat as stale historical click (see §7.8).

### 11.5 Free-text + button mix
- If `expected_input_kind = BUTTON` and a free-text arrives:
  - For `AWAITING_ANSWER_BUTTON` (post-scientific-answer), context says we should treat **the free text as the next query** (loop continues). We honor that.
  - For `PARTIAL_CONFIRM_PENDING` and `CONSENT_PENDING`, we send Fallback 1 ("please choose one of the options").

### 11.6 Replay safety
- All outbound writes happen **before** Interakt API call (state = `PENDING_SEND`); the response transitions it to `SENT` or `FAILED`. A crash mid-call leaves a `PENDING_SEND` row → janitor reconciles by checking Interakt or by re-sending using the same `idempotency_key` (which Interakt won't dedupe, so we accept a 1-in-a-million potential duplicate; alternative is to require manual reconciliation — simpler).

### 11.7 Two-workers-same-user safeguard
The Redis lock + the DB `version` column means even if two workers somehow get the same session, only one commit wins; the other retries from a fresh state read.

---

## 12. Database Design

### 12.1 Conventions
- Schema name: `wabot`.
- Primary keys: `id UUID DEFAULT gen_random_uuid()` (built into Postgres 13+ via `pgcrypto`). UUIDv7 is **not** required for the 15-day build; we can revisit later if index bloat becomes visible.
- All tables also have:
  - `created_at TIMESTAMPTZ(6) NOT NULL DEFAULT clock_timestamp()`
  - `updated_at TIMESTAMPTZ(6) NOT NULL DEFAULT clock_timestamp()` (trigger updates on row update).
- **All temporal columns use `TIMESTAMPTZ(6)`** (microsecond precision) and use `clock_timestamp()` (real wall-clock, not transaction start) so concurrent transactions get distinguishable timestamps. This matches Interakt's 6-decimal precision and is essential for race-condition forensics.
- `full_phone_number VARCHAR(20)` everywhere (E.164 without `+`). Always indexed and unique on `doctor`.
- Enums modeled as native Postgres `ENUM`s for the hot ones (`journey_type`, state enums, `consent_status`, etc.).
- Soft-delete only where needed (`master_data` mirror); business tables hard-delete is forbidden — use status flags.

### 12.2 Core tables (logical model)

| Table | Purpose |
|---|---|
| `doctor` | **Owned master + canonical user record** (one per phone). Holds `is_profile_complete` flag. Loaded from client-supplied data via a one-shot import script; thereafter we own it. |
| `consent` | Latest consent snapshot per doctor + history table. |
| `whatsapp_onboarding_status` | Has the user been sent the consent template at least once. |
| `journey_state` | Active journey + state per doctor (1:1 with doctor). |
| `journey_state_history` | Append-only transition log. |
| `conversation_session` | Logical chat session for GenAI context. |
| `conversation_message` | Inbound + outbound messages, ordered. |
| `outbound_message` | Outbound dispatch attempts and lifecycle; carries `callback_data` for chain resolution. |
| `webhook_event_raw` | Raw Interakt payloads (replay log). |
| `genai_interaction` | Each GenAI request/response pair. |
| `registration_attempt` | Each parse attempt for a user with errors and retry counter. |
| `partial_profile_confirmation` | Captures the Yes/No partial-data confirmation event. |

> The v1 separate `master_data_doctor` mirror table is **removed** (per A4: we own the master directly).
> The v1 `outbound_idempotency` separate table is **removed** — the unique index on `outbound_message.idempotency_key` is sufficient.
> The v1 `webhook_event_dedupe` separate table is **removed** — the composite unique on `webhook_event_raw` is sufficient.

### 12.3 DDL (planning-grade — mirrored verbatim in `models.txt`)

```sql
CREATE SCHEMA IF NOT EXISTS wabot;
SET search_path TO wabot;

CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- for gen_random_uuid()

CREATE TYPE journey_type AS ENUM ('registration', 'registered');

CREATE TYPE registration_state AS ENUM (
    'REG_INITIATED',
    'AWAITING_FULL_DETAILS',
    'PARTIAL_CONFIRM_PENDING',
    'AWAITING_REMAINING_DETAILS',
    'AWAITING_CORRECTED_FULL',
    'REGISTRATION_COMPLETED',
    'ASSISTED_SUPPORT'
);

CREATE TYPE registered_state AS ENUM (
    'CONSENT_PENDING',
    'CONSENT_DECLINED',
    'CONSENT_ACCEPTED',
    'AWAITING_FREE_TEXT',
    'GENAI_PROCESSING',
    'AWAITING_ANSWER_BUTTON',
    'HOTLINE_TEMPLATE_SENT'
);

CREATE TYPE consent_status   AS ENUM ('PENDING', 'ACCEPTED', 'DECLINED');
CREATE TYPE message_direction AS ENUM ('INBOUND', 'OUTBOUND');
CREATE TYPE outbound_status  AS ENUM ('PENDING_SEND','SENT','DELIVERED','READ','FAILED','CLICKED');
CREATE TYPE outbound_kind    AS ENUM ('TEXT','BUTTONS','TEMPLATE');

-- ============ Doctor (we own this) ============
CREATE TABLE doctor (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_phone_number           VARCHAR(20) NOT NULL UNIQUE,   -- E.164 sans '+'
    first_name                  TEXT,
    last_name                   TEXT,
    speciality                  TEXT,                          -- e.g. Cardiology, Diabetes, Neurology, Radiology
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
CREATE INDEX idx_doctor_phone      ON doctor(full_phone_number);
CREATE INDEX idx_doctor_complete   ON doctor(is_profile_complete);
CREATE INDEX idx_doctor_speciality ON doctor(speciality);

-- ============ Consent (current + history) ============
CREATE TABLE consent (
    doctor_id            UUID PRIMARY KEY REFERENCES doctor(id) ON DELETE CASCADE,
    status               consent_status NOT NULL DEFAULT 'PENDING',
    accepted_at          TIMESTAMPTZ(6),
    declined_at          TIMESTAMPTZ(6),
    last_template_msg_id TEXT,
    updated_at           TIMESTAMPTZ(6) NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE consent_history (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doctor_id      UUID NOT NULL REFERENCES doctor(id) ON DELETE CASCADE,
    status         consent_status NOT NULL,
    occurred_at    TIMESTAMPTZ(6) NOT NULL DEFAULT clock_timestamp(),
    reason         TEXT,
    correlation_id UUID
);
CREATE INDEX idx_consent_history_doctor ON consent_history(doctor_id, occurred_at DESC);

-- ============ Onboarding ============
CREATE TABLE whatsapp_onboarding_status (
    doctor_id     UUID PRIMARY KEY REFERENCES doctor(id) ON DELETE CASCADE,
    is_onboarded  BOOLEAN NOT NULL DEFAULT FALSE,
    onboarded_at  TIMESTAMPTZ(6)
);

-- ============ Journey state ============
CREATE TABLE journey_state (
    doctor_id               UUID PRIMARY KEY REFERENCES doctor(id) ON DELETE CASCADE,
    journey                 journey_type NOT NULL,
    state_registration      registration_state,
    state_registered        registered_state,
    expected_input_kind     TEXT,                          -- 'BUTTON' | 'FREE_TEXT' | 'REGISTRATION_TEXT'
    expected_outbound_id    UUID,                          -- which outbound's reply we are awaiting (for chain check)
    retry_count             INT NOT NULL DEFAULT 0,
    context                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_event_received_at  TIMESTAMPTZ(6),
    last_processed_event_id TEXT,
    version                 INT NOT NULL DEFAULT 0,        -- optimistic locking
    updated_at              TIMESTAMPTZ(6) NOT NULL DEFAULT clock_timestamp(),
    CHECK (
       (journey='registration' AND state_registration IS NOT NULL AND state_registered IS NULL)
    OR (journey='registered'   AND state_registered   IS NOT NULL AND state_registration IS NULL)
    )
);
CREATE INDEX idx_journey_state_journey ON journey_state(journey);

CREATE TABLE journey_state_history (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doctor_id       UUID NOT NULL REFERENCES doctor(id) ON DELETE CASCADE,
    from_state      TEXT,
    to_state        TEXT NOT NULL,
    event_id        TEXT,
    correlation_id  UUID,
    occurred_at     TIMESTAMPTZ(6) NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX idx_jsh_doctor_time ON journey_state_history(doctor_id, occurred_at DESC);

-- ============ Conversations ============
CREATE TABLE conversation_session (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doctor_id        UUID NOT NULL REFERENCES doctor(id) ON DELETE CASCADE,
    started_at       TIMESTAMPTZ(6) NOT NULL DEFAULT clock_timestamp(),
    last_activity_at TIMESTAMPTZ(6) NOT NULL DEFAULT clock_timestamp(),
    ended_at         TIMESTAMPTZ(6)
);
CREATE INDEX idx_conv_doctor_active ON conversation_session(doctor_id) WHERE ended_at IS NULL;

CREATE TABLE conversation_message (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES conversation_session(id),
    doctor_id       UUID NOT NULL REFERENCES doctor(id),
    direction       message_direction NOT NULL,
    text            TEXT,
    payload         JSONB,                                 -- canonical or raw
    interakt_msg_id TEXT,
    callback_data   TEXT,                                  -- echo for outbound; null for inbound free-text
    correlation_id  UUID,
    created_at      TIMESTAMPTZ(6) NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX idx_conv_msg_session_time ON conversation_message(session_id, created_at);
CREATE INDEX idx_conv_msg_interakt ON conversation_message(interakt_msg_id);

-- ============ Outbound ============
CREATE TABLE outbound_message (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doctor_id           UUID NOT NULL REFERENCES doctor(id),
    kind                outbound_kind NOT NULL,
    template_name       TEXT,
    payload             JSONB NOT NULL,                    -- exact body sent to Interakt
    idempotency_key     TEXT NOT NULL UNIQUE,
    callback_data       TEXT NOT NULL,                     -- '{outbound_id}|{correlation_id}'
    interakt_message_id TEXT,                              -- returned by Interakt on accept
    state_when_sent     TEXT,                              -- snapshot of journey state for forensics
    status              outbound_status NOT NULL DEFAULT 'PENDING_SEND',
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
CREATE INDEX idx_outbound_doctor_time ON outbound_message(doctor_id, created_at DESC);
CREATE INDEX idx_outbound_status     ON outbound_message(status) WHERE status IN ('PENDING_SEND','FAILED');
CREATE INDEX idx_outbound_interakt   ON outbound_message(interakt_message_id);

-- ============ Webhooks ============
CREATE TABLE webhook_event_raw (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type           TEXT NOT NULL,
    interakt_message_id  TEXT,
    full_phone_number    VARCHAR(20),
    payload              JSONB NOT NULL,
    received_at          TIMESTAMPTZ(6) NOT NULL DEFAULT clock_timestamp(),
    processed_at         TIMESTAMPTZ(6),
    UNIQUE (event_type, interakt_message_id, (payload->'data'->'message'->>'message_status'))
);
CREATE INDEX idx_webhook_raw_phone   ON webhook_event_raw(full_phone_number, received_at DESC);
CREATE INDEX idx_webhook_unprocessed ON webhook_event_raw(received_at) WHERE processed_at IS NULL;

-- ============ GenAI ============
CREATE TABLE genai_interaction (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doctor_id       UUID NOT NULL REFERENCES doctor(id),
    session_id      UUID REFERENCES conversation_session(id),
    request         JSONB NOT NULL,
    response        JSONB,
    status          TEXT NOT NULL,                         -- OK | TIMEOUT | ERROR
    latency_ms      INT,
    correlation_id  UUID,
    created_at      TIMESTAMPTZ(6) NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX idx_genai_doctor_time ON genai_interaction(doctor_id, created_at DESC);

-- ============ Registration ============
CREATE TABLE registration_attempt (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doctor_id       UUID NOT NULL REFERENCES doctor(id),
    raw_text        TEXT NOT NULL,
    parsed          JSONB,
    is_valid        BOOLEAN NOT NULL,
    errors          JSONB,
    attempt_no      INT NOT NULL,
    created_at      TIMESTAMPTZ(6) NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX idx_reg_attempt_doctor ON registration_attempt(doctor_id, created_at DESC);

CREATE TABLE partial_profile_confirmation (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doctor_id       UUID NOT NULL REFERENCES doctor(id),
    presented_data  JSONB NOT NULL,
    confirmed       BOOLEAN,                                -- NULL = pending; TRUE/FALSE on response
    responded_at    TIMESTAMPTZ(6),
    created_at      TIMESTAMPTZ(6) NOT NULL DEFAULT clock_timestamp()
);
```

### 12.4 Indexing strategy
- All lookups by `full_phone_number` are indexed (unique on `doctor`).
- Partial index on `outbound_message(status) WHERE status IN ('PENDING_SEND','FAILED')` keeps janitor scans cheap.
- Partial index on `webhook_event_raw(received_at) WHERE processed_at IS NULL` enables O(log n) janitor.
- Future partitioning (when volume warrants):
  - `webhook_event_raw` by `received_at` monthly.
  - `outbound_message` and `conversation_message` by `created_at` monthly.

### 12.5 Naming conventions
- Tables: `snake_case_singular` (`doctor`, `conversation_message`).
- Indexes: `idx_<table>_<cols>`.
- Foreign keys: `fk_<from_table>_<to_table>`.
- Enums: `lowercase_singular`.

---

## 13. Redis Usage Plan

Redis is used aggressively to **keep the hot path off Postgres** for user identification and routing. The `doctor` table is still the source of truth, but every inbound event under steady state should resolve the user purely from Redis.

### 13.1 What goes in Redis
| Purpose | Key pattern | Type | TTL |
|---|---|---|---|
| Per-user lock (orchestrator) | `lock:user:{full_phone}` | string (NX PX) | 30s, watchdog-refreshed every 10s |
| Webhook dedupe (defensive, before DB unique check) | `dedupe:wh:{event_type}:{interakt_msg_id}:{status}` | string | 10m |
| **User resolution snapshot** (used by free-text router) | `user:{full_phone}` | hash | none — write-through, invalidated on write |
| Journey snapshot (for fast "is this the expected reply?" check) | `journey:{full_phone}` | hash | none — write-through |
| Outbound chain lookup (callbackData resolution) | `outbound:{outbound_message_id}` | hash (`doctor_id`,`kind`,`state_when_sent`,`sent_at_iso`) | 7 days |
| Outbound rate limiter | `interakt:bucket:{minute_epoch}` | counter | 70s |
| Idempotency (already-processed events) | `event:processed:{interakt_msg_id}` | string | 24h |
| GenAI in-flight guard | `genai:inflight:{doctor_id}` | string | 60s |

### 13.2 `user:{full_phone}` snapshot fields
Write-through hash, populated whenever a doctor is created/updated and whenever consent or onboarding flags change:
```
doctor_id              : UUID
is_profile_complete    : 0|1
is_onboarded           : 0|1
consent_status         : PENDING|ACCEPTED|DECLINED
active_journey         : registration|registered
active_state           : <enum>
expected_input_kind    : BUTTON|FREE_TEXT|REGISTRATION_TEXT
journey_version        : int (matches DB optimistic-lock version)
updated_at             : ISO-8601 microsecond UTC
```
The free-text router reads this hash in **a single Redis HGETALL** to decide which journey case (A/B/C/D) applies — **zero DB calls on the steady-state hot path**. On miss, it falls back to a DB read and immediately backfills Redis.

### 13.3 Never-only-in-Redis rules
- Consent, journey state, doctor profile, message logs, registration attempts — **DB is truth**. Redis snapshots are write-through caches keyed by the DB `version` column.
- On any inbound event that mutates state, the orchestrator: (1) acquires the per-user lock, (2) reads `journey_state` from DB **once** to confirm `version` matches the cached snapshot, (3) mutates DB inside a transaction with `WHERE version = :v`, (4) on commit, refreshes both `user:{...}` and `journey:{...}` hashes (within the lock).
- If the DB and cache disagree on `version`, the cache is invalidated and the DB row wins.

### 13.4 Cache invalidation
- Write-through inside the per-user lock — no inconsistency window across reads/writes for the same user.
- A simple `cache_warm_doctor(phone)` helper is reused on first-touch and on profile updates.

### 13.5 Locks
- `redis.asyncio.lock.Lock` with token-based ownership; renewal task started by orchestrator and torn down on completion. Lock TTL=30s, refreshed every 10s while the handler runs.

### 13.6 Streams
- Used as the local broker (see §10).

---

## 14. GenAI Integration Contract

### 14.1 Endpoint
- `POST {GENAI_BASE_URL}/v1/chat/answer`
- Auth: `Authorization: Bearer {GENAI_API_KEY}`.
- Headers: `X-Correlation-Id`, `X-Doctor-Id`, `X-Conversation-Id`.

### 14.2 Request
```json
{
  "schema_version": "1.0",
  "doctor_id": "uuid",
  "conversation_id": "uuid",
  "journey": "registered",
  "current_state": "AWAITING_FREE_TEXT",
  "user_message": "string",
  "recent_turns": [
    { "role": "user|bot", "text": "string", "timestamp": "iso8601" }
  ],
  "summary_context": "string",
  "channel": "whatsapp",
  "locale": "en"
}
```

### 14.3 Response
```json
{
  "schema_version": "1.0",
  "success": true,
  "intent": "answer | hotline | fallback",
  "query_nature": "non_scientific | scientific",
  "response_type": "text | template",
  "answer_text": "string",
  "app_link": "string|null",
  "template_name": "string|null",
  "flags": {
    "send_processing_message": false,
    "end_session": false,
    "requires_hotline": false,
    "requires_template": false,
    "show_answer_buttons": false,
    "use_rag": false
  },
  "meta": {
    "confidence": 0.0,
    "reason": "string",
    "trace_id": "string",
    "model_version": "string"
  }
}
```

### 14.4 Behavior rules
- `query_nature=non_scientific` → orchestrator sends a single Text session message with `answer_text`. No buttons.
- `query_nature=scientific` → orchestrator first sends the processing ack (when `flags.send_processing_message=true`), then a single InteractiveButton session message with `answer_text` + buttons `Satisfied`, `Call hotline`. If `app_link` is non-null, append `\n\n{app_link}` to `answer_text` (builder concern).
- `intent=hotline` → send the `hotline_v1` template directly.
- `intent=fallback` → send Fallback 3 copy.

### 14.5 Resilience
- **GenAI is async HTTP** — we call it with `httpx.AsyncClient.post(...)` + `await` from the worker. The webhook hot path never awaits GenAI; only the orchestrator worker does, after the `Let me check that for you…` ack has already been dispatched. Frontend message latency is therefore decoupled from GenAI latency.
- Timeouts: 2s connect, 20s read.
- Retries: **exponential backoff with jitter** — 1 retry on 5xx/timeout (`min(2^n * 0.5s, 4s)` ± 20%). Treated as idempotent for the same `(conversation_id, user_message_hash)`.
- Circuit breaker: open after 5 consecutive failures in 60s; half-open after 30s.
- On open circuit or final failure → orchestrator emits Fallback 3 and reverts journey state to `AWAITING_FREE_TEXT` so the user can retry.

### 14.6 Versioning
- `schema_version` on both ends. Server must reject unknown major versions. Adapter pins a `min_supported` and `max_supported` range; mismatch → fallback.

---

## 15. Environment Variable / Config Strategy

`.env.example` will ship grouped variables. Loaded via `pydantic-settings`. **No secret in code.**

```env
# === App ===
APP_NAME=wabot
APP_ENV=local                       # local|dev|staging|prod
APP_LOG_LEVEL=INFO
APP_LOG_JSON=true
APP_HTTP_PORT=8000
APP_REQUEST_TIMEOUT_SECONDS=30
APP_FEATURE_FLAG_DRY_RUN_OUTBOUND=false

# === DB (Azure PostgreSQL Flex — components, not URL, so password is never embedded in a string) ===
DB_HOST=docbotdatabase.postgres.database.azure.com
DB_PORT=5432
DB_USER=drbot_admin
DB_PASSWORD=
DB_NAME=postgres                    # change if Azure DB name differs
DB_SCHEMA=wabot
DB_SSL_MODE=require                 # Azure PG requires SSL
DB_POOL_SIZE=20
DB_POOL_MAX_OVERFLOW=20
DB_STATEMENT_TIMEOUT_MS=15000

# === Redis ===
REDIS_URL=redis://localhost:6379/0
REDIS_LOCK_TTL_SECONDS=30
REDIS_DEDUPE_TTL_SECONDS=600

# === Interakt ===
INTERAKT_BASE_URL=https://api.interakt.ai
INTERAKT_API_KEY=base64-encoded-key
INTERAKT_TIMEOUT_CONNECT_SECONDS=5
INTERAKT_TIMEOUT_READ_SECONDS=10
INTERAKT_RATE_LIMIT_RPS=80
INTERAKT_WEBHOOK_PATH_SECRET=change-me
INTERAKT_ALLOWED_CIDRS=0.0.0.0/0     # tighten for prod

# === Templates / catalog ===
TEMPLATE_DOCTOR_WELCOME_CONSENT=doctor_welcome_consent_v1
TEMPLATE_HOTLINE=hotline_v1
TEMPLATE_LOCALE=en
# template_category is intentionally NOT used in v2 (only 2 templates today)
SUPPORT_CONTACT_VALUE=+91-XXXXXXXXXX

# === GenAI ===
GENAI_BASE_URL=https://genai.example.local
GENAI_API_KEY=...
GENAI_TIMEOUT_CONNECT_SECONDS=2
GENAI_TIMEOUT_READ_SECONDS=20
GENAI_RECENT_TURNS_LIMIT=5
GENAI_CIRCUIT_BREAKER_FAILS=5
GENAI_CIRCUIT_BREAKER_WINDOW_SECONDS=60

# === Broker ===
BROKER_DRIVER=redis_streams          # redis_streams|azure_servicebus|in_memory
BROKER_INBOUND_TOPIC=inbound.user-events
BROKER_STATUS_TOPIC=outbound.delivery-status
BROKER_RETRY_TOPIC=outbound.send-retry
BROKER_GROUP_INBOUND=inbound-workers
BROKER_MAX_DELIVERY_COUNT=5
BROKER_VISIBILITY_TIMEOUT_SECONDS=60
AZURE_SERVICEBUS_CONNECTION_STRING=

# === Workers ===
INBOUND_WORKER_CONCURRENCY=8
STATUS_WORKER_CONCURRENCY=4
WORKER_GRACEFUL_SHUTDOWN_SECONDS=20

# === Behavior ===
REGISTRATION_MAX_RETRIES=2
# No session/idle timeout: WhatsApp users may reply at any time.
# No consent re-entry cooldown: next inbound after decline triggers consent template again.

# === Observability ===
OTEL_ENABLED=false
OTEL_EXPORTER_OTLP_ENDPOINT=
METRICS_ENABLED=true
```

---

## 16. Local Development Plan

### 16.1 What runs locally
- **App container** (FastAPI, role=api).
- **Worker container** (same image, role=worker).
- **Redis** container (compose).
- **PostgreSQL**: client's Azure Postgres via DBeaver — **do not** run a local Postgres unless the dev is offline. The compose file ships an *optional* `postgres` profile (`docker compose --profile local-db up`) for offline work; default profile uses the `DB_*` component env vars from `.env` to build the asyncpg DSN at app startup (host: `docbotdatabase.postgres.database.azure.com`, user: `drbot_admin`, schema: `wabot`, SSL: required).
- **Optional**: RabbitMQ container via `--profile rabbit` for stress/queue experiments.

### 16.2 docker-compose (sketch)
- Services: `api`, `worker`, `redis`, optional `rabbitmq`, optional `postgres`.
- Health checks on all.
- A `tools` service that runs migrations: `docker compose run --rm tools alembic upgrade head`.

### 16.3 Webhook testing
- **Thunder Client** (VS Code extension) collection in `scripts/thunderclient/wabot.thunder-collection.json` — pre-populated requests using sample payloads from `interakt_webhook.md`. Postman is blocked on the dev's machine.
- For Interakt to actually reach a local instance, **ngrok** or **cloudflared tunnel** is documented in README. Until then, replay via Thunder Client is sufficient.
- `scripts/send_test_webhook.py` POSTs the fixtures from `tests/fixtures/interakt_webhooks/` for fast smoke tests.

### 16.4 Seed data
- `scripts/seed_dev_data.py` inserts directly into our `doctor` table:
  - One fully-registered doctor (`is_profile_complete=true`, all fields filled).
  - One partial doctor (`is_profile_complete=false`, missing email/pincode).
  - One unknown phone (no `doctor` row at all) — used to drive the new-user path.

### 16.5 Local queue
- `BROKER_DRIVER=redis_streams` is default — no extra service needed.

---

## 17. Testing Strategy

### 17.1 Layers
- **Unit** — pure parsers, message builder, validators, state-transition functions. Property-based tests (via `hypothesis`) for the registration parser.
- **Integration** — repos against a real Postgres (testcontainers); broker against a real Redis (testcontainers); journey handlers driven by canonical events.
- **API** — FastAPI `httpx.AsyncClient` end-to-end through `/webhooks/interakt`, including dedupe and ack-time SLA.
- **Contract** — pinned JSON fixtures from `interakt_webhook.md` go through the normalizer and assert against canonical schemas; pinned GenAI request/response fixtures.
- **State-machine** — table-driven tests: `(state, event_kind) → next_state`. This catches missed transitions.
- **Concurrency / ordering** — fire 100 events for the same phone in parallel; assert journey state is one valid linear path.
- **Idempotency** — replay same webhook 10 times; assert exactly one outbound row, one state transition.
- **Migrations** — `alembic upgrade head && downgrade base && upgrade head` in CI to catch drift.
- **Load** — `locust` script that ramps inbound webhooks; checks ack P95 < 100ms and worker throughput.

### 17.2 Mocks
- GenAI mocked via `respx` with fixture responses.
- Interakt outbound mocked via `respx` returning `{result:true, id:"..."}`.

---

## 18. Observability / Monitoring / Logging

### 18.1 Logging
- **structlog** JSON logs, fields always include: `correlation_id`, `doctor_id`, `phone_e164` (hashed in prod), `journey`, `state`, `event_kind`, `interakt_message_id`.
- Webhook bodies are logged with sensitive fields **redacted** (auth header, callback_data > 200 chars, full text bodies behind `LOG_PII=false`).

### 18.2 Correlation
- HTTP middleware reads/creates `X-Correlation-Id`, binds to structlog context.
- Queue messages carry the correlation id in headers — workers re-bind on consume.

### 18.3 Metrics (Prometheus-compatible)
- Counters: `webhook_received_total{type}`, `webhook_dedupe_drop_total`, `outbound_sent_total{kind,status}`, `genai_calls_total{outcome}`.
- Histograms: `webhook_ack_seconds`, `worker_handle_seconds{journey,state}`, `genai_latency_seconds`, `interakt_send_latency_seconds`.
- Gauges: `queue_lag_messages`, `inbound_lock_holders`.

### 18.4 Audit
- Every state change → `journey_state_history` row.
- Every consent change → `consent_history` row.
- Every outbound and inbound → message tables.

### 18.5 Azure-readiness
- OTel tracing wired but disabled locally (`OTEL_ENABLED=false`). Toggle on for Azure Monitor with the Azure Monitor exporter.
- App Service / AKS app insights exporter is a single env-var change.

---

## 19. Security / Compliance

### 19.1 Secrets
- Never in code; only env. Local dev uses `.env` (git-ignored). Cloud uses Key Vault references.
- API keys redacted in any logs.

### 19.2 PII
- Phone number is PII — hash (`sha256(phone+salt)`) for analytics/log fields when `LOG_PII=false`.
- Email/address only in DB; never in metrics or logs.
- Conversation content excluded from default logs; admins access via `/admin` endpoints with RBAC.

### 19.3 Webhook security
- Path secret + IP allowlist today.
- HMAC verification scaffolded; switch on once Interakt confirms support.
- Reject payloads > 256 KB or with content-type other than `application/json`.

### 19.4 DB access
- App user has only `SELECT, INSERT, UPDATE` on its tables; `DELETE` revoked except for housekeeping role.
- TLS-required connection.

### 19.5 Outbound dependencies
- httpx with strict TLS, certs verified, no `verify=False`.

### 19.6 OWASP top 10 hygiene
- All inputs validated by Pydantic.
- SQL via parametrized SQLAlchemy (no string interpolation).
- Rate limiting at webhook ingress (per-IP token bucket) + at outbound (per-account).
- CORS disabled for webhook route.
- Admin endpoints require `X-Admin-Token` env-defined; behind network ACL in prod.

---

## 20. Risks, Weaknesses, and Recommended Improvements (v2)

| # | Issue | Impact | Recommended fix | When |
|---|---|---|---|---|
| R1 | Context §5.6 says "session text + button". Native session text doesn't carry buttons; Interakt requires `InteractiveButton` for that. | Wrong message shape; runtime errors. | Use `InteractiveButton` for any session message that needs buttons. | Now |
| R2 | Profile completeness was defined on a separate master mirror table in v1. | Cross-system consistency drift. | **Resolved in v2**: completeness flag (`is_profile_complete`) lives directly on the owned `doctor` table; one-shot import populates it. | Done |
| R3 | v1 imposed a session idle timeout. | Blocks valid late replies on an open-ended channel. | **Resolved in v2**: removed entirely (\u00a77.5). | Done |
| R4 | Two events from the same user racing through the worker. | State corruption. | Per-user FIFO (Service Bus sessions / partitioned Redis Streams) + per-user Redis lock + DB optimistic-version. Documented in \u00a710\u2013\u00a711. | Now |
| R5 | Consent re-entry cooldown felt ill-defined. | Spam vs UX trade-off. | **Resolved in v2**: removed cooldown entirely; next inbound after decline triggers consent again (per context). | Done |
| R6 | Free-text router latency (DB lookup on every inbound). | Latency spikes. | **Resolved in v2**: write-through `user:{full_phone}` Redis hash means steady-state hot path is zero DB calls (\u00a713). | Done |
| R7 | Interakt outbound has no native idempotency. | Possible duplicates on retry. | Pre-write `outbound_message` with unique `idempotency_key`; retry only on connection-level failures with no `interakt_message_id` returned. | Now |
| R8 | GenAI failure could trap users in `GENAI_PROCESSING`. | Stuck users. | Hard timeout, exponential backoff with jitter, circuit breaker; on failure emit Fallback 3 and revert state to `AWAITING_FREE_TEXT`. | Now |
| R9 | Registration retry counter has no time bound. | Edge: long-spread retries permanently lock the user. | Counter resets only on a successful parse or on explicit `ASSISTED_SUPPORT` clear. Acceptable given 2-strike rule + hotline path. | Accepted |
| R10 | Partial-data confirmation copy could literalize missing placeholders. | UX bug. | Builder skips lines whose value is empty; if no available fields, fall back to "no data found" path. | Now |
| R11 | Free text while `expected_input_kind=BUTTON`. | Ambiguity. | Per \u00a711.5: post-scientific-answer treats free text as next query (loop continues); for consent and partial-confirm steps, send Fallback 1. | Now |
| R12 | Stale historical button click (user scrolls up days later). | Could mutate state incorrectly. | **Resolved in v2** via `callbackData` chain check (\u00a77.8): clicks that resolve to an `outbound_message_id` older than the latest forward action are no-ops. | Done |
| R13 | Template name registry not validated at send time. | Typo causes 4xx. | Two templates only \u2014 names live in env. Add a validation feature flag later if templates grow. | Later |
| R14 | v1 planned to expire conversation sessions after 7d. | Conflicts with "no expiry" rule. | **Resolved in v2**: conversation sessions never auto-close; janitor only trims very old rows for storage hygiene (>180d), not for behavior. | Done |
| R15 | Replay safety on outbound has a tiny duplicate window (network failure after Interakt accepted). | Rare duplicate. | Acceptable for v1 launch; documented. | Accepted |
| R16 | Phone-number normalization ownership. | Mismatched lookups. | Normalize once at the webhook boundary (`fullPhoneNumber`, digits only). | Now |
| R17 | Hotline CTA payload was unclear in v1. | False alarm. | **Resolved in v2** (per A8): `hotline_v1` only takes doctor name as `bodyValues[0]`; `Call` CTA is pre-configured in Interakt and needs no `buttonValues` from us. | Done |
| R18 | No dedicated path for STOP/UNSUBSCRIBE keywords. | Regulatory risk. | Treat configured keywords at router level \u2192 set `consent.status=DECLINED`, send acknowledgement. | Now |
| R19 | `flowchart.txt` may drift from `context_final.md`. | Doc confusion. | Treat `context_final.md` as authoritative; diff and reconcile before go-live. | Later |
| R20 *(new v2)* | Webhook auth currently shared-secret-in-URL only. | Possible spoof if URL leaks. | Acceptable for v1 (per user direction). Revisit HMAC if Interakt adds support after launch. | Later |
| R21 *(new v2)* | `clock_timestamp()` vs `now()` matters for race ordering. | Two updates inside one transaction would otherwise share a timestamp. | All temporal columns default to `clock_timestamp()` and use `TIMESTAMPTZ(6)`. Application also writes `datetime.now(UTC)` with microseconds. | Done |
| R22 *(new v2)* | `callbackData` is single-string; collisions possible if devs forget to set it. | Chain-of-context resolution fails silently. | Outbound dispatcher **enforces** non-empty `callback_data = "{outbound_id}|{correlation_id}"` at the adapter boundary; reject sends without it. | Now |

---

## 21. Final Recommended Build Order

### What to build first (the "vertical slice")
1. **Phase 0–2** (skeleton, config, DB).
2. **Webhook ingestion** (Phase 3) end-to-end with raw persistence and dedupe.
3. **Outbound text send** (Phase 6 partial: `Text` only) so we can observe both sides.
4. **Free-text router → user_registration (new user path)**: simplest journey, exercises every layer (router, journey, parser, repo, outbound).
5. **Consent template send + accept/decline** in registered-user journey.
6. **GenAI integration** with mocked responses, then real.
7. **Status webhook consumer** and outbound lifecycle.
8. **Partial-data path** in registration.
9. **Hotline + scientific answer flow**.
10. **Janitors / DLQ / admin endpoints**.
11. **Observability hardening + load test**.
12. **Azure-deployment doc & migration**.

### Files to create first (in order)
1. `pyproject.toml`, `Dockerfile`, `docker-compose.yml`, `.env.example`.
2. `src/wabot/main.py`, `infra/config.py`, `infra/logging.py`, `infra/correlation.py`.
3. `data/db.py`, `data/base.py`, `migrations/env.py`, `migrations/versions/0001_init.py` (full schema from §12).
4. `api/routers/health.py`, `api/routers/webhooks.py`.
5. `api/schemas/interakt_webhook.py`, `adapters/interakt/normalizer.py`.
6. `cache/client.py`, `cache/locks.py`, `cache/dedupe.py`.
7. `adapters/broker/base.py`, `adapters/broker/redis_streams.py`.
8. `services/orchestrator.py`, `domain/router.py`, `domain/enums.py`, `domain/events.py`.
9. `domain/journeys/base.py`, `domain/journeys/registration.py`.
10. `domain/messages/catalog.py`, `domain/messages/builder.py`.
11. `adapters/interakt/client.py`, `services/outbound_pipeline.py`.
12. `domain/journeys/registered.py`, `domain/consent.py`.
13. `adapters/genai/client.py`, `adapters/genai/schemas.py`.
14. `workers/inbound_worker.py`, `workers/status_worker.py`.
15. Tests, fixtures, scripts, Thunder Client collection.

### What to defer
- Azure Service Bus adapter implementation (port and contracts now; impl when subscription is available).
- Azure Monitor / App Insights integration (OTel scaffolding only).
- Template registry validation feature flag.
- Multi-language locale support beyond `en`.
- HMAC webhook verification (revisit post-launch, only if Interakt adds it).

### What to mock initially
- GenAI responses (use `respx` with realistic fixtures including both `non_scientific` and `scientific` shapes).
- Interakt outbound (in unit/integration tests).
- Doctor table seed via `scripts/seed_dev_data.py`.

---

## 22. Revision Log

### v2.1 — client update (registration form changes)
- **Registration form now has 7 fields** (was 6). Added `Speciality` (e.g., Cardiology, Diabetes, Neurology, Radiology) between `Full Name` and `Address`.
- **Delimiter changed from newline → `#`** for all registration prompts and the parser. Single-line input, tokens trimmed.
- **`Full Name` is split on first whitespace** into `first_name` and `last_name` at parse time.
- **Schema change** (`models.txt` + §12.3): `doctor.full_name` removed; replaced with `doctor.first_name`, `doctor.last_name`, and `doctor.speciality`. New index `idx_doctor_speciality`.
- **Updated copy** in `context_final.md` §6.6, §6.7, §6.8, §6.9, §6.11. Partial-confirm message now includes a `Speciality:` row.
- **Parser contract** documented in Phase 7 of this plan.

### v2 (post architecture review) \u2014 changes vs v1
- **A4 corrected**: we own the master user table directly. Removed `master_data_doctor`. `doctor.is_profile_complete` is the source of completeness.
- **A6 corrected**: GenAI exposes async HTTP endpoints. Documented isolation between webhook hot path and worker await.
- **A7, A8, A9 added**: `callbackData` round-trip; `hotline_v1` body-only; `template_category` omitted.
- **No session/idle timeout**: removed `SESSION_IDLE_TIMEOUT_SECONDS` and consent re-entry cooldown env vars and the corresponding behavior. WhatsApp is open-ended.
- **`fullPhoneNumber` everywhere**: every outbound payload uses the single field; never `countryCode + phoneNumber`. All schema columns renamed to `full_phone_number`.
- **Timestamps**: every `TIMESTAMPTZ` upgraded to `TIMESTAMPTZ(6)` with `clock_timestamp()` default; canonical events and Python objects use microsecond UTC.
- **Redis-first user resolution**: introduced `user:{full_phone}` write-through hash so the steady-state hot path issues zero DB calls for routing decisions; `outbound:{outbound_message_id}` cache for callback-data resolution.
- **`callbackData` chain-of-context**: outbound dispatcher always sets `callback_data = "{outbound_id}|{correlation_id}"`; orchestrator uses it to detect stale historical button clicks safely without a time window.
- **Webhook auth simplified**: shared-secret URL only; no IP allowlist / HMAC complexity in v1.
- **DDL consolidated**: removed `master_data_doctor`, `webhook_event_dedupe`, `outbound_idempotency`, `feature_flags` tables. Added `outbound_message.callback_data`, `outbound_message.state_when_sent`, `journey_state.expected_outbound_id`, `conversation_message.callback_data`.
- **Tooling**: Thunder Client replaces Postman for local API testing.\n- **UUIDs**: switched to `gen_random_uuid()` (built-in) to avoid the `pg_uuidv7` extension dependency for the 15-day timeline.\n- **Retries**: standardized on **exponential backoff with jitter** via `tenacity` for both Interakt outbound and GenAI client.\n- **STOP/UNSUBSCRIBE**: added explicit handling at the router level (R18).\n- **Companion files**: `models.txt` and `claude_memory.md` introduced.\n\n---\n\n> **End of plan (v2).** Code generation should now proceed module-by-module against this document, beginning at Phase 0 and not skipping ahead past the dependency chain in \u00a76. Update `claude_memory.md` after every meaningful checkpoint.
