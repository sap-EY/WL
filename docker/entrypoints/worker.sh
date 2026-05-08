#!/usr/bin/env sh
set -eu

# Worker process role. Real consumer loop lands in Phase 5.
# For Phase 0 the worker entrypoint just blocks so the container stays alive
# and proves the same image can run as either role.

exec python -m wabot.workers.inbound_worker
