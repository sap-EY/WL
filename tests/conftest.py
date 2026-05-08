"""Pytest configuration shared across the test tree."""

from __future__ import annotations

import os

# Ensure tests use a deterministic config without relying on developer .env.
os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("APP_LOG_JSON", "false")
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("DB_SCHEMA", "wabot")
os.environ.setdefault("DB_SSL_MODE", "disable")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
