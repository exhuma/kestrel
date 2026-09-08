"""Feedback intake tables.

Adds ``feedback_item`` (durable dedup ledger + mid-run queue, keyed by each
adapter's own opaque ``external_id`` — the same insert-if-absent pattern
``WebhookDeliveryRow``/``IssueDismissalRow`` already use) and
``feedback_cursor`` (per ticket/PR "how far read", tracked independently of
any single run so post-terminal feedback and a linked successor run can both
resolve it). Also adds ``workflow_run.pr_number`` (nullable INTEGER): the
missing PR-number index alongside the existing ``pr_url`` string column, set
by the new ``change_request_number(pr_url)`` helper — no backfill, existing
rows still resolve by matching on ``pr_url`` (see feature 013's
data-model.md).

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-07
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create feedback_item/feedback_cursor and add workflow_run.pr_number."""
    op.create_table(
        "feedback_item",
        sa.Column("external_id", sa.Text(), primary_key=True),
        sa.Column(
            "workflow_id", sa.String(),
            sa.ForeignKey("workflow_run.id"), nullable=True,
        ),
        sa.Column("task_ref", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("author", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("target_step", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_feedback_item_workflow_state",
        "feedback_item",
        ["workflow_id", "state"],
    )
    op.create_table(
        "feedback_cursor",
        sa.Column("scope", sa.Text(), primary_key=True),
        sa.Column("cursor", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.add_column(
        "workflow_run",
        sa.Column("pr_number", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    """Drop feedback_item/feedback_cursor and workflow_run.pr_number."""
    with op.batch_alter_table("workflow_run") as batch:
        batch.drop_column("pr_number")
    op.drop_table("feedback_cursor")
    op.drop_index(
        "ix_feedback_item_workflow_state", table_name="feedback_item"
    )
    op.drop_table("feedback_item")
