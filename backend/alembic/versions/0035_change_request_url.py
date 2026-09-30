"""The change request's URL alongside its number (feature 043).

Adds ``board_workflow.change_request_url``, recorded when delivery opens
a change request, so the cockpit can link to it. ``NULL`` for every
existing workflow: a delivery from before 043 recorded only a number,
and it is not backfilled.

Revision ID: 0035
Revises: 0034
Create Date: 2026-09-30
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the column."""
    with op.batch_alter_table("board_workflow") as batch:
        batch.add_column(
            sa.Column("change_request_url", sa.Text(), nullable=True)
        )


def downgrade() -> None:
    """Drop the column."""
    with op.batch_alter_table("board_workflow") as batch:
        batch.drop_column("change_request_url")
