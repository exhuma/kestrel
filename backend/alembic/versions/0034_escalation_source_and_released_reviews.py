"""Escalation sources; close released security reviews (feature 041).

- Adds ``board_card.source_card_id``: the card a ``coordinator_review``
  escalates, which places the escalation in that card's phase. ``NULL``
  for every existing card — an escalation without one is placed by the
  rest of the request.
- Completes every released security review whose card was left open.
  Before 041 a release moved the card to ``ready``, where nothing ever
  moved it on, so the request stayed in Intake for good. The operator's
  release is the review's completion: the card becomes ``done``.

Downgrade drops the column; the completed cards stay ``done`` (a
``ready`` review card was never meaningful).

Revision ID: 0034
Revises: 0033
Create Date: 2026-09-30
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the column; complete the released reviews' open cards."""
    with op.batch_alter_table("board_card") as batch:
        batch.add_column(
            sa.Column("source_card_id", sa.Text(), nullable=True)
        )
    op.execute(
        "UPDATE board_card SET state = 'done' "
        "WHERE kind = 'security_review' "
        "AND state IN ('ready', 'claimed') "
        "AND id IN (SELECT card_id FROM board_security_review "
        "WHERE review_state = 'released')"
    )


def downgrade() -> None:
    """Drop the column."""
    with op.batch_alter_table("board_card") as batch:
        batch.drop_column("source_card_id")
