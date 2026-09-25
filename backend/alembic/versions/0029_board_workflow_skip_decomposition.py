"""Add ``board_workflow.skip_decomposition`` (feature 026, T068).

Set once at ingestion from the source task's own body
(``has_subtask_sentinel``): a task Kestrel itself published as a
decomposition child must never be forced through decomposition again,
regardless of ``board_decomposition_required`` — otherwise a
required-decomposition deployment would recurse into a child's children
forever.

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-27
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the column, defaulting existing rows to ``False``."""
    with op.batch_alter_table("board_workflow") as batch:
        batch.add_column(
            sa.Column(
                "skip_decomposition",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    """Drop the column."""
    with op.batch_alter_table("board_workflow") as batch:
        batch.drop_column("skip_decomposition")
