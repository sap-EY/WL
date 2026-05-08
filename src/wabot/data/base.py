"""SQLAlchemy declarative base.

A single `Base` class is shared by every ORM model in
`wabot.data.models`. The `MetaData` is bound to the `wabot` schema so
`Table.__tablename__` does not need a per-table `schema=` kwarg, and the
naming convention below makes Alembic-generated index/constraint names
deterministic across environments.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Schema name is hard-coded to keep the ORM aligned with `models.txt`. If we
# ever need to override it (multi-tenant tests, etc.), we'll inject via env
# at engine creation time, not here.
WABOT_SCHEMA = "wabot"

metadata = MetaData(schema=WABOT_SCHEMA, naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    """Common base for every wabot ORM model."""

    metadata = metadata
