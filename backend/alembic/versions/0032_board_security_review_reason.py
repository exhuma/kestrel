"""Add ``board_security_review.reason`` (feature 026, T079).

The deterministic/classifier's own short, safe explanation of *why*
content was quarantined was already computed (``ClassificationResult.
reason``) but silently discarded before it ever reached the review
record — an operator deciding release vs. discard had no way to see it.

Revision ID: 0032
Revises: 0031
Create Date: 2026-09-27
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the column, defaulting existing rows to unset."""
    with op.batch_alter_table("board_security_review") as batch:
        batch.add_column(sa.Column("reason", sa.Text(), nullable=True))


def downgrade() -> None:
    """Drop the column."""
    with op.batch_alter_table("board_security_review") as batch:
        batch.drop_column("reason")
