"""Add ``board_workflow`` CI-repair columns (feature 026, T052).

Tracks a delivered workflow's change request and required-CI outcome so
a periodic poll can repair a failing check (bounded by
``max_ci_repair_iterations``) or escalate once that budget is exhausted.

Revision ID: 0030
Revises: 0029
Create Date: 2026-09-27
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the columns, defaulting existing rows to unset/zero."""
    with op.batch_alter_table("board_workflow") as batch:
        batch.add_column(
            sa.Column("change_request_number", sa.Integer(), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "ci_repair_round",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(sa.Column("ci_status", sa.Text(), nullable=True))


def downgrade() -> None:
    """Drop the columns."""
    with op.batch_alter_table("board_workflow") as batch:
        batch.drop_column("ci_status")
        batch.drop_column("ci_repair_round")
        batch.drop_column("change_request_number")
