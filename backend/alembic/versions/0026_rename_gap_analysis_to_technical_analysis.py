"""Rename the persisted ``gap_analysis`` step to ``technical_analysis``.

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-18
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

_OLD = "gap_analysis"
_NEW = "technical_analysis"


def _rename(table: str, column: str, old: str, new: str) -> None:
    """Rewrite one step-name column's stored value in place.

    :param table: The table that stores a workflow step identifier.
    :param column: The column holding the step name to rename.
    :param old: The currently-stored value to match.
    :param new: The value to replace it with.
    """
    op.execute(
        sa.text(
            f"UPDATE {table} SET {column} = :new WHERE {column} = :old"
        ).bindparams(new=new, old=old)
    )


def _rename_all(old: str, new: str) -> None:
    """Apply a step-value rename across every table that stores one."""
    _rename("workflow_step", "name", old, new)
    _rename("workflow_round_chip", "step_name", old, new)
    _rename("feedback_item", "target_step", old, new)


def upgrade() -> None:
    """Rewrite every persisted ``gap_analysis`` step value.

    The rename is a clean break: the identifier no longer exists under its
    old name, so pre-existing rows are migrated rather than left dangling.
    Deliverable checkpoint JSON, task-source markers, and committed
    technical-analysis artifacts are deliberately untouched — they already
    use the ``technical_analysis`` terminology.
    """
    _rename_all(_OLD, _NEW)


def downgrade() -> None:
    """Restore the pre-rename ``gap_analysis`` step value."""
    _rename_all(_NEW, _OLD)
