"""Add `mci_id` column to wabot.doctor.

Phase-7 pivot: registration moves to a WhatsApp Flow form and the
form collects an optional Medical Council of India registration id.

Revision ID: 0002_mci_id
Revises: 0001_init
Create Date: 2026-05-10
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_mci_id"
down_revision: str | None = "0001_init"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE wabot.doctor ADD COLUMN IF NOT EXISTS mci_id TEXT;")


def downgrade() -> None:
    op.execute("ALTER TABLE wabot.doctor DROP COLUMN IF EXISTS mci_id;")
