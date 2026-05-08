"""Shared SQLAlchemy column types and mixins.

Centralised so the ORM uses one consistent representation for
TIMESTAMPTZ(6) and JSONB across every table.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Enum as SAEnum
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

# Postgres `TIMESTAMPTZ(6)` — microsecond precision, timezone-aware.
TimestampTZ = TIMESTAMP(timezone=True, precision=6)

# Postgres `JSONB` (preferred over JSON for indexing + storage compactness).
JsonB = JSONB()

# Postgres `UUID` mapped to `uuid.UUID`.
UuidPg = UUID(as_uuid=True)


def pg_enum(py_enum: type[Any], name: str) -> SAEnum:
    """Bind a Python `Enum` to an existing Postgres ENUM in `wabot`.

    `create_type=False` keeps SQLAlchemy from trying to create the type
    (the SQL migration owns it). `values_callable` makes the ENUM use
    the Python value strings (e.g. ``"REGISTRATION_COMPLETED"``)
    instead of the Python member names.
    """
    return SAEnum(
        py_enum,
        name=name,
        schema="wabot",
        native_enum=True,
        create_type=False,
        values_callable=lambda e: [m.value for m in e],
    )


def created_at_column() -> Mapped[datetime]:
    return mapped_column(
        TimestampTZ,
        nullable=False,
        server_default=text("clock_timestamp()"),
    )


def updated_at_column() -> Mapped[datetime]:
    """`updated_at` is maintained by the `set_updated_at` DB trigger."""
    return mapped_column(
        TimestampTZ,
        nullable=False,
        server_default=text("clock_timestamp()"),
    )


def uuid_pk_column() -> Mapped[uuid.UUID]:
    return mapped_column(
        UuidPg,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
