"""Workflow run and step tables.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-02
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the workflow_run and workflow_step tables."""
    op.create_table(
        "workflow_run",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("repo", sa.String(), nullable=False),
        sa.Column(
            "issue_number", sa.Integer(), nullable=False
        ),
        sa.Column("issue_title", sa.String(), nullable=False),
        sa.Column("base_branch", sa.String(), nullable=False),
        sa.Column("branch", sa.String(), nullable=False),
        sa.Column("workspace", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("pr_url", sa.String(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_table(
        "workflow_step",
        sa.Column(
            "workflow_id",
            sa.String(),
            sa.ForeignKey("workflow_run.id"),
            primary_key=True,
        ),
        sa.Column(
            "position", sa.Integer(), primary_key=True
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("deliverable", sa.Text(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
    )


def downgrade() -> None:
    """Drop the workflow tables."""
    op.drop_table("workflow_step")
    op.drop_table("workflow_run")
