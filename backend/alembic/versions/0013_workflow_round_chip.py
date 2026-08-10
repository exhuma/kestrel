"""Workflow round chip history.

Adds the ``workflow_round_chip`` table: a durable history trail of
session chips, written once a step's live chip set is retired (cleared
or replaced), so a completed round's chips stay visible across a page
reload or backend restart. This is additive and separate from the
existing ephemeral ``active_sessions`` telemetry (never persisted) — no
existing table changes.

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-30
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the workflow_round_chip table."""
    op.create_table(
        "workflow_round_chip",
        sa.Column(
            "id", sa.Integer(), primary_key=True, autoincrement=True
        ),
        sa.Column(
            "workflow_id", sa.String(),
            sa.ForeignKey("workflow_run.id"), nullable=False,
        ),
        sa.Column("step_name", sa.String(), nullable=False),
        sa.Column("round_index", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column(
            "badge", sa.String(), nullable=False, server_default="sys"
        ),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("retired_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_workflow_round_chip_workflow_step",
        "workflow_round_chip",
        ["workflow_id", "step_name"],
    )


def downgrade() -> None:
    """Drop the workflow_round_chip table."""
    op.drop_index(
        "ix_workflow_round_chip_workflow_step",
        table_name="workflow_round_chip",
    )
    op.drop_table("workflow_round_chip")
