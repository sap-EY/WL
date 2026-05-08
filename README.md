# Wockhardt WhatsApp Bot

Production-grade WhatsApp orchestration layer for the Wockhardt LifeSciences chatbot.
Built on FastAPI + asyncpg + Redis, integrates with **Interakt** (WhatsApp BSP) and the
**GenAI** layer.

This README covers Phase 0 (repo bootstrap). For full architecture, sequencing,
and contracts see [implementation_plan.md](./implementation_plan.md). For the
canonical schema see [models.txt](./models.txt). For day-to-day progress see
[claude_memory.md](./claude_memory.md).

## Prerequisites
- Python **3.12.x**
- Docker Desktop (for `docker compose`)
- Access to the Azure PostgreSQL Flex server (host: `docbotdatabase.postgres.database.azure.com`)
- DBeaver (already used to apply `models.txt`)

## Local setup

```powershell
# 1. Configure environment
copy .env.example .env
# edit .env and set:
#   DB_PASSWORD=<your password>
#   INTERAKT_API_KEY=<base64 key>
#   INTERAKT_WEBHOOK_PATH_SECRET=<some long random string>

# 2. Create venv + install
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pre-commit install

# 3. Run tests
pytest

# 4. Run the API locally (no container)
uvicorn wabot.main:app --reload --port 8000
# then open  http://127.0.0.1:8000/healthz   and   http://127.0.0.1:8000/docs
```

## Run with Docker Compose

```powershell
docker compose build
docker compose up
# api      → http://127.0.0.1:8000/healthz
# worker   → idles cleanly until Phase 5
# redis    → localhost:6379
```

For fully offline work (rare — Postgres lives on Azure):
```powershell
docker compose --profile local-db up
```

## Project layout
See [implementation_plan.md §5](./implementation_plan.md). High-level:
- `src/wabot/api/` — FastAPI routers
- `src/wabot/domain/` — pure business logic (journeys, parsers, router)
- `src/wabot/services/` — orchestrator, pipelines
- `src/wabot/adapters/` — Interakt, GenAI, broker (ports + impls)
- `src/wabot/data/` — SQLAlchemy models + repositories
- `src/wabot/cache/` — Redis helpers (locks, dedupe, snapshots)
- `src/wabot/infra/` — config, logging, correlation, errors
- `src/wabot/workers/` — worker entrypoints

## Tooling
- **ruff** — lint + format (`ruff check .`, `ruff format .`)
- **black** — formatting backstop (`black .`)
- **mypy --strict** — type checking (`mypy src`)
- **pytest** — tests (`pytest`)
- **bandit** + **pip-audit** — security checks (run by pre-commit)

## Deployment target
- Azure App Service or AKS, two roles from one image:
  - api: `CMD ["/app/docker/entrypoints/api.sh"]`
  - worker: `CMD ["/app/docker/entrypoints/worker.sh"]`
- Azure PostgreSQL Flex (already provisioned)
- Azure Cache for Redis
- Azure Service Bus (queue) — selected via `BROKER_BACKEND=azure_servicebus`

## Phase status
See [claude_memory.md](./claude_memory.md) for the live status board.
