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
| 3    | Interakt webhook ingestion                       | ✅ Done | Shared-secret URL handler, two-layer dedupe (Redis SET NX EX + DB partial unique index), Redis Streams broker port, /readyz now probes Redis too |
| 4    | Webhook normalizer + canonical event             | ✅ Done | `CanonicalInboundEvent` (frozen, extra=forbid) + Interakt normalizer; pure, deterministic; 14 unit tests covering all 6 event variants, QR/CTA click discrimination, callback chain |
| 5    | Orchestrator + per-user lock + free-text router  | ✅ Done | `UserLock` (SET NX PX + watchdog + Lua release), Redis Streams consume API (XREADGROUP/XACK/ensure_consumer_group), pure router (Cases A–D), Orchestrator end-to-end pipeline, NoopJourney + NoopOutboundStatus handlers as defaults; 29 new unit tests (90 total) |
| 6    | Outbound dispatcher + Interakt adapter           | ✅ Done | `OutboundIntent` + `InteractiveButton` (frozen pydantic); message catalog + pure builders; `InteraktClient` (httpx async + tenacity exp-jitter retry on 5xx/network, immediate fail on 4xx, optional Redis token-bucket rate guard); `OutboundPipeline` (deterministic `idempotency_key` → `create_pending` → `callbackData = {row.id}|{correlation_id}` → send → `mark_sent` / FAILED); orchestrator dispatches intents post-commit under user lock; 32 new unit tests (122 total) |
| 7    | User registration journey engine                 | ✅ Done (revised) | Pivoted to **WhatsApp Flow form** (`user_registration_v1` template, flow id `985469590600160`). Handler sends Flow template on first inbound; user submits in-app form (First Name req, Last Name req, MCI-ID opt, Speciality req multi-select); backend upserts profile with `email/address/city/state/pincode = NULL`. Parser is `parse_form_response(response_json)` — substring-matches `screen_<n>_` prefixed keys; any parse failure → `ASSISTED_SUPPORT` (no retry counter, no partial-confirm). Added `doctor.mci_id TEXT` column + Alembic migration `0002_mci_id`. Webhook normalizer handles new `message_api_flow_response` event kind → `EventKind.USER_FORM_REPLY`. Client-side rate limit removed; 429 → tenacity transient retry. 161 unit tests green. |
| 8    | Registered users journey engine + consent        | ✅ Done | `RegisteredJourneyHandler` covering all 7 `RegisteredState` branches (Case C trigger-consent, Accept/Decline, ice-breaker, AWAITING_FREE_TEXT GenAI loop, scientific vs non-scientific shaping, AWAITING_ANSWER_BUTTON Satisfied/Call hotline, hotline template send, declined-reentry); `GenAIPort` Protocol + `StubGenAIPort` (always raises `GenAIServiceError`) + module-level registry (`register_genai_port`/`get_genai_port`/`reset_genai_port_for_tests`); `ConsentRepository` + `OnboardingRepository`; 3 new `MessageSymbol`s (ACK / CONSENT_DECLINED / ANSWER_TEXT); 18 new unit tests (163 total) |
| 9    | GenAI gateway (async)                            | ⬜ Not started | Worker awaits; never the webhook hot path |
| 10   | Status webhook consumer                          | ⬜ Not started | |
| 11   | Observability                                    | ⬜ Not started | |
| 12   | Testing harness                                  | ⬜ Not started | |
| 13   | Deployment readiness                             | ⬜ Not started | |

Legend: ✅ done · 🟡 in progress · ⏳ blocked / waiting · ⬜ not started

---

## 1. Immediate next actions

1. **User**: copy `.env.example` → `.env`, fill in `DB_PASSWORD`, `INTERAKT_API_KEY`, `INTERAKT_WEBHOOK_PATH_SECRET`.
2. **User**: `pip install -e ".[dev]"` → `pre-commit install` → `pytest` (90 unit tests should pass).
3. **User**: `docker compose build && docker compose up` → verify `http://127.0.0.1:8000/healthz` returns 200 and `/readyz` returns 200 once Postgres + Redis are up.
4. **Public webhook ingress is no longer in scope for this codebase** — corporate AUP forbids cloudflared / SSH reverse / localhost.run / LocalTunnel from this dev machine. The client will provide an Azure Function (or equivalent managed gateway) that forwards Interakt traffic to the API; until that is delivered the webhook endpoint is reachable only on `127.0.0.1:8000` and via the unit test suite.
5. Move into **Phase 9** (GenAI gateway): replace `StubGenAIPort` with a real `httpx`-based adapter living at `src/wabot/adapters/genai/client.py`; honor implementation_plan.md §14.5 (retries, timeouts, optional circuit breaker); persist a `genai_interaction` row per call (request hash, response, latency, status); register via `register_genai_port(...)` from the worker boot path. Phase 8's `RegisteredJourneyHandler` already accepts the port via the registry, so wiring is drop-in.
6. Phase 13 will swap the broker backend from Redis Streams to Azure Service Bus (with sessions = `full_phone_number`) and add `XPENDING`/`XAUTOCLAIM` recovery for any stream messages that died mid-handler. Today's worker logs and continues on `BrokerConsumeError`; redelivery happens via consumer-group retry, not in-process bookkeeping.

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
- **Registration form (v2.2 — current)**: WhatsApp Flow form delivered via `user_registration_v1` template (`is_flow_template = true`). Fields: `first_name` (req), `last_name` (req), `mci_id` (opt), `speciality` (req multi-select; backend joins with `", "`). `email/address/city/state/pincode` are left `NULL` to avoid major code changes; columns remain in schema for future re-introduction. No partial-confirm step and no retry counter — parse failure escalates straight to `ASSISTED_SUPPORT`.
- **No client-side Interakt rate limit**: Interakt is the source of truth for throughput; `429 Too Many Requests` is reclassified as a transient error and retried via tenacity. No Redis token bucket. `INTERAKT_RATE_LIMIT_RPS` env removed.
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

### 2026-05-10 — Phase 7 revised: WhatsApp Flow form registration
- Replaced `#`-delimited free-text parser with a **Flow form** (`user_registration_v1`, flow id `985469590600160`).
- Webhook plumbing: new `EVENT_TYPE_API_FLOW_RESPONSE = "message_api_flow_response"` in `api/schemas/interakt_webhook.py`; `EventKind.USER_FORM_REPLY` + `form_response: dict | None` on `CanonicalInboundEvent`; normalizer extracts `data.message.message.nfm_reply.response_json` (handles `message_received` envelopes that carry an `InteractiveFlowReply` body too).
- `domain/parsers/registration.py` fully rewritten: `parse_form_response(response_json)` returns `ParsedRegistration(first_name, last_name, speciality, mci_id)`. Substring (case-insensitive) match against Interakt's `screen_<n>_<field>` keys; speciality multi-select joined with `", "`. No retry / partial-confirm logic.
- `domain/journeys/registration.py` fully rewritten: Case A creates shell + sends Flow template (state `AWAITING_FULL_DETAILS`); `USER_FORM_REPLY` upserts profile (with `email/address/city/state/pincode = None`) → `REGISTRATION_COMPLETED` → `MSG_REG_COMPLETED`; parse failure → `ASSISTED_SUPPORT`; any other non-form inbound while awaiting form re-sends the template.
- DB: new `doctor.mci_id TEXT` column. ORM updated, repo `upsert_profile` gained `mci_id` kwarg, `models.txt` §3 + new §13 idempotent ALTER, Alembic migration `migrations/versions/20260510_0002_add_mci_id.py`.
- Outbound: `OutboundIntent.is_flow_template: bool` + `build_template(..., is_flow_template=True)`; client adds `"is_flow_template": true` to the template body.
- Removed client-side rate limiting: dropped `INTERAKT_RATE_LIMIT_RPS`, `_RATE_LIMIT_KEY_PREFIX`, `_acquire_rate_token`, `redis_client` ctor arg. 429 is now an `InteraktTransientError` handled by tenacity exp-backoff retry. Inbound worker no longer passes `redis_client=` to the client.
- Config: new `template_user_registration` setting (default `user_registration_v1`).
- Catalog: new `MessageSymbol.TEMPLATE_USER_REGISTRATION` (kept old MSG_REG_* / partial-confirm button symbols as dead-but-harmless to avoid touching unrelated tests).
- drive_webhook: new `flow <phone> <json>` subcommand for end-to-end simulation.
- Tests: rewrote `tests/unit/test_registration_parser.py` and `tests/unit/test_registration_journey.py`; full suite is **161 passed**.
- Pending: live retest on `919867401411`, then commit + push.

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

### 2026-05-11 — Phase 8 complete (registered users journey + consent)
- **GenAI port** (`src/wabot/domain/ports/genai.py`):
  - Frozen `GenAIRequest(conversation_id, doctor_id, user_message, current_state, locale="en", recent_turns=(), summary_context="")` and `GenAIResponse(intent, query_nature, answer_text, app_link=None, send_processing_message=False, show_answer_buttons=False, requires_hotline=False, meta={})`. `QueryNature = Literal["scientific","non_scientific"]`, `IntentLabel = Literal["answer","hotline","fallback"]`.
  - `GenAIPort(Protocol)` with `async def generate(request) -> GenAIResponse`. `StubGenAIPort.generate` **always** raises `GenAIServiceError("genai stub: no live adapter registered")` — forces handlers down the fallback branch until Phase 9 swaps in a real client. Module-level registry: `register_genai_port`, `get_genai_port` (lazy default = `StubGenAIPort()`), `reset_genai_port_for_tests`. The default is intentional: an accidental prod boot without a real adapter trips loudly the first time a user types instead of pretending to answer.
- **Repositories**:
  - `ConsentRepository` (`src/wabot/data/repositories/consent_repo.py`): `get(doctor_id)`, `upsert_pending(*, doctor_id, last_template_msg_id=None)` (inserts on first send, otherwise stamps `last_template_msg_id` and re-flips status to `PENDING`), `set_status(*, doctor_id, status, correlation_id=None, reason=None)` (stamps `accepted_at` / `declined_at` based on status and appends a `ConsentHistory` row for audit).
  - `OnboardingRepository` (`src/wabot/data/repositories/onboarding_repo.py`): `get(doctor_id)` and `mark_onboarded(doctor_id)` (idempotent — preserves the original `onboarded_at` if already onboarded; only flips a freshly-created row's `is_onboarded`).
- **Catalog** (`src/wabot/domain/messages/catalog.py`):
  - Added `MessageSymbol.MSG_REGISTERED_CONSENT_ACK` (TEXT, "Thanks for accepting. You're all set."), `MSG_REGISTERED_CONSENT_DECLINED` (TEXT, "No problem. If you change your mind, just send us a message and we'll share the consent form again."), and `MSG_REGISTERED_ANSWER_TEXT` (TEXT, no static body — handler always supplies `text_override`). Symbol kinds and static templates registered in `MESSAGE_CATALOG`.
- **Journey handler** (`src/wabot/domain/journeys/registered.py`):
  - `RegisteredJourneyHandler.__init__(*, genai_port: GenAIPort | None = None)` — overrides the registry for tests; production resolves via `get_genai_port()` through the `_genai_port` property. Module-level title constants `_CONSENT_ACCEPT_TITLE = "Accept"`, `_CONSENT_DECLINE_TITLE = "Decline"` matched case-insensitively (Interakt only echoes button titles).
  - **Case C (fresh / no journey row, or `state_registered=None`)** → `consent_repo.upsert_pending` + `onboarding_repo.mark_onboarded` + emit `TEMPLATE_DOCTOR_WELCOME_CONSENT` with `body_values=(_doctor_display_name(doctor),)` → next state `CONSENT_PENDING`, expected `BUTTON`.
  - **`CONSENT_PENDING` + button reply**: case-insensitive title match. `"Accept"` → `consent_repo.set_status(ACCEPTED, correlation_id=_safe_uuid(event.correlation_id))` → emit `MSG_REGISTERED_CONSENT_ACK` + ice-breaker buttons (`REGISTERED_ASK_QUESTION` "Ask a question", `REGISTERED_TALK_TO_HOTLINE` "Talk to hotline") → next state `CONSENT_ACCEPTED`, expected `BUTTON`. `"Decline"` → `set_status(DECLINED)` → `MSG_REGISTERED_CONSENT_DECLINED` → `CONSENT_DECLINED`, expected `FREE_TEXT`. Free-text (non-button) on `CONSENT_PENDING` → `MSG_REGISTERED_FALLBACK_CHOOSE_OPTION`, stay in `CONSENT_PENDING`.
  - **`CONSENT_DECLINED` + any inbound** → re-sends the consent template (no cooldown — implementation_plan.md §7.7). The user can opt-in again at any time by saying anything.
  - **`CONSENT_ACCEPTED`**: title `"Ask a question"` → text "Sure — go ahead and type your question." + `AWAITING_FREE_TEXT`. Title `"Talk to hotline"` → hotline template (see below). Anything else (free text or unknown button) → `_handle_free_text` (per §11.5: free-text fallthrough after consent is a query).
  - **`AWAITING_FREE_TEXT`**: build `GenAIRequest`, call `self._genai_port.generate(request)`. On `GenAIServiceError` (network, 5xx, parse, etc.) → `MSG_REGISTERED_FALLBACK_GENAI_FAILED`, stay in `AWAITING_FREE_TEXT`. `intent=="hotline"` or `requires_hotline` → hotline template. `intent=="fallback"` → `MSG_REGISTERED_FALLBACK_GENAI_FAILED`. Otherwise: scientific → optional `MSG_REGISTERED_ACK_THINKING` (only when `send_processing_message=True`) + `MSG_REGISTERED_ANSWER_WITH_BUTTONS` (text_override = `answer_text` plus `\n\n{app_link}` when present, two buttons `REGISTERED_ANSWER_SATISFIED` "Satisfied" and `REGISTERED_ANSWER_CALL_HOTLINE` "Call hotline") → `AWAITING_ANSWER_BUTTON`. Non-scientific → `MSG_REGISTERED_ANSWER_TEXT` with `text_override=answer_text` (no buttons) → `AWAITING_FREE_TEXT`. Empty inbound text → fallback prompt.
  - **`AWAITING_ANSWER_BUTTON`**: title `"Satisfied"` → text "Great — let me know if you have another question." + `AWAITING_FREE_TEXT`. Title `"Call hotline"` → hotline template. Free text → fall through to `_handle_free_text` (treated as the next query per §11.5).
  - **Transient states (`GENAI_PROCESSING`, `HOTLINE_TEMPLATE_SENT`)**: user replied during a transient state → treated as a fresh free-text turn so the conversation never stalls.
  - **Hotline template send**: `build_template(TEMPLATE_HOTLINE, body_values=(_doctor_display_name(doctor),))` + state `HOTLINE_TEMPLATE_SENT`, expected `FREE_TEXT`.
  - Handler auto-registers via `register_journey_handler(JourneyType.REGISTERED, RegisteredJourneyHandler())` at module end; `wabot/domain/journeys/__init__.py` imports it for the side-effect.
- **Tests** (18 new, 163 total):
  - `tests/unit/test_genai_port.py` (3): stub always raises, registry default is stub, registry swap replaces the active port.
  - `tests/unit/test_registered_journey.py` (15): Case C marks onboarded + sends template with the doctor display name; Accept records `ACCEPTED` + emits ack + ice-breaker; Decline records `DECLINED` + emits decline text; free-text on `CONSENT_PENDING` falls back; declined-reentry re-sends template; ice-breaker `Ask a question` → `AWAITING_FREE_TEXT`; `Talk to hotline` → hotline template; scientific GenAI response → ack + buttons (Satisfied / Call hotline) + `AWAITING_ANSWER_BUTTON` (and app_link is concatenated with `\n\n`); non-scientific → text only + `AWAITING_FREE_TEXT`; `GenAIServiceError` → fallback; `intent="hotline"` → hotline template; `Satisfied` button → `AWAITING_FREE_TEXT`; `Call hotline` button → hotline template; free text on `AWAITING_ANSWER_BUTTON` invokes GenAI again; handler is auto-registered (with defensive re-registration to survive `reset_handlers_for_tests`).
- **Lessons / gotchas**:
  - `StubGenAIPort` always raising is deliberate: a silent stub answer in production would be worse than a clearly-logged fallback. Phase 9 must call `register_genai_port(...)` from worker boot **before** any inbound is consumed.
  - `ConsentRepository.set_status` stamps `accepted_at` / `declined_at` server-side via `clock_timestamp()` to stay consistent with §2 timestamp policy; mirroring the timestamps in `ConsentHistory` keeps audit ordering unambiguous.
  - `OnboardingRepository.mark_onboarded` must be idempotent without rewriting `onboarded_at` — the first send wins. The repo only touches the timestamp on the initial insert.
  - The button-title contract is now repeated for the registered journey: match titles case-insensitively against module-level constants; `ButtonId` still drives the outbound build.
  - The handler returns intents only (never sends); the orchestrator's outbound pipeline owns the wire call. This preserves the Phase 6 contract and keeps the handler easily testable with synchronous in-memory stubs.
  - **Commit workflow**: `git add -A` **before** `pre-commit run` (so the hooks see new files in the first run). After hooks autofix, `git add -A` again, then `git commit`. This removes the double-commit churn that plagued earlier phases. Saved at `/memories/repo/commit-workflow.md`.

### 2026-05-11 — Phase 7 complete (user registration journey engine)
- **Parser** (`src/wabot/domain/parsers/registration.py`):
  - Pure (no I/O, no DB, no settings). `parse_registration(text)` splits the inbound on `#`, requires exactly 7 stripped non-empty tokens in the order `Full Name#Speciality#Address#Email#City#State#Pincode`, validates email via `^[^@\s]+@[^@\s]+\.[^@\s]+$` and pincode via `^\d{6}$`, splits the full name on the first whitespace run (single-word → `last_name=None`, multi-word → `first` + everything else as `last_name`). Returns frozen `ParsedRegistration`. Raises `RegistrationParseError(reason, field)` with stable slugs (`empty_payload`, `field_count`, `empty:<field>`, `email_format`, `pincode_format`) so handler tests can pin failure modes without depending on copy.
- **Journey handler** (`src/wabot/domain/journeys/registration.py`):
  - `RegistrationJourneyHandler.handle(...)` is the registry entry for `JourneyType.REGISTRATION`. Auto-registers on module import via `register_journey_handler(JourneyType.REGISTRATION, RegistrationJourneyHandler())` at the bottom; `wabot.domain.journeys/__init__.py` re-imports the module so any consumer that imports the package gets the handler wired.
  - **Case A (fresh, doctor=None)** → `DoctorRepository.create_shell(full_phone)` → emit `MSG_REG_FULL_DETAILS_PROMPT` → next state `AWAITING_FULL_DETAILS`, expected `REGISTRATION_TEXT`, retry_count=0.
  - **Case D defensive (partial doctor, no journey row)** → if any seed field is populated, emit `MSG_REG_PARTIAL_CONFIRM_PROMPT` with `ButtonId.REG_PARTIAL_CONFIRM_YES/NO` (titles `"Yes"`/`"No"`) and transition to `PARTIAL_CONFIRM_PENDING` (expected BUTTON); otherwise fall through to the full-details prompt.
  - **Text-input states** (`AWAITING_FULL_DETAILS` / `AWAITING_CORRECTED_FULL` / `AWAITING_REMAINING_DETAILS`): try `parse_registration(event.text)`. On success → `DoctorRepository.upsert_profile(..., is_profile_complete=True)` (repo also stamps `registration_completed_at` when it transitions to complete) → emit `MSG_REG_COMPLETED` → next state `REGISTRATION_COMPLETED`. The router will then pick `RoutingCase.C_TRIGGER_CONSENT` on the user's next inbound (Phase 8).
  - **Parse failure**: `next_retry = journey.retry_count + 1`. If `next_retry > settings.registration_max_retries` (default `2` via `REGISTRATION_MAX_RETRIES`) → emit `MSG_REG_ASSISTED_SUPPORT`, next state `ASSISTED_SUPPORT`. Otherwise emit `MSG_REG_RETRY_PROMPT`, next state `AWAITING_CORRECTED_FULL`, persist `retry_count=next_retry`.
  - **`PARTIAL_CONFIRM_PENDING`**: only `EventKind.USER_BUTTON_REPLY` advances; match on `event.button_text` (Interakt echoes the title, not the id). Title `"Yes"` → upsert existing doctor fields with `is_profile_complete=True` → `MSG_REG_COMPLETED` → `REGISTRATION_COMPLETED`. Title `"No"` → re-prompt full details, next state `AWAITING_FULL_DETAILS`. Anything else (free-text or unknown title) → emit `MSG_REGISTERED_FALLBACK_CHOOSE_OPTION` and stay in `PARTIAL_CONFIRM_PENDING` (per plan §11.5).
  - **Terminal states** (`REGISTRATION_COMPLETED`, `ASSISTED_SUPPORT`): no outbound, state preserved. Defensive: registration row with `state_registration=None` re-prompts full details rather than crashing.
  - Handler returns only `JourneyResult`; the orchestrator dispatches `outbound_intents` post-commit under the user lock (Phase 6 pipeline). No direct Interakt calls from the handler.
- **Config** (`src/wabot/infra/config.py`): added `registration_max_retries: int = 2` (alias `REGISTRATION_MAX_RETRIES`). Matches implementation_plan.md §6 line 63 verbatim.
- **Tests** (23 new, 145 total):
  - `tests/unit/test_registration_parser.py` (11): happy path, whitespace strip, single-word + three-word name, wrong field count, empty field (slug `empty:speciality`), bad email, bad pincode (length + non-digit), empty/None payload, field-count constant alignment.
  - `tests/unit/test_registration_journey.py` (12): Case A creates shell + prompts; valid 7-token text completes; parse failure with retry_count=0 → `AWAITING_CORRECTED_FULL` + retry_count=1 + `MSG_REG_RETRY_PROMPT`; retry_count=`registration_max_retries` → `ASSISTED_SUPPORT` + `MSG_REG_ASSISTED_SUPPORT`; partial-confirm Yes → completed (upsert uses existing doctor fields); partial-confirm No → re-prompt full details; free text on `PARTIAL_CONFIRM_PENDING` → fallback; defensive Case D with partial doctor → partial-confirm prompt with both button ids; defensive Case D with empty doctor → full-details prompt; terminal `ASSISTED_SUPPORT` → no-op; handler auto-registered (re-registers after `reset_handlers_for_tests` to be robust to `test_orchestrator.py` running first).
- **Lessons / gotchas**:
  - `JourneyState` uses `doctor_id` as PK — there is no `id` column. Mypy caught three logger calls using `journey.id`; replaced with `journey.doctor_id`.
  - `CanonicalInboundEvent.button_text` carries the **button title**, not the `ButtonId`. Interakt's `message_received` for QR replies only echoes the title via `meta_data.button_payload.payload.text`. The handler therefore matches Yes/No by case-insensitive title compare against module-level title constants; the `ButtonId` enum still drives the outbound build so the catalog stays the single source of truth.
  - The registry is module-level and `reset_handlers_for_tests()` (used autouse by `test_orchestrator.py`) clears it. Because pytest caches imports, the registration module's import-time `register_journey_handler(...)` does **not** run again after a reset. Tests that depend on the registration handler being registered must re-register defensively (`register_journey_handler(JourneyType.REGISTRATION, RegistrationJourneyHandler())`). The orchestrator's runtime path is unaffected: production code never calls `reset_handlers_for_tests`.
  - Importing concrete handler modules from `domain/journeys/__init__.py` is the auto-wiring seam. Phase 8's `registered` handler will follow the same pattern: bottom-of-file `register_journey_handler(...)` + an import in `__init__.py`.

### 2026-05-11 — Phase 6 complete (outbound dispatcher + Interakt adapter)
- **`OutboundIntent` contract** (`src/wabot/domain/outbound.py`):
  - Pydantic v2 model, `extra="forbid"`, `frozen=True`, slot-friendly field set: `kind` (`Literal["TEXT","BUTTONS","TEMPLATE"]`), `full_phone_number` (length-bounded), `symbol` (catalog id; participates in idempotency), and optional payload fields (`text`, `buttons: tuple[InteractiveButton,...]|None`, `template_name`/`template_locale`/`body_values`/`header_values`/`button_values`/`file_name`).
  - `InteractiveButton` enforces WhatsApp's 20-char title cap and a non-empty id. Every model is frozen so a handler cannot rewrite an emitted intent and cause partial dispatch.
- **Catalog + pure builders** (`src/wabot/domain/messages/`):
  - `MessageSymbol(StrEnum)` is the single source of truth for outbound symbols (6 registration prompts, 5 registered prompts, 2 templates). `CATALOG: dict[MessageSymbol, CatalogEntry]` carries the kind + (for TEXT/BUTTONS) the English copy + (for TEMPLATE) the `AppSettings` attribute name that resolves the Interakt template code-name. `ButtonId(StrEnum)` keeps reply-id strings centralised so the journey routers and the dispatcher cannot drift.
  - `build_text` / `build_buttons` / `build_template` are pure: `(symbol, full_phone_number, params) -> OutboundIntent`. They raise `MessageBuildError` on kind mismatch, missing copy, or empty buttons. Phases 7/8 call these instead of constructing `OutboundIntent` by hand so kind+symbol agreement is guaranteed at the call site.
- **Interakt async client** (`src/wabot/adapters/interakt/client.py`):
  - `InteraktClient(settings, *, http_client=None, redis_client=None, sleep=asyncio.sleep)` owns the lifecycle of one `httpx.AsyncClient` (timeouts pulled from `settings.interakt_timeout_*`, base URL from `settings.interakt_base_url`, and `Authorization: Basic {INTERAKT_API_KEY}` header — Interakt issues a pre-encoded key, we pass it through verbatim per the docs). `aclose()` is idempotent; the worker calls it on shutdown.
  - `send(intent, *, callback_data)` translates the intent via `build_request_body(...)` (handles `Text` / `InteractiveButton` / `Template` shapes; **never** sends `template_category`; always sends `fullPhoneNumber` + `callbackData`) and POSTs to `/v1/public/message/`. 4xx \u2192 `InteraktPermanentError` (no retry). 5xx / network / non-JSON \u2192 `InteraktTransientError`. Tenacity `AsyncRetrying` wraps the whole thing with `wait_random_exponential(multiplier=0.5, max=8)` + `stop_after_attempt(4)`; `sleep` is injectable so unit tests don't burn real wall-clock seconds. A 200 response with `result=false` collapses to permanent (Interakt's documented "rejected" envelope).
  - `_acquire_rate_token()` runs an `INCR` + `EXPIRE 2` per-second token bucket against `wabot:interakt:rate:{epoch_second}`. Above `settings.interakt_rate_limit_rps` we sleep until the next second boundary. Redis errors degrade open (we never block outbound traffic on our own infra) and are logged.
- **Outbound pipeline** (`src/wabot/services/outbound_pipeline.py`):
  - `compute_idempotency_key` is `sha256(doctor_id|state_when_sent|correlation_id|sequence|symbol|sha256(payload_dump))` so retries collapse but two intents from the same handler invocation get distinct rows. Sequence is the per-dispatch index (0, 1, 2 \u2026) — necessary because two consecutive symbols *could* be identical (re-prompt + same prompt reissue) and we still want the second one to live.
  - Per intent: open `session_scope()` \u2192 `OutboundRepository.create_pending(...)` (idempotency-keyed; returns the existing row on collision) \u2192 if the row was fresh, rewrite `callback_data` from the placeholder `"PENDING_SEND"` to `"{row.id}|{correlation_id}"` \u2192 commit. Then `await client.send(intent, callback_data=...)` outside the DB transaction. On success: a second short transaction calls `mark_sent(row.id, interakt_message_id, sent_at)`. On `InteraktPermanentError` (or transient retries exhausted): a third short transaction sets `status=FAILED`, `failed_at=now`, `failure_reason=str(exc)[:1000]`. Per-intent failures are isolated so one 4xx never aborts later intents.
- **Orchestrator wiring** (`src/wabot/services/orchestrator.py`):
  - `Orchestrator(settings, *, pipeline=None)` accepts an optional `OutboundPipeline`; tests still construct `Orchestrator(settings)` and pipeline-less dispatch is a single warn log (`outbound_intents_dropped_no_pipeline`).
  - `_handle_locked` now returns a `_DispatchPlan(doctor_id, state_when_sent, intents)` captured **inside** the session_scope. After the scope commits but **still under the user lock**, `handle_message` calls `await self._pipeline.dispatch(plan.intents, ...)`. This satisfies plan \u00a79: DB transaction is short, outbound never holds a connection, and per-user FIFO ordering (one outbound chain finishes before the next inbound event runs).
  - `JourneyResult.outbound_intents` tightened from `tuple[Any, ...]` to `tuple[OutboundIntent, ...]`. Phases 7/8 now have a typed contract.
- **Worker lifecycle** (`src/wabot/workers/inbound_worker.py`):
  - `_run` constructs `InteraktClient(settings, redis_client=redis)` once at startup and threads it into `OutboundPipeline(client=...)` \u2192 `Orchestrator(settings, pipeline=...)`. Shutdown cancels the consume task, `aclose()`s the Interakt client (suppress errors), then closes broker / redis / DB engine in the existing order.
- **Tests** (32 new, 122 total):
  - `tests/unit/test_outbound_intent.py` (10): frozen, extra=forbid, length bounds, kind branches.
  - `tests/unit/test_messages_builder.py` (8): catalog text + override path, kind mismatches, empty-buttons guard, template happy path.
  - `tests/unit/test_interakt_client.py` (8): `httpx.MockTransport` coverage of TEXT/BUTTONS/TEMPLATE wire shapes (asserts `template_category` absent, `callbackData` present), 4xx \u2192 permanent, 5xx retried-then-200, 5xx exhausted, 200+`result=false` \u2192 permanent. Backoff sleeps stubbed via injected `sleep`.
  - `tests/unit/test_outbound_pipeline.py` (6): persists + sends, marks FAILED on `InteraktPermanentError`, isolates per-intent failures, idempotency-key determinism (same args identical, sequence different distinct), kind enum sanity.
- **Pre-commit**: added `httpx==0.28.1` and `tenacity==9.1.4` to the mypy hook's `additional_dependencies` so strict mypy runs in the pre-commit cached venv. All hooks (ruff, ruff-format, black, mypy, bandit) clean.
- **Lessons learned**:
  - mypy with `httpx`/`tenacity` *needs* both libs installed in the pre-commit env, not just locally — strict mode rejects `Cannot find implementation or library stub` even when you have stubs in your project venv.
  - `tenacity.AsyncRetrying` accepts `sleep=` directly; passing a no-op makes 4-attempt retry tests run in milliseconds rather than ~12 s.
  - `wait_random_exponential` (not `wait_exponential_jitter`) is the public tenacity 9.x API for jittered exponential.
  - Lazy `_outbound_model()` to dodge a circular import is a code smell. Just import `OutboundMessage` directly — `outbound_repo` already imports it and the pipeline depends on the repo, so there's no cycle.
- **Not in scope (deferred)**:
  - A reconciliation worker that re-attempts `FAILED` rows with `failure_reason` matching transient classes \u2014 Phase 11 (observability + replay tooling) will own that.
  - Surfacing rate-limit waits as a Prometheus counter \u2014 Phase 11.
- **Next**: Phase 7 \u2014 user registration journey engine. Build `domain/journeys/registration_handler.py` + `domain/registration_parser.py`. Plug in via `register_journey_handler(JourneyType.REGISTRATION, RegistrationJourneyHandler())`. Outbound side is fully wired: handlers just return `outbound_intents=(...)` built from `wabot.domain.messages`.

### 2026-05-10 — Phase 5 complete (orchestrator + per-user lock + free-text router)
- **Per-user Redis lock** (`src/wabot/cache/locks.py`):
  - `UserLock` is the **only** mutual-exclusion primitive on the inbound path. Acquisition is `SET NX PX` against `wabot:lock:user:{full_phone}` with a 16-byte random token (`secrets.token_hex(16).encode()`); release is a Lua check-and-delete script (`_RELEASE_SCRIPT`) so we never delete a key owned by a different worker after a TTL refresh race.
  - A watchdog task (`_refresh_loop`) re-runs `PEXPIRE` every `refresh_interval_seconds` (default 10 s) so a slow handler can never lose the lock under the default 30 s TTL. If `PEXPIRE` returns 0 we log `wabot.lock.lost` and let the handler keep running — the orchestrator will detect the next failure via the journey state row, not via the lock primitive (locks are an ordering guarantee, not a correctness gate).
  - `__init__` validates `refresh_interval_seconds < ttl_seconds` and `ttl_seconds > 0` so a misconfiguration crashes at construction, not at runtime.
  - `__aenter__` polls until `acquire_timeout_seconds` (default 30 s) elapses and raises `UserLockUnavailableError`. The orchestrator catches that and returns `False` to the worker, which **does not ack** — the broker redelivers via consumer-group retry.
- **Broker consume API** (`src/wabot/adapters/broker/base.py`, `redis_streams.py`):
  - Extended `InboundBroker` Protocol with `ensure_consumer_group(*, group)`, `consume(*, group, consumer, batch_size=16, block_ms=2000) -> list[InboundMessage]`, `ack(*, message_id)`. New error class `BrokerConsumeError` and frozen dataclass `InboundMessage(message_id, partition_key, payload)`.
  - `RedisStreamsBroker.ensure_consumer_group` uses `XGROUP CREATE … MKSTREAM` and tolerates `BUSYGROUP` (group already exists). Any other `ResponseError` is wrapped as `BrokerConsumeError`.
  - `consume` uses `XREADGROUP GROUP {group} {consumer} BLOCK {block_ms} COUNT {batch_size} STREAMS {stream} >`, decodes the stored fields (`b"key"` and orjson-encoded `b"data"`), and returns `[]` on idle. Non-dict payloads → `BrokerConsumeError` (poison handling is one layer up).
  - `ack` calls `XACK` and **logs warnings instead of raising** because `XPENDING` + a future `XAUTOCLAIM` reaper (Phase 13) is the recovery path. Raising here would crash the consumer loop and lose progress on the rest of the batch.
- **Pure router** (`src/wabot/domain/router.py`):
  - `route_user_event(*, event, doctor, journey, onboarding) -> RoutingDecision` is a pure function over already-loaded snapshots (no DB, no Redis, no time). Cases A–D from `implementation_plan.md` §6 are implemented exactly as documented:
    - **Case A** (no doctor row) → start `REGISTRATION` from `REG_INITIATED` expecting `REGISTRATION_TEXT`.
    - **Case D** (doctor exists, profile incomplete) → resume the existing `REGISTRATION` journey row if present, otherwise restart from `REG_INITIATED`.
    - **Case C** (profile complete, not onboarded) → kick `REGISTERED.CONSENT_PENDING` expecting a `BUTTON`. Missing onboarding row is treated as not-onboarded so the consent template is sent on first-ever inbound.
    - **Case B** (profile complete + onboarded) → resume the existing `REGISTERED` journey row, falling back to a fresh `AWAITING_FREE_TEXT` if the row is missing (defensive against bad data).
  - Status events (everything in `OUTBOUND_STATUS_KINDS`) short-circuit to `RoutingCase.NON_USER_EVENT` so the orchestrator can dispatch them to the outbound-status handler without going through the user router.
- **Journey framework** (`src/wabot/domain/journeys/base.py`):
  - `JourneyResult` (frozen dataclass) is the contract every handler returns: `next_journey`, `next_registration_state`, `next_registered_state`, `expected_input_kind`, `expected_outbound_id`, `retry_count`, `context_patch`, `outbound_intents`. `outbound_intents` is typed `tuple[Any, ...]` for now — `OutboundIntent` ships in Phase 6 and the orchestrator just counts and logs them as `wabot.orchestrator.outbound_intents_pending` until the dispatcher exists.
  - `JourneyHandler(Protocol).handle(*, event, decision, journey, doctor, session) -> JourneyResult` is the only seam Phases 7/8 need to plug into. `OutboundStatusHandler.handle(*, event, session) -> None` is the seam Phase 10 plugs into.
  - Defaults: `NoopJourneyHandler` (returns the existing journey row's state on resume, otherwise the decision's initial state) and `NoopOutboundStatusHandler`. Both are wired automatically. `register_journey_handler(JourneyType, handler)` and `register_outbound_status_handler(handler)` swap them in. `reset_handlers_for_tests()` undoes every registration — used by the test suite.
- **Orchestrator** (`src/wabot/services/orchestrator.py`):
  - `Orchestrator.handle_message(InboundMessage) -> bool`. The boolean is the ack decision: `True` → broker `XACK`, `False` → leave pending so the consumer group redelivers it.
  - Pipeline: extract `event_id` + `full_phone_number` (poison payloads are logged and acked to drain) → bind a structured-log context (`broker_message_id`, `event_id`, `full_phone_number`, `correlation_id`) → take the user lock → open a single `session_scope()` short transaction → `session.get(WebhookEventRaw, event_id)` (skip if missing or already processed) → `normalize(...)` (mark processed and ack on `NormalizationError`) → branch on `event.event_kind`.
  - **User events**: load doctor (`DoctorRepository.get_by_phone`), journey (`JourneyRepository.get`), onboarding (one-shot `select` on `WhatsappOnboardingStatus` — no dedicated repo because it's read-only at this point). Idempotency: if `journey.last_processed_event_id == event.interakt_message_id` we skip the handler entirely, mark the raw row processed, and ack (re-delivery from the broker must not double-fire side effects). Otherwise call the registered `JourneyHandler`, then `_persist_result`.
  - **Status events**: hand straight to `get_outbound_status_handler().handle(event, session)`. The default Noop just logs; Phase 10 swaps in the real one.
  - `_persist_result` re-loads the doctor before persisting (registration handlers in Phase 7 may create the shell mid-flight). If there's still no doctor row we skip the upsert and log the pending intents — never persist a `journey_state` row without a `doctor_id`. When `from_state != to_state` we call `JourneyRepository.append_history` keyed off `event.interakt_message_id` and (parsed) `correlation_id`.
  - Local import of `WebhookEventRaw` inside `_handle_locked` is intentional — keeps TC003 clean and avoids circular-import friction with the data layer.
- **Worker rewrite** (`src/wabot/workers/inbound_worker.py`):
  - Consumer name is `f"{socket.gethostname()}-{os.getpid()}"` so a multi-worker deployment shows up cleanly in `XPENDING`. Group name comes from `settings.broker_inbound_group`.
  - `_consume_forever` calls `broker.ensure_consumer_group(group)` once at startup, then loops `consume → handle_message → ack` until SIGINT/SIGTERM. `BrokerConsumeError` triggers a 1-second backoff (no death spirals when Redis blips). `Orchestrator.handle_message` returning `False` means **do not ack** — pending entries are eligible for `XAUTOCLAIM` once Phase 13 ships.
  - `_run` configures logging, primes the engine + Redis singletons, instantiates `Orchestrator`, installs signal handlers, awaits stop, then `cancel(consume_task) → close_broker → close_redis → dispose_engine` in that order. Same singleton lifecycle as the API process, so swapping between webhook ingest and worker drain doesn't reopen connections.
- **Tests added** (29 new, 90 total green):
  - `tests/unit/test_locks.py` (5): hand-rolled async `FakeRedis` covering acquire/release happy path, contention with the `acquire_timeout_seconds` deadline, blocking-second-acquirer, Lua-script ownership safety (mismatched token does not delete), and constructor validation of the TTL/refresh ratio.
  - `tests/unit/test_router.py` (8): `SimpleNamespace` stand-ins for doctor/journey/onboarding to keep the router pure; cases A–D plus the `RoutingCase.NON_USER_EVENT` short-circuit and the defensive Case B/D restart paths.
  - `tests/unit/test_orchestrator.py` (8): patches `UserLock`, `get_redis`, `session_scope`, `normalize`, `DoctorRepository`, `JourneyRepository`, and `_load_onboarding`; asserts ack semantics for missing/already-processed raw rows, lock contention, poison payloads, normalization failure, status-event dispatch, user-event handler invocation + persistence, and `last_processed_event_id` deduplication.
  - `tests/unit/test_broker_redis_streams.py` (8): mocks `redis.asyncio.Redis` to assert `XGROUP CREATE` / `BUSYGROUP` tolerance, `XREADGROUP` decode shape, idle returns `[]`, `XACK` argument shape, and that non-dict payloads or upstream errors raise `BrokerConsumeError`.
- **Validation**: `pytest -q` → 90/90 green. `pre-commit run --all-files` → all hooks (ruff, ruff-format, black, mypy strict, bandit) clean after one ruff auto-fix on a redundant import.
- **Decisions**:
  - Locks are an ordering guarantee, not a correctness gate. The `journey_state.version` row + `last_processed_event_id` are the source of truth for idempotency. We pick this combination explicitly so a multi-worker deployment can lose a Redis lock to TTL expiry without corrupting state.
  - `broker.ack` swallows errors. `XPENDING` + future `XAUTOCLAIM` (Phase 13) is the recovery story; raising here would crash the loop on a transient blip.
  - Default journey handler is a real Noop, not a `NotImplementedError` raiser. Phases 7/8 register the real ones. This means the worker can be deployed end-to-end today and will gracefully drain status events while user events get a silent state-only update — easier to validate against a live Interakt without templates configured.
- **Webhook tunnel work permanently abandoned**. Corporate security flagged cloudflared, localhost.run, LocalTunnel, and SSH reverse tunnels as AUP violations. The user has uninstalled cloudflared and reset the Interakt webhook configuration. Future webhook ingress will be served by an Azure Function/Service hosted by the client and forwarded to this app. **Do not propose tunnels again.**
- **Next**: Phase 6 — outbound dispatcher + Interakt adapter. Build `OutboundIntent`, `OutboundMessageRepository.create_pending`, `adapters/interakt/client.py`, `services/outbound_pipeline.py` so journey handlers in Phases 7/8 can return `outbound_intents` that turn into Interakt API calls with `callbackData = {outbound_id}|{correlation_id}`.

### 2026-05-10 — Phase 4 complete (webhook normalizer + canonical event)
- **Domain model** (`src/wabot/domain/events.py`):
  - `EventKind(StrEnum)` with 8 values: `USER_TEXT`, `USER_BUTTON_REPLY`, `USER_LIST_REPLY`, `OUTBOUND_SENT`, `OUTBOUND_DELIVERED`, `OUTBOUND_READ`, `OUTBOUND_FAILED`, `OUTBOUND_CLICKED`. Convenience sets `USER_EVENT_KINDS` / `OUTBOUND_STATUS_KINDS` for journey routing.
  - `CanonicalInboundEvent(BaseModel)` is `model_config = ConfigDict(extra="forbid", frozen=True)` — closed shape, immutable, downstream code can hash/compare freely. Carries `correlation_id`, `raw_event_id`, `event_kind`, `interakt_message_id`, `interakt_customer_id`, `full_phone_number`, `text`, `button_text`, `click_type` (`Literal["QR","CTA"]`), `callback_data`, `referenced_outbound_message_id` (UUID-validated), `failure_reason`, `received_at` (microsecond UTC).
- **Adapter** (`src/wabot/adapters/interakt/normalizer.py`): pure function `normalize(*, raw_event_id, correlation_id, payload) -> CanonicalInboundEvent`. **Single source of truth** for Interakt's wire format — every downstream consumer reads only the canonical event.
  - Coerces the raw payload through `InteraktEnvelope.model_validate` (defensive — raises `NormalizationError` not `ValidationError` so the worker has one exception class to catch).
  - Required routing fields: `data.message.id` and a derivable phone (channel_phone_number || country_code+phone). Missing → `NormalizationError`.
  - **Click discrimination** is dual-shape:
    - **CTA**: top-level `event.click_type == "CTA"`, `event.callbackData`, `event.button_text`.
    - **QR**: `data.message.meta_data.click_type == "QR"`, label deep under `meta_data.button_payload.payload.text`, `callbackData` lives at `meta_data.source_data.callback_data`.
  - **callbackData precedence**: top-level `event.callbackData` → `meta_data.source_data.callback_data` → `meta_data.callbackData` (defensive). The CTA path *intentionally* wins over the QR/status path because Interakt mirrors stale values into `meta_data` for click events.
  - **`referenced_outbound_message_id`** parses the documented `"{outbound_message_id}|{correlation_id}"` contract via strict UUID validation on the head; non-UUID heads (free-form template callbacks) silently produce `None` rather than raising — keeps journey handlers safe from third-party templates.
  - **`received_at`** prefers `data.message.received_at_utc` (microsecond), falls back to top-level `timestamp`, final fallback `datetime.now(UTC)`. ISO parser tolerates trailing `Z` and naive UTC strings.
  - Unknown free-text content type → `USER_TEXT` with `text=None` rather than raising; the raw row remains on disk for audit. Truly unknown event types (`type` not in the documented set) → `UnsupportedEventTypeError` (subclass of `NormalizationError`) so the worker can choose to mark-as-processed without retry.
- **Tests** (`tests/unit/test_normalizer.py`): 14 cases — text/QR-button/CTA-click happy paths, all 4 status events parametrised, failure-reason carry-through, country-code phone fallback, callback chain UUID parsing (valid/free-form/non-UUID-head), missing-id and missing-phone error paths, unsupported-type error.
- **Validation**: pytest 61/61 green; pre-commit (ruff, ruff-format, black, mypy, bandit) all clean. Zero `# type: ignore` and zero per-file mypy waivers added.
- **Decisions**:
  - Canonical event is `frozen=True` deliberately — handlers can't accidentally mutate fields the orchestrator depends on, and equality is structural.
  - `EventKind` is a `StrEnum` (not a `Literal`) so `match`/`isinstance` arms can use the enum members directly and logs show readable values.
  - The normalizer is **pure**: no time, no DB, no I/O, no logging side-effects. Logging belongs to the worker (Phase 5) so the same code path is testable end-to-end against any orchestrator.
- **Next**: Phase 5 — orchestrator. Replace `inbound_worker._run` body with: read from Redis stream → load `webhook_event_raw` row → `normalize(...)` → acquire `user:{full_phone}` Redis lock → dispatch by `event_kind` to the journey state machine. Mark row `processed_at` once the journey commits.

### 2026-05-10 — Phase 3 complete (Interakt webhook ingestion)
- **Cache layer** (`src/wabot/cache/`):
  - `client.py` — lazy singleton `Redis.from_url(..., decode_responses=False, socket_keepalive=True, health_check_interval=30, socket_connect_timeout=2.0)`. `redis_ping(timeout_seconds=1.0)` uses `asyncio.timeout`; failures logged at warning level with the URL **redacted** (`_redacted_url` strips creds before logging). `close_redis()` calls `aclose()` and clears the singleton.
  - `dedupe.py` — `WebhookDedupe.claim(key)` does `SET NX EX` with TTL = `settings.redis_dedupe_ttl_seconds` (default 600 s). `build_dedupe_key(event_type, interakt_message_id, message_status)` mirrors the DB partial unique index exactly (missing parts → `"-"` sentinel) so Redis fast-path and DB strong-path agree on identity.
- **Broker port** (`src/wabot/adapters/broker/`):
  - `base.py` — `InboundBroker` `Protocol` with `enqueue(*, partition_key, payload) -> str` and `close()`; `BrokerEnqueueError(RuntimeError)`.
  - `redis_streams.py` — `RedisStreamsBroker` writes to `XADD <stream> MAXLEN ~ 100_000` with fields `{"key": partition_key, "data": orjson.dumps(payload)}`. Any `RedisError` is wrapped as `BrokerEnqueueError`. `close()` is a no-op (Redis client lifecycle is owned by `wabot.cache.client`).
  - `factory.py` — lazy singleton `get_broker(settings)` switching on `settings.broker_backend` (`"redis_streams"` now; `"azure_servicebus"` raises `NotImplementedError` until Phase 13). `set_broker(...)` is a test seam.
- **Schema** (`src/wabot/api/schemas/interakt_webhook.py`): permissive Pydantic v2 envelope (`ConfigDict(extra="allow")`) so the raw row stays byte-faithful. Validates only the routing fields we actually consume:
  - `interakt_message_id` ← `data.message.id`
  - `message_status` ← `data.message.message_status`
  - `full_phone_number` prefers `customer.channel_phone_number`, falls back to `country_code.lstrip('+') + phone_number`.
  - Constants `EVENT_TYPE_API_SENT/DELIVERED/READ/FAILED/CLICKED/RECEIVED/TEMPLATE_STATUS` plus `KNOWN_EVENT_TYPES: frozenset` so unknown event types are still persisted but skip enqueue.
- **Router** (`src/wabot/api/routers/webhooks.py`): `POST /webhooks/{secret}/interakt`. Failure modes are explicit and final:
  1. **Wrong secret** → `secrets.compare_digest` mismatch → `HTTPException(404)` (no information leakage; indistinguishable from a wrong path).
  2. **Bad JSON / bad envelope** → `ValidationFailedError` → 400 with stable `{"error": {"code": "validation_failed", ...}}` envelope.
  3. **Redis dedupe pre-filter** — if `claim()` returns `False`, return `WebhookAckResponse(status="duplicate")` immediately, **without ever opening a DB connection**. Cache failures are tolerated (`is_first=True`) and logged at warning level.
  4. **DB write** runs inside a single short `session_scope()` calling `WebhookRepository.record_if_new(...)`. If `record_if_new` raises, log and return `WebhookAckResponse(status="ok", ...)` with HTTP 503 so Interakt retries (durable row is the source of truth, not the broker).
  5. **DB-side duplicate** (Redis missed but DB partial unique index caught it) → 200 + `status="duplicate"`, no enqueue.
  6. **Broker enqueue** runs **after** DB commit, **outside** `session_scope`, so the DB connection is never held while talking to Redis. Broker failures are logged but do not block the 200 ack — the row is durable and a future janitor will pick up `processed_at IS NULL`. Only enqueue when `event_type in KNOWN_EVENT_TYPES`.
- **Lifecycle wiring** (`main.py`, `workers/inbound_worker.py`): both processes prime `get_engine(settings)` and `get_redis(settings)` at startup so the first request never pays connection cost; on shutdown `close_broker(); close_redis(); dispose_engine()` in that order. `pool_pre_ping=True` + `pool_recycle=1800` from Phase 2 keep the SQLAlchemy pool healthy without idle leaks.
- **/readyz** (`api/routers/health.py`): now probes both DB and Redis via `asyncio.gather(db_ping(), redis_ping())`. Either failing → 503 with `status="degraded"` and `dependencies={"db": bool, "redis": bool}`.
- **DB hygiene checklist** (per user requirement "no unnecessary db connections will be open"):
  - One short transaction per webhook request; commit happens before the broker call.
  - Redis pre-filter eliminates DB hits on duplicate bursts (Interakt retries can hammer us).
  - Sessions never escape `session_scope()` (FastAPI dep also routes through it).
  - Engine + Redis client are singletons; opened once at lifespan startup, disposed once at shutdown.
  - Worker uses the same engine/redis singletons — no per-message connections.
- **Public URL for local testing**: cloudflared (`winget install --id Cloudflare.cloudflared`). One command: `cloudflared tunnel --url http://localhost:8000`. Register the resulting URL in Interakt as `https://<tunnel>/webhooks/<INTERAKT_WEBHOOK_PATH_SECRET>/interakt`.
- **Tests** (15 new):
  - `tests/unit/test_interakt_schema.py` — 6 cases covering routing-field extraction, country-code fallback, missing `type` rejection, unknown event acceptance, click-event preservation, extra-field byte-faithfulness.
  - `tests/unit/test_cache.py` — 2 cases covering `build_dedupe_key` agreement with the DB unique index.
  - `tests/unit/test_webhooks.py` — 6 cases (wrong secret 404; bad envelope 400; happy path persist+enqueue; Redis dedupe short-circuit with no DB/broker hit; DB-side duplicate with no enqueue; click event accepted).
  - `tests/unit/test_health.py` extended for the new `redis` dependency field.
- **Test infra fix**: added an autouse `_reset_structlog_after_test` fixture in `tests/conftest.py`. Without it, `test_logging.py` runs under `capsys`, which closes the captured stdout file at teardown; structlog's `PrintLoggerFactory` had cached that closed file and later tests that emitted log lines crashed with `ValueError: I/O operation on closed file`. The fixture calls `structlog.reset_defaults()` after every test so each one starts clean.
- **Tooling**: `pyproject.toml` mypy override added for `redis.*` (no first-party stubs in our pin: `redis==7.4.0`).
- **Validation**: `pytest -q` → 47/47 passing. `pre-commit run --all-files` → all hooks green (ruff legacy alias, ruff format, black, mypy strict, bandit).
- **Next**: Phase 4 — webhook normalizer to translate `webhook_event_raw` rows into the canonical event the orchestrator consumes (extract intent: text vs button vs status, attach `outbound_message_id` via `callbackData` chain, etc.).


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
