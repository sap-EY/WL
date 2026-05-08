"""Async engine, sessionmaker, and unit-of-work helpers.

Design choices:
- Single process-wide `AsyncEngine`, lazily created on first call to
  `get_engine()`. Pool size and SSL mode come from `AppSettings`.
- `expire_on_commit=False` so ORM objects remain usable after `commit()`
  inside FastAPI handlers and worker tasks (we hand off to background
  tasks frequently).
- `session_scope()` is the canonical unit of work: it commits on success
  and rolls back on any exception. Use this for writes from services.
- `get_session()` is the FastAPI dependency for read-mostly handlers
  where per-call commit/rollback semantics are explicit.
- `_apply_session_settings` is a per-connection hook that pins the
  `search_path` to `wabot` and applies `statement_timeout`. We register
  it via the engine's `connect` event so it fires once per pooled
  connection.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from wabot.infra.config import AppSettings, get_settings
from wabot.infra.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _build_engine(settings: AppSettings) -> AsyncEngine:
    engine = create_async_engine(
        settings.db_dsn,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_pool_max_overflow,
        pool_pre_ping=True,
        pool_recycle=1800,
        future=True,
    )

    statement_timeout_ms = settings.db_statement_timeout_ms
    schema = settings.db_schema

    @event.listens_for(engine.sync_engine, "connect")
    def _apply_session_settings(dbapi_conn: Any, _record: Any) -> None:
        # asyncpg connection: use a short sync cursor for SET LOCAL/SET.
        cur = dbapi_conn.cursor()
        try:
            cur.execute(f"SET search_path TO {schema}, public")
            cur.execute(f"SET statement_timeout = {statement_timeout_ms}")
        finally:
            cur.close()

    logger.info(
        "wabot.db.engine_created",
        dsn=settings.db_dsn_for_logging,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_pool_max_overflow,
        statement_timeout_ms=statement_timeout_ms,
    )
    return engine


def get_engine(settings: AppSettings | None = None) -> AsyncEngine:
    """Return the process-wide async engine, creating it on first use."""
    global _engine, _sessionmaker  # noqa: PLW0603 - cached singletons
    if _engine is None:
        settings = settings or get_settings()
        _engine = _build_engine(settings)
        _sessionmaker = async_sessionmaker(
            bind=_engine,
            expire_on_commit=False,
            autoflush=False,
            class_=AsyncSession,
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide async sessionmaker."""
    if _sessionmaker is None:
        get_engine()
    if _sessionmaker is None:  # pragma: no cover - guard for type narrowing
        msg = "Async sessionmaker failed to initialize"
        raise RuntimeError(msg)
    return _sessionmaker


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Transactional unit of work. Commits on success, rolls back on error."""
    sm = get_sessionmaker()
    async with sm() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session without an implicit commit.

    Handlers should call `await session.commit()` themselves when they
    intend to persist changes; otherwise the session is rolled back on
    exit. This keeps read endpoints free of accidental writes.
    """
    sm = get_sessionmaker()
    async with sm() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def ping(timeout_seconds: float = 2.0) -> bool:
    """Cheap readiness probe; returns True iff `SELECT 1` succeeds."""
    engine = get_engine()
    try:
        async with asyncio.timeout(timeout_seconds), engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning("wabot.db.ping_failed", error=str(exc))
        return False


async def dispose_engine() -> None:
    """Dispose the engine and clear the singleton (idempotent)."""
    global _engine, _sessionmaker  # noqa: PLW0603 - cached singletons
    if _engine is not None:
        await _engine.dispose()
        logger.info("wabot.db.engine_disposed")
    _engine = None
    _sessionmaker = None
