"""Workflow step refine_round column.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add a durable monotonic round counter to workflow_step.

    Non-nullable with a server default of 0 so existing rows (steps
    already persisted before this column existed) load cleanly. This
    is the dedicated, queryable marker used to distinguish a genuine
    refine-questionnaire change from a no-op update.
    """
    op.add_column(
        "workflow_step",
        sa.Column(
            "refine_round", sa.Integer(), nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    """Drop the workflow_step.refine_round column."""
    op.drop_column("workflow_step", "refine_round")
