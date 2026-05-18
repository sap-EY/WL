#!/usr/bin/env sh
set -eu

exec python -m wabot.workers.status_worker
