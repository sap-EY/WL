# Memory — Wockhardt WhatsApp Bot

> Living tracker for the build. Update after every meaningful code change or architectural decision.

---

## 0. Current Status

| Phase | Title | Status | Notes |
|------:|-------|--------|-------|
| 0 | Repository bootstrap | Done | FastAPI app, tooling, Docker, compose, health smoke tests. |
| 1 | Config, logging, correlation | Done | Pydantic settings, structlog JSON, `X-Correlation-Id`, stable error envelope. |
| 2 | DB models + Alembic | Done | Async SQLAlchemy models for the `wabot` schema, Alembic, seed scripts, `/readyz` DB probe. |
| 3 | Interakt webhook ingestion | Done | `POST /webhooks/{secret}/interakt`, raw event persistence, Redis dedupe, Redis Streams enqueue. |
| 4 | Webhook normalizer | Done | Interakt payloads normalize into `CanonicalInboundEvent`, including Flow replies and callback data. |
| 5 | Orchestrator + lock + router | Done | Worker consumes broker messages, takes per-user Redis lock, routes Cases A-D, persists journey state. |
| 6 | Outbound dispatcher + Interakt adapter | Done | `OutboundIntent`, message catalog/builders, Interakt client, outbound idempotency, callback chain. |
| 7 | User registration journey | Done | WhatsApp Flow form via `user_registration_v1`; stores first/last name, MCI-ID, speciality; completion immediately emits consent template. |
| 8 | Registered users journey | Done | Consent accept/decline, ice-breaker, GenAI port seam, scientific/non-scientific answer shaping, hotline path. |
| 9 | GenAI gateway | Blocked | GenAI team APIs are not available yet; real adapter remains intentionally unimplemented. |
| 10 | Status webhook consumer | Done | Status/click webhooks route to a dedicated status queue and worker; handler applies lifecycle updates to `outbound_message`. |
| 11 | Observability | Done | `/metrics`, operational counters, structured queue/status fields, and optional Azure Monitor bootstrap. |
| 12 | Test harness expansion | Not started | Integration/contract/load tests. |
| 13 | Azure deployment readiness | In progress | Azure Service Bus broker adapter and queue env shape implemented; deployment scripts/resource provisioning still pending. |

Current validation: **175 unit tests green**, `ruff check .` clean, and `mypy src` clean after Phase 10/11/Azure queue edits.

---

## 1. Immediate Next Actions

1. Keep Phase 9 blocked until the GenAI team provides the real API contract.
2. Provision Azure Service Bus queues with sessions enabled for `wabot-inbound`, `wabot-status`, `wabot-genai`, and `wabot-outbound` before cloud cutover.
3. For Azure deployment, the public webhook URL will be the Azure App Service HTTPS hostname plus the existing route: `https://<app-name>.azurewebsites.net/webhooks/<INTERAKT_WEBHOOK_PATH_SECRET>/interakt`.
4. No local public tunneling flow is part of this project. Local journey testing remains simulation-based via `scripts/drive_webhook.py` and unit tests.

---

## 2. Locked Decisions

- The app will be deployed and publicly reached through **Azure App Service for Containers**. There is no external managed gateway assumption.
- Interakt webhook configuration should point directly to the App Service HTTPS URL: `https://<app-name>.azurewebsites.net/webhooks/<secret>/interakt`.
- Webhook auth remains `INTERAKT_WEBHOOK_PATH_SECRET` in the URL path for v1. Interakt calls the endpoint; `webhooks.py` validates the path secret using a constant-time comparison and returns 404 for wrong secrets.
- No local public tunneling flow is part of the project.
- Azure Service Bus production queues should use **sessions keyed by `full_phone_number`** wherever per-user ordering matters.
- Recommended queue plan:
  - `inbound_webhook_queue` — implemented; receives user message and Flow response references from the FastAPI ingress path.
  - `status_webhook_queue` — implemented; receives Interakt lifecycle events (`message_api_sent/delivered/read/failed/clicked`) and updates `outbound_message`.
  - `genai_processing_queue` — configured/reserved for future isolation once GenAI APIs exist; not consumed today.
  - `outbound_message_queue` — configured/reserved for future independent Interakt send workers; current code sends outbound messages inline after journey commit.
  - Retry handling should prefer Azure Service Bus scheduled delivery/retry policies and per-queue DLQs. A separate `retry_queue` is optional for advanced replay workflows, not mandatory on day one.
  - A separate `dead_letter` / `poison_queue` is usually unnecessary because Azure Service Bus has a built-in DLQ for each queue. Use a manual `poison_queue` only if operations needs one cross-queue triage surface.
- No session/idle timeout. WhatsApp conversations can resume hours or days later.
- `fullPhoneNumber` is the only Interakt phone field used; never split into `countryCode + phoneNumber`.
- `callbackData = "{outbound_message_id}|{correlation_id}"` is mandatory on outbound sends.
- `template_category` is omitted from Interakt template sends.
- Registration uses WhatsApp Flow form `user_registration_v1` for new/unregistered doctors. Known doctors route to the registered-user journey; there is no partial-profile branch in code.
- Tests, ruff, black, mypy strict, and bandit must stay clean.

---

## 3. Current Code Reality

- `src/wabot/api/routers/webhooks.py` is the public Interakt webhook endpoint. It persists the raw event, dedupes, routes user events to `inbound`, routes status/click events to `status`, and returns quickly.
- `src/wabot/adapters/broker/base.py` defines logical broker queues: `inbound`, `status`, `genai`, and `outbound`.
- `src/wabot/adapters/broker/redis_streams.py` maps logical queues to Redis Streams for local/dev.
- `src/wabot/adapters/broker/azure_servicebus.py` maps logical queues to Azure Service Bus queues and uses sessions for per-phone ordering.
- `src/wabot/workers/inbound_worker.py` consumes inbound user events; `src/wabot/workers/status_worker.py` consumes status lifecycle events.
- GenAI and outbound Interakt sends currently happen inside the worker flow, not via separate workers.

---

## 4. Open Questions

| # | Question | Owner | Blocker? |
|---|---|---|---|
| Q1 | Final hotline phone number(s) for `hotline_v1`; currently expected to be configured inside Interakt template. | User/team | No |
| Q2 | Final STOP/UNSUBSCRIBE keyword list. | User/team | No |
| Q3 | Exact GenAI base URL and auth token for local/dev/prod. | GenAI team | Phase 9 |
| Q4 | Azure resource names: App Service name, ACR name, Service Bus namespace, Redis name, resource group, region. | Platform/team | Phase 13 |
| Q5 | Client doctor import file format and final columns. | User/team | Before go-live |

---

## 5. Progress Log

### 2026-05-18 — Partial registration branch removed from code/schema
- Removed obsolete partial-registration router branch, enum states, message catalog symbols, ORM model, and seed helper mode.
- Updated `models.txt`, Alembic migration baseline, and added migration/SQL cleanup scripts for existing databases.
- Kept active registration resumption based on `journey_state`, so new users with shell doctor rows can still submit the WhatsApp Flow form safely.

### 2026-05-18 — Phase 10/11 and Azure queue readiness
- Added logical broker queues and wired Redis Streams plus Azure Service Bus adapter support.
- Split webhook ingress into `inbound` and `status` queues; added the `status-worker` role.
- Implemented outbound status lifecycle updates for sent/delivered/read/failed/clicked events.
- Added `/metrics`, operational counters, and optional Azure Monitor bootstrap.
- Left Phase 9 real GenAI adapter blocked until the GenAI team provides API details.
- Validated with 175 passing unit tests, clean Ruff lint, and clean mypy strict typing.

### 2026-05-18 — Documentation aligned for Azure deployment
- Renamed the living tracker to `memory.md`.
- Removed stale external gateway and local public tunneling assumptions.
- Locked the webhook deployment model: Interakt calls Azure App Service HTTPS directly at `/webhooks/{secret}/interakt`.
- Clarified queue topology: only inbound queue exists in code today; target Azure architecture should add GenAI/outbound/status processing queues as later phases require.
- Added `azure.md` as the concise Azure services and webhook reference.

### 2026-05-11 — Phase 8 complete
- Registered-user journey implemented: consent, declined re-entry, ice-breaker, GenAI port seam, scientific answer buttons, hotline template path.

### 2026-05-10 — Phase 7 revised
- Registration pivoted to WhatsApp Flow form `user_registration_v1` with `mci_id` support and immediate consent-template transition after successful form submission.
