# syntax=docker/dockerfile:1.7
# =============================================================================
# Wockhardt WhatsApp Bot — multi-stage image for FastAPI api & worker.
# Same image, two CMDs (selected via docker/entrypoints/{api,worker}.sh).
# =============================================================================

ARG PYTHON_VERSION=3.12.13

# ---------- Builder stage ----------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install .

# ---------- Runtime stage ----------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# Non-root user
RUN groupadd --system app && useradd --system --gid app --home /app --shell /sbin/nologin app

# Minimal runtime deps; ca-certificates for TLS to Azure PG / Interakt.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl tini \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app src/ /app/src/
COPY --chown=app:app docker/entrypoints/ /app/docker/entrypoints/
COPY --chown=app:app pyproject.toml README.md /app/
RUN chmod +x /app/docker/entrypoints/*.sh

USER app
EXPOSE 8000

# tini gives clean signal handling for uvicorn / worker loops.
ENTRYPOINT ["/usr/bin/tini", "--"]

# Default to API role; compose / Azure overrides for worker.
CMD ["/app/docker/entrypoints/api.sh"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1
