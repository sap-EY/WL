"""Data-layer package.

Re-exports the small surface that callers should depend on:

- `Base`            : declarative base for ORM models.
- `WABOT_SCHEMA`    : the Postgres schema name.
- `get_engine`      : lazily-built async engine bound to `AppSettings`.
- `get_sessionmaker`: async sessionmaker (expire_on_commit=False).
- `session_scope`   : `async with` context manager for a transactional unit of work.
- `get_session`     : FastAPI dependency yielding a per-request session.
- `dispose_engine`  : called from app/worker shutdown hooks.

Models are imported eagerly from `wabot.data.models` so that
`Base.metadata` is fully populated before Alembic introspects it.
"""

from __future__ import annotations

from wabot.data import models as _models  # noqa: F401 - register mappers
from wabot.data.base import WABOT_SCHEMA, Base
from wabot.data.db import (
    dispose_engine,
    get_engine,
    get_session,
    get_sessionmaker,
    session_scope,
)

__all__ = [
    "WABOT_SCHEMA",
    "Base",
    "dispose_engine",
    "get_engine",
    "get_session",
    "get_sessionmaker",
    "session_scope",
]
