"""Smoke tests for the structlog configuration."""

from __future__ import annotations

import json
import logging

import structlog

from wabot.infra.config import get_settings
from wabot.infra.logging import configure_logging, get_logger


def test_configure_logging_sets_level_and_global_meta(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("APP_LOG_LEVEL", "INFO")
    monkeypatch.setenv("APP_LOG_JSON", "true")
    get_settings.cache_clear()

    configure_logging(get_settings())
    logger = get_logger("test")
    logger.info("hello", extra_field="value")

    out = capsys.readouterr().out.strip().splitlines()
    assert out, "no log line emitted"
    payload = json.loads(out[-1])
    assert payload["event"] == "hello"
    assert payload["level"] == "info"
    assert payload["extra_field"] == "value"
    assert payload["app"] == "wabot"
    assert payload["env"] in {"local", "dev", "staging", "prod"}
    assert "ts" in payload and "T" in payload["ts"]
    assert logging.getLogger().level == logging.INFO

    # Reset structlog so other tests don't see leaked context.
    structlog.contextvars.clear_contextvars()
