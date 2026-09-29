"""Sub-tasks as cards inside the parent workflow (feature 031).

- Adds ``board_card.task_node_id``: the approved-decomposition task a
  card works on (research R2). ``NULL`` for every card not created
  from, or on behalf of, an approved CAB-2 task.
- Drops ``board_workflow.skip_decomposition`` (0029) and the
  ``child_task_link`` table (0018/0023): approved tasks are no longer
  published as child tickets, so nothing records or reads either (the
  clean break, research R12). Their rows are discarded.

Downgrade re-creates the dropped column (every row ``False``) and the
table (empty) with their shapes as of 0032, minus the foreign keys 0018
declared (never enforced: SQLite's ``foreign_keys`` pragma is off, see
0028); it cannot restore the discarded rows.

Revision ID: 0033
Revises: 0032
Create Date: 2026-09-29
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the card column; drop the child-ticket bookkeeping."""
    with op.batch_alter_table("board_card") as batch:
        batch.add_column(
            sa.Column("task_node_id", sa.Text(), nullable=True)
        )
    with op.batch_alter_table("board_workflow") as batch:
        batch.drop_column("skip_decomposition")
    op.drop_table("child_task_link")


def downgrade() -> None:
    """Restore the pre-031 schema (not its discarded rows)."""
    op.create_table(
        "child_task_link",
        sa.Column("task_ref", sa.Text(), primary_key=True),
        sa.Column("parent_workflow_id", sa.String(), nullable=False),
        sa.Column("latest_workflow_id", sa.String(), nullable=True),
        sa.Column("source_state", sa.Text(), nullable=False),
        sa.Column("source_generation", sa.Text(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("retired_at", sa.DateTime(), nullable=True),
        sa.Column("task_node_id", sa.Text(), nullable=True),
        sa.Column(
            "prerequisites", sa.Text(), nullable=False, server_default="[]"
        ),
        sa.Column(
            "integration_branch", sa.Text(), nullable=False,
            server_default="",
        ),
    )
    with op.batch_alter_table("board_workflow") as batch:
        batch.add_column(
            sa.Column(
                "skip_decomposition", sa.Boolean(), nullable=False,
                server_default="0",
            )
        )
    with op.batch_alter_table("board_card") as batch:
        batch.drop_column("task_node_id")
