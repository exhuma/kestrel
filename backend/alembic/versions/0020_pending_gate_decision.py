"""Persist approval decisions until a workflow driver consumes them.

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-10
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the asynchronous gate-decision checkpoint to workflow runs."""
    op.add_column(
        "workflow_run",
        sa.Column("pending_gate_decision", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Remove the asynchronous gate-decision checkpoint."""
    op.drop_column("workflow_run", "pending_gate_decision")
