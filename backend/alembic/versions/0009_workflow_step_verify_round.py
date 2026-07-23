"""Workflow step verify_round column.

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-22
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add a durable code↔verify iteration counter to workflow_step.

    Non-nullable with a server default of 0 so existing rows (steps
    already persisted before this column existed) load cleanly. Drives
    the verify chip's "remaining runs" indicator in the UI.
    """
    op.add_column(
        "workflow_step",
        sa.Column(
            "verify_round", sa.Integer(), nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    """Drop the workflow_step.verify_round column."""
    op.drop_column("workflow_step", "verify_round")
