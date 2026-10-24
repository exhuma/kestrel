"""The ticket as a channel (feature 046).

- ``board_external_projection`` keeps what it posts, so a failed post can
  be retried: ``task_ref``, ``payload`` (document JSON) and ``attempts``.
  ``NULL`` / ``0`` on existing rows, which recorded only a hash.
- ``board_comment_cursor``: how far each workflow's ticket comments have
  been read.
- ``board_inbound_comment``: every ticket comment kestrel considered, so
  each is acted on at most once.

Revision ID: 0036
Revises: 0035
Create Date: 2026-10-05
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the ledger columns and the two comment tables."""
    with op.batch_alter_table("board_external_projection") as batch:
        batch.add_column(sa.Column("task_ref", sa.Text(), nullable=True))
        batch.add_column(sa.Column("payload", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column(
                "attempts", sa.Integer(), nullable=False, server_default="0"
            )
        )
    op.create_table(
        "board_comment_cursor",
        sa.Column(
            "workflow_id", sa.String(),
            sa.ForeignKey("board_workflow.id"), primary_key=True,
        ),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "board_inbound_comment",
        sa.Column("external_id", sa.Text(), primary_key=True),
        sa.Column(
            "workflow_id", sa.String(),
            sa.ForeignKey("board_workflow.id"), nullable=False,
        ),
        sa.Column("gate_card_id", sa.String(), nullable=True),
        sa.Column("author_account_id", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("security_review_id", sa.String(), nullable=True),
        sa.Column("intent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "has_inbound_comment_workflow",
        "board_inbound_comment",
        ["workflow_id"],
    )


def downgrade() -> None:
    """Drop the comment tables and the ledger columns."""
    op.drop_index(
        "has_inbound_comment_workflow", table_name="board_inbound_comment"
    )
    op.drop_table("board_inbound_comment")
    op.drop_table("board_comment_cursor")
    with op.batch_alter_table("board_external_projection") as batch:
        batch.drop_column("attempts")
        batch.drop_column("payload")
        batch.drop_column("task_ref")
