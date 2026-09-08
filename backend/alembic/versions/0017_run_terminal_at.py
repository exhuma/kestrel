"""Terminal-transition timestamp column.

Adds ``workflow_run.terminal_at`` (nullable): when a run last entered a
terminal status (``done``/``failed``/``rejected``/``escalated``/
``decomposed``). Feature 013's feedback poll needs this to bound how long
after going terminal a run is still worth re-polling for review/ticket
feedback (``settings.feedback_window_days``) — without it, "poll every
`done` run forever" is the only alternative, an unbounded and ever-growing
cost for a long-lived deployment. No backfill: an already-terminal row's
window simply starts counting from the first save after this migration,
which is an acceptable one-time widening, not a correctness bug.

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-08
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add workflow_run.terminal_at.

    SQLite cannot ``ALTER TABLE ... ADD COLUMN`` with a constraint
    outside of batch mode — see ``0015_feedback.py``'s downgrade for the
    same pattern.
    """
    with op.batch_alter_table("workflow_run") as batch:
        batch.add_column(
            sa.Column("terminal_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    """Drop workflow_run.terminal_at."""
    with op.batch_alter_table("workflow_run") as batch:
        batch.drop_column("terminal_at")
