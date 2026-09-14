"""Persist explicit PRD approval provenance on workflow runs.

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-14
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the false-by-default PRD approval provenance flag."""
    op.add_column(
        "workflow_run",
        sa.Column(
            "prd_approved", sa.Boolean(), nullable=False, server_default="0"
        ),
    )


def downgrade() -> None:
    """Remove the PRD approval provenance flag."""
    op.drop_column("workflow_run", "prd_approved")
