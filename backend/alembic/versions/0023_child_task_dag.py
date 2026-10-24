"""Persist published child task-DAG scheduling metadata.

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-14
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add DAG identities and the parent feature integration branch."""
    op.add_column(
        "child_task_link", sa.Column("task_node_id", sa.Text(), nullable=True)
    )
    op.add_column(
        "child_task_link",
        sa.Column(
            "prerequisites", sa.Text(), nullable=False, server_default="[]"
        ),
    )
    op.add_column(
        "child_task_link",
        sa.Column(
            "integration_branch", sa.Text(), nullable=False, server_default=""
        ),
    )


def downgrade() -> None:
    """Remove child task-DAG scheduling metadata."""
    op.drop_column("child_task_link", "integration_branch")
    op.drop_column("child_task_link", "prerequisites")
    op.drop_column("child_task_link", "task_node_id")
