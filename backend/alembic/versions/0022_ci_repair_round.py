"""Persist the separate required-CI repair budget.

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-14
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the false-by-default CI repair round counter."""
    op.add_column(
        "workflow_run",
        sa.Column(
            "ci_repair_round", sa.Integer(), nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    """Remove the CI repair round counter."""
    op.drop_column("workflow_run", "ci_repair_round")
