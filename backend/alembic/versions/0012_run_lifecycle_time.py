"""Workflow run active/wait time tracking.

Adds ``workflow_run.active_seconds``/``wait_seconds`` (cumulative,
feature 006) and ``clock_state``/``clock_since`` (which clock is
currently running, and since when). Nullable/server-defaulted, no
backfill: every existing run simply starts at ``0.0``/``NULL``, which
the dispatcher treats as "no time tracked yet" — the same
no-backfill pattern as ``0011_workflow_run_boundary.py``.

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-27
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the active/wait-time columns."""
    op.add_column(
        "workflow_run",
        sa.Column(
            "active_seconds",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "workflow_run",
        sa.Column(
            "wait_seconds", sa.Float(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "workflow_run", sa.Column("clock_state", sa.Text(), nullable=True)
    )
    op.add_column(
        "workflow_run",
        sa.Column("clock_since", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    """Drop the active/wait-time columns."""
    with op.batch_alter_table("workflow_run") as batch:
        batch.drop_column("clock_since")
        batch.drop_column("clock_state")
        batch.drop_column("wait_seconds")
        batch.drop_column("active_seconds")
