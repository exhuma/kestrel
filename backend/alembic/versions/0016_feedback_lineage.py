"""Run-lineage column for a linked successor run.

Adds ``workflow_run.parent_run_id`` (nullable FK to ``workflow_run.id``):
the smallest viable shape for feature 013's "Run lineage" entity
(data-model.md) — set only on a successor run started by
``IngestionService.start_successor_run`` when marked feedback arrives for
a `done` run whose change request has since merged/closed (or never
existed), so the two are never mistaken for unrelated activity on the
same ticket (FR-011, User Story 4). No backfill: every pre-existing row
is not a successor, so NULL is already the correct value.

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-07
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add workflow_run.parent_run_id.

    SQLite cannot ``ALTER TABLE ... ADD COLUMN`` with a constraint
    outside of batch mode (copy-and-move) — see the existing
    ``0015_feedback.py``'s downgrade for the same pattern.
    """
    with op.batch_alter_table("workflow_run") as batch:
        batch.add_column(
            sa.Column(
                "parent_run_id", sa.String(),
                sa.ForeignKey(
                    "workflow_run.id", name="fk_workflow_run_parent_run_id"
                ),
                nullable=True,
            ),
        )


def downgrade() -> None:
    """Drop workflow_run.parent_run_id."""
    with op.batch_alter_table("workflow_run") as batch:
        batch.drop_column("parent_run_id")
