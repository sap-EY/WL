"""Alembic environment for wabot.

Reads the database URL from `wabot.infra.config.AppSettings` so secrets
never live in `alembic.ini`. Supports both online (autogenerate, upgrade)
and offline (SQL emit) modes, async-engine backed.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import TYPE_CHECKING

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

# Import models so every mapper is registered on `target_metadata`.
import wabot.data.models  # noqa: F401

# Load the wabot settings + metadata.
from wabot.data.base import WABOT_SCHEMA
from wabot.data.base import metadata as target_metadata
from wabot.infra.config import get_settings

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.db_dsn)


def _include_object(obj, name, type_, reflected, compare_to):  # type: ignore[no-untyped-def]
    """Restrict autogenerate to the wabot schema."""
    return not (type_ == "table" and getattr(obj, "schema", None) not in (None, WABOT_SCHEMA))


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it."""
    context.configure(
        url=settings.db_dsn,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=WABOT_SCHEMA,
        include_schemas=True,
        include_object=_include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema=WABOT_SCHEMA,
        include_schemas=True,
        include_object=_include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
