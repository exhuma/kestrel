"""Sub-tasks as cards inside the parent workflow (feature 031).

Adds ``board_card.task_node_id``: the approved-decomposition task a card
works on (research R2). ``NULL`` for every card not created from, or on
behalf of, an approved CAB-2 task.

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
    """Add the column, defaulting existing rows to unset."""
    with op.batch_alter_table("board_card") as batch:
        batch.add_column(
            sa.Column("task_node_id", sa.Text(), nullable=True)
        )


def downgrade() -> None:
    """Drop the column."""
    with op.batch_alter_table("board_card") as batch:
        batch.drop_column("task_node_id")
