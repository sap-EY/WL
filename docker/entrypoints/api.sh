#!/usr/bin/env sh
set -eu

: "${APP_HTTP_PORT:=8000}"
: "${APP_ENV:=local}"

if [ "${APP_ENV}" = "local" ]; then
  exec uvicorn wabot.main:app \
    --host 0.0.0.0 \
    --port "${APP_HTTP_PORT}" \
    --reload \
    --proxy-headers
else
  exec gunicorn wabot.main:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers "${WEB_CONCURRENCY:-2}" \
    --bind "0.0.0.0:${APP_HTTP_PORT}" \
    --timeout 30 \
    --graceful-timeout 30 \
    --access-logfile - \
    --forwarded-allow-ips "*"
fi
