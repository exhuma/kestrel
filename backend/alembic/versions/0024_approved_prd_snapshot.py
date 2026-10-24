"""Persist the immutable PRD accepted for each workflow run.

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-14
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the accepted PRD snapshot without inventing legacy provenance."""
    op.add_column(
        "workflow_run", sa.Column("approved_prd", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    """Remove the accepted PRD snapshot column."""
    op.drop_column("workflow_run", "approved_prd")
