"""Initial session and event tables.

Revision ID: 0001
Revises:
Create Date: 2026-07-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the session and event tables."""
    op.create_table(
        "session",
        sa.Column("session_id", sa.String(), primary_key=True),
        sa.Column("cwd", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
    )
    op.create_table(
        "event",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "session_id",
            sa.String(),
            sa.ForeignKey("session.session_id"),
            nullable=False,
        ),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("raw", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    """Drop the event and session tables."""
    op.drop_table("event")
    op.drop_table("session")
