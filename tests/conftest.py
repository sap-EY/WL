"""Pytest configuration shared across the test tree.

The environment variables below are set unconditionally (overriding any
`.env` the developer may have at the repo root) so the suite is
hermetic and never accidentally talks to a real database, Redis, or
Interakt. Tests that need to hit a real DB must opt in explicitly via
their own fixtures.
"""

from __future__ import annotations

import os

_TEST_ENV = {
    "APP_ENV": "local",
    "APP_LOG_JSON": "false",
    "DB_HOST": "localhost",
    "DB_PORT": "5432",
    "DB_USER": "test",
    "DB_PASSWORD": "test",
    "DB_NAME": "test",
    "DB_SCHEMA": "wabot",
    "DB_SSL_MODE": "disable",
    "REDIS_URL": "redis://localhost:6379/0",
    "INTERAKT_WEBHOOK_PATH_SECRET": "unit-test-secret",
}
for _key, _value in _TEST_ENV.items():
    os.environ[_key] = _value

# Clear the settings cache so the overrides above take effect even if a
# previous import already populated the lru_cache.
from wabot.infra.config import get_settings  # noqa: E402

get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Logging hygiene
# ---------------------------------------------------------------------------
# `wabot.infra.logging.configure_logging` binds `sys.stdout` into structlog's
# `PrintLoggerFactory` at call time. Tests like `test_logging.py` invoke it
# under `capsys`, which swaps stdout for a temporary buffer that pytest closes
# at the end of the test. Without an explicit reset, every later test that
# logs (e.g. the webhook router's exception path) writes to a closed file and
# raises `ValueError: I/O operation on closed file`. We therefore reset
# structlog's configuration after every test so each one starts from a clean
# slate that re-binds to the live `sys.stdout`.
import pytest  # noqa: E402
import structlog  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_structlog_after_test() -> object:
    yield
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()
