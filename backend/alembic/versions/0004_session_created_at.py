"""Session created_at column.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-03
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add a nullable created_at to the session table.

    Nullable so rows written before this column existed load cleanly
    (their timestamp is simply unknown).
    """
    op.add_column(
        "session",
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    """Drop the session.created_at column."""
    op.drop_column("session", "created_at")
