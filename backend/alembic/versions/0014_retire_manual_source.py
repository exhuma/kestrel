"""Retire the "manual" run origin.

Feature 010 removed manual repo+issue entry from the UI and the
``POST /api/workflows`` endpoint it fed, so every run now originates from a
task source (ingestion) or from a rerun. Existing ``source = 'manual'`` rows
are factually GitHub runs — their ``repo`` is a GitHub repository and their
``task_ref`` is ``owner/name#n`` — so they are relabelled ``github-issue``,
which is also what the removed ``"manual"`` adapter mapping resolved to.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-31
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Relabel "manual" runs as GitHub runs and move the server-default."""
    op.execute(
        "UPDATE workflow_run SET source = 'github-issue' "
        "WHERE source = 'manual'"
    )
    with op.batch_alter_table("workflow_run") as batch:
        batch.alter_column(
            "source",
            existing_type=sa.String(),
            existing_nullable=False,
            server_default="github-issue",
        )


def downgrade() -> None:
    """Restore the "manual" server-default.

    The relabelling is deliberately not reversed: a run's original origin is
    unrecoverable once merged into ``github-issue``, and ``"manual"`` and
    ``"github-issue"`` bound the same adapters anyway.
    """
    with op.batch_alter_table("workflow_run") as batch:
        batch.alter_column(
            "source",
            existing_type=sa.String(),
            existing_nullable=False,
            server_default="manual",
        )
