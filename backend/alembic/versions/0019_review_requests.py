"""Durable external gate review revisions.

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-10
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the revision-token ledger for external gate reviews."""
    op.create_table(
        "review_request",
        sa.Column("token", sa.Text(), primary_key=True),
        sa.Column(
            "workflow_id", sa.String(), sa.ForeignKey("workflow_run.id"),
            nullable=False,
        ),
        sa.Column("gate", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "uq_review_request_active_gate",
        "review_request",
        ["workflow_id", "gate"],
        unique=True,
        sqlite_where=sa.text("active = 1"),
    )


def downgrade() -> None:
    """Drop the revision-token ledger for external gate reviews."""
    op.drop_index("uq_review_request_active_gate", "review_request")
    op.drop_table("review_request")
