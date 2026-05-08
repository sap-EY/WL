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
}
for _key, _value in _TEST_ENV.items():
    os.environ[_key] = _value

# Clear the settings cache so the overrides above take effect even if a
# previous import already populated the lru_cache.
from wabot.infra.config import get_settings  # noqa: E402

get_settings.cache_clear()
