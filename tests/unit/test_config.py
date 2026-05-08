"""Verify settings resolution and DSN assembly."""

from __future__ import annotations

import os
from urllib.parse import quote_plus

from wabot.infra.config import AppSettings, get_settings


def test_dsn_is_assembled_from_components(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DB_HOST", "docbotdatabase.postgres.database.azure.com")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_USER", "drbot_admin")
    monkeypatch.setenv("DB_PASSWORD", "S3cret!@#")
    monkeypatch.setenv("DB_NAME", "postgres")
    monkeypatch.setenv("DB_SSL_MODE", "require")

    get_settings.cache_clear()
    s = get_settings()
    assert isinstance(s, AppSettings)

    assert quote_plus("S3cret!@#") in s.db_dsn
    assert "drbot_admin" in s.db_dsn
    assert "docbotdatabase.postgres.database.azure.com" in s.db_dsn
    assert s.db_dsn.endswith("?ssl=require")

    # Logging form must NOT contain the password.
    assert "S3cret" not in s.db_dsn_for_logging
    assert "***" in s.db_dsn_for_logging


def test_default_environment_is_local() -> None:
    get_settings.cache_clear()
    os.environ.pop("APP_ENV", None)
    s = get_settings()
    assert s.env == "local"
