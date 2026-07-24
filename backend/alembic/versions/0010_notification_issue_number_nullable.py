"""Make ``notification.issue_number`` nullable.

A Jira-sourced run has no numeric issue id, so its gate/terminal notifications
carry ``issue_number = NULL``. The column was created NOT NULL (feature 002,
GitHub-only), which made every Jira notification fail to persist.

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-24
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Relax ``notification.issue_number`` to nullable."""
    with op.batch_alter_table("notification") as batch:
        batch.alter_column(
            "issue_number", existing_type=sa.Integer(), nullable=True
        )


def downgrade() -> None:
    """Restore NOT NULL (drops Jira rows that have no numeric id)."""
    op.execute("DELETE FROM notification WHERE issue_number IS NULL")
    with op.batch_alter_table("notification") as batch:
        batch.alter_column(
            "issue_number", existing_type=sa.Integer(), nullable=False
        )
