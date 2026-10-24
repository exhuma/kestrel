"""Add ``board_workflow.task_body``/``approved_prd`` (feature 026, T078).

``task_body`` carries the task source's own body, safe-screened once at
intake — previously computed by quarantine screening and then discarded,
leaving every specialist (including the coordinator's own wake-up turn)
with nothing but a short display title. ``approved_prd`` is the PRD
content a ``prd_gate`` approves, read by every later card's envelope
alongside ``task_body``.

Revision ID: 0031
Revises: 0030
Create Date: 2026-09-27
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the columns, defaulting existing rows to empty/unset."""
    with op.batch_alter_table("board_workflow") as batch:
        batch.add_column(
            sa.Column(
                "task_body", sa.Text(), nullable=False, server_default=""
            )
        )
        batch.add_column(sa.Column("approved_prd", sa.Text(), nullable=True))


def downgrade() -> None:
    """Drop the columns."""
    with op.batch_alter_table("board_workflow") as batch:
        batch.drop_column("approved_prd")
        batch.drop_column("task_body")
