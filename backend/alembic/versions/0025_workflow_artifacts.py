"""Create the durable workflow-artifact cleanup ledger.

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-15
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create records for workflow-owned cleanup resources."""
    op.create_table(
        "workflow_artifact",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workflow_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("cleanup_mode", sa.String(), nullable=False),
        sa.Column(
            "state", sa.String(), nullable=False, server_default="pending"
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("cleaned_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow_run.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_workflow_artifact_workflow_id",
        "workflow_artifact",
        ["workflow_id"],
    )


def downgrade() -> None:
    """Remove the workflow-artifact cleanup ledger."""
    op.drop_index("ix_workflow_artifact_workflow_id", "workflow_artifact")
    op.drop_table("workflow_artifact")
