"""Workflow run boundary classification.

Adds ``workflow_run.boundary`` — the project's user-facing boundary
("http" | "ui" | "both" | "none"), classified once by the design step and
reused by every verify round of a run (feature 005). Nullable, no backfill:
every existing run simply gets NULL, which verify treats the same as "none"
(today's check-and-diff-judgment behaviour, unchanged).

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-24
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the nullable boundary column."""
    op.add_column(
        "workflow_run",
        sa.Column("boundary", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Drop the boundary column."""
    with op.batch_alter_table("workflow_run") as batch:
        batch.drop_column("boundary")
