"""Workflow artifact directory: per-run step-handover folder.

Adds ``workflow_run.artifact_dir`` — the worktree-relative
``.kestrel/<YYYY-MM-DD>-<serial>/`` directory holding a run's PRD/design
handover files (written to the shared worktree and committed with the change).
Server-default "" keeps pre-existing rows valid; it stays empty for historical
runs whose worktrees are gone.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-22
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the nullable artifact_dir column (server-default empty)."""
    op.add_column(
        "workflow_run",
        sa.Column(
            "artifact_dir", sa.Text(), nullable=True, server_default=""
        ),
    )


def downgrade() -> None:
    """Drop the artifact_dir column."""
    with op.batch_alter_table("workflow_run") as batch:
        batch.drop_column("artifact_dir")
