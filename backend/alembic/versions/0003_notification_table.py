"""Notification table.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-03
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the notification table."""
    op.create_table(
        "notification",
        sa.Column(
            "id", sa.Integer(), primary_key=True, autoincrement=True
        ),
        sa.Column(
            "workflow_id", sa.String(),
            sa.ForeignKey("workflow_run.id"), nullable=False,
        ),
        sa.Column("repo", sa.String(), nullable=False),
        sa.Column("issue_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("read", sa.Boolean(), nullable=False),
    )


def downgrade() -> None:
    """Drop the notification table."""
    op.drop_table("notification")
