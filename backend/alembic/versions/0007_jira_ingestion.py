"""Jira ingestion: source-neutral task_ref identity.

Adds ``workflow_run.task_ref`` (backfilled from ``repo#issue_number``),
makes ``workflow_run.issue_number`` nullable (Jira runs have no numeric id),
and re-keys ``issue_dismissal`` from ``(repo, issue_number)`` to a single
``task_ref`` primary key (feature 003, FR-024/FR-033/FR-037).

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-21
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add task_ref, make issue_number nullable, re-key dismissals."""
    # workflow_run: add task_ref (server_default keeps existing rows valid),
    # then backfill it for the pre-existing GitHub/manual rows.
    op.add_column(
        "workflow_run",
        sa.Column(
            "task_ref", sa.String(), nullable=False, server_default=""
        ),
    )
    op.execute(
        "UPDATE workflow_run SET task_ref = repo || '#' || issue_number "
        "WHERE task_ref = '' AND issue_number IS NOT NULL"
    )
    with op.batch_alter_table("workflow_run") as batch:
        batch.alter_column(
            "issue_number", existing_type=sa.Integer(), nullable=True
        )

    # issue_dismissal: rebuild with a single task_ref PK, backfilling from
    # the old (repo, issue_number) composite.
    op.create_table(
        "issue_dismissal_new",
        sa.Column("task_ref", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.execute(
        "INSERT OR IGNORE INTO issue_dismissal_new (task_ref, created_at) "
        "SELECT repo || '#' || issue_number, created_at FROM issue_dismissal"
    )
    op.drop_table("issue_dismissal")
    op.rename_table("issue_dismissal_new", "issue_dismissal")


def downgrade() -> None:
    """Reverse task_ref, issue_number nullability, and dismissal key."""
    op.create_table(
        "issue_dismissal_old",
        sa.Column("repo", sa.String(), primary_key=True),
        sa.Column("issue_number", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    # Split a GitHub task_ref "owner/name#123" back into (repo, issue_number);
    # rows without a numeric suffix (Jira) cannot be represented; drop them.
    op.execute(
        "INSERT OR IGNORE INTO issue_dismissal_old "
        "(repo, issue_number, created_at) "
        "SELECT substr(task_ref, 1, instr(task_ref, '#') - 1), "
        "CAST(substr(task_ref, instr(task_ref, '#') + 1) AS INTEGER), "
        "created_at "
        "FROM issue_dismissal WHERE instr(task_ref, '#') > 0"
    )
    op.drop_table("issue_dismissal")
    op.rename_table("issue_dismissal_old", "issue_dismissal")

    with op.batch_alter_table("workflow_run") as batch:
        batch.alter_column(
            "issue_number", existing_type=sa.Integer(), nullable=False
        )
        batch.drop_column("task_ref")
