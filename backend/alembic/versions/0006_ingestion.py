"""GitHub ingestion: delivery dedup, issue dismissals, run source.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-21
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create ingestion tables and add ``workflow_run.source``."""
    op.create_table(
        "webhook_delivery",
        sa.Column("delivery_id", sa.String(), primary_key=True),
        sa.Column("event", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("repo", sa.String(), nullable=True),
        sa.Column("issue_number", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "issue_dismissal",
        sa.Column("repo", sa.String(), primary_key=True),
        sa.Column("issue_number", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.add_column(
        "workflow_run",
        sa.Column(
            "source",
            sa.String(),
            nullable=False,
            server_default="manual",
        ),
    )


def downgrade() -> None:
    """Drop the ingestion tables and the ``source`` column."""
    with op.batch_alter_table("workflow_run") as batch:
        batch.drop_column("source")
    op.drop_table("issue_dismissal")
    op.drop_table("webhook_delivery")
