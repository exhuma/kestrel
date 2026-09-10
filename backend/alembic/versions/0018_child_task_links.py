"""Durable child-task links and source lifecycle state.

Each approved decomposition child has one row keyed by its source-native task
reference.  The row preserves its publishing parent, current child-run head,
and the last observed source state.  ``reopening`` is a short-lived claim that
prevents concurrent observations from creating duplicate successors.

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-10
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the child-task link table."""
    op.create_table(
        "child_task_link",
        sa.Column("task_ref", sa.Text(), primary_key=True),
        sa.Column(
            "parent_workflow_id", sa.String(),
            sa.ForeignKey("workflow_run.id"), nullable=False,
        ),
        sa.Column(
            "latest_workflow_id", sa.String(),
            sa.ForeignKey("workflow_run.id"), nullable=True,
        ),
        sa.Column("source_state", sa.Text(), nullable=False),
        sa.Column("source_generation", sa.Text(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("retired_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    """Drop the child-task link table."""
    op.drop_table("child_task_link")
