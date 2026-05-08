"""Smoke tests for the data.db engine helpers (no live DB required)."""

from __future__ import annotations

import pytest

from wabot.data import db as db_module


@pytest.fixture(autouse=True)
def _reset_engine_singletons() -> None:
    db_module._engine = None
    db_module._sessionmaker = None


def test_get_engine_caches_singleton() -> None:
    e1 = db_module.get_engine()
    e2 = db_module.get_engine()
    assert e1 is e2
    sm1 = db_module.get_sessionmaker()
    sm2 = db_module.get_sessionmaker()
    assert sm1 is sm2


@pytest.mark.asyncio
async def test_dispose_engine_clears_singletons() -> None:
    db_module.get_engine()
    assert db_module._engine is not None
    await db_module.dispose_engine()
    assert db_module._engine is None
    assert db_module._sessionmaker is None


@pytest.mark.asyncio
async def test_ping_returns_false_when_db_unreachable() -> None:
    # Conftest config points DB at localhost; readiness probe must fail
    # gracefully without raising.
    assert (await db_module.ping(timeout_seconds=0.5)) is False
    await db_module.dispose_engine()
