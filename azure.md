# Azure Deployment Notes

## Required Azure Services

- **Azure App Service for Containers**: hosts the same Docker image in separate process roles: API and worker.
- **Azure Container Registry**: stores the built Docker image used by App Service.
- **Azure Database for PostgreSQL Flexible Server**: existing `wabot` schema and application data store.
- **Azure Cache for Redis**: dedupe keys, per-user locks, hot cache, and local-compatible Redis behavior.
- **Azure Service Bus**: production queue backend with sessions for per-user ordering.
- **Azure Key Vault**: stores DB password, Interakt API key, webhook path secret, GenAI key, Service Bus connection details, and other secrets.
- **Application Insights / Azure Monitor / Log Analytics**: logs, traces, metrics, alerts, and dashboarding.

## Webhook Setup

Interakt needs a public HTTPS endpoint. With Azure App Service, the endpoint is the API app's HTTPS hostname plus the existing FastAPI route:

```text
https://<app-name>.azurewebsites.net/webhooks/<INTERAKT_WEBHOOK_PATH_SECRET>/interakt
```

Example:

```text
https://wabot-api-prod.azurewebsites.net/webhooks/3d080e69-c939-4c6b-9ec0-22df2c7a2065/interakt
```

How it works:

- Interakt sends webhook payloads to that URL.
- Azure App Service terminates HTTPS and forwards the request to the FastAPI container.
- `src/wabot/api/routers/webhooks.py` handles `POST /webhooks/{secret}/interakt`.
- The route compares `{secret}` with `INTERAKT_WEBHOOK_PATH_SECRET` from environment/Key Vault.
- Valid payloads are persisted in `webhook_event_raw`, deduped, and enqueued for worker processing.
- Wrong secrets return 404.

No separate gateway or local public tunneling service is required for production. Local testing remains simulation-based with `scripts/drive_webhook.py`.

## Queue Plan

The broker abstraction now supports named logical queues. Locally, each queue maps to a Redis Stream; in Azure, `BROKER_BACKEND=azure_servicebus` maps the same logical queues to Azure Service Bus queues with sessions keyed by `full_phone_number` for per-user ordering.

Implemented queue topology:

| Queue | Required | Session key | Notes |
|---|---:|---|---|
| `SERVICEBUS_QUEUE_INBOUND` / `wabot-inbound` | Yes | `full_phone_number` | User message and Flow response events after raw DB persistence. Consumed by `wabot.workers.inbound_worker`. |
| `SERVICEBUS_QUEUE_STATUS` / `wabot-status` | Yes | `full_phone_number` | Interakt sent/delivered/read/failed/clicked lifecycle events. Consumed by `wabot.workers.status_worker`. |
| `SERVICEBUS_QUEUE_GENAI` / `wabot-genai` | Reserved | `full_phone_number` | Configured now so Phase 9+ can split GenAI processing later without changing broker/config shape. Current worker still calls the fake GenAI port inline. |
| `SERVICEBUS_QUEUE_OUTBOUND` / `wabot-outbound` | Reserved | `full_phone_number` | Configured now for future outbound send worker separation. Current code sends outbound messages inline after journey commit. |
| Retry handling | Built-in first | varies | Prefer Service Bus scheduled delivery, max delivery count, lock renewal, and each queue's built-in DLQ before adding a custom `retry_queue`. |
| Poison handling | Built-in first | varies | Prefer each queue's built-in DLQ before adding a separate `dead_letter` / `poison_queue`. |

The user's proposed five queues are directionally right, but the status queue is the important production queue for Phase 10, and Azure Service Bus already provides DLQs so a standalone poison queue is not mandatory.

## Observability

- `/metrics` exposes Prometheus-compatible text metrics when `METRICS_ENABLED=true`.
- Logs remain structured through `structlog` and include queue/event/status fields on the webhook and worker paths.
- Azure Monitor bootstrap is controlled by `OTEL_ENABLED=true` and `APPLICATIONINSIGHTS_CONNECTION_STRING`; local and test runs leave it disabled.
