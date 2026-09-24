"""Drop the retired fixed-driver and feedback-dispatch tables (feature 026).

Phase 10 clean break: the old fixed six-step workflow driver and the
feedback-dispatch subsystem it hosted are removed from the codebase in
favour of the board domain (``board_*`` tables, migration 0027). Per
spec.md FR-037 this is a green-field replacement — existing
``workflow_run``/... data does not need to carry forward. Drops
``workflow_run``, ``workflow_step``, ``workflow_round_chip``,
``workflow_artifact``, ``review_request``, ``feedback_item``, and
``feedback_cursor``.

``notification.workflow_id`` and ``child_task_link.parent_workflow_id``/
``latest_workflow_id`` keep referencing (now board) workflow ids by
convention only — this project never enables SQLite's ``PRAGMA
foreign_keys``, so their declared foreign keys were never enforced and
dropping the old table they pointed at is safe without touching either.

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-24
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

_CHILD_TABLES = (
    "workflow_artifact",
    "workflow_round_chip",
    "workflow_step",
    "review_request",
    "feedback_item",
    "feedback_cursor",
)


def upgrade() -> None:
    """Drop every retired fixed-driver / feedback-dispatch table."""
    for table in _CHILD_TABLES:
        op.drop_table(table)
    op.drop_table("workflow_run")


def downgrade() -> None:
    """Recreate every table this migration dropped, in its prior shape."""
    _create_workflow_run()
    _create_workflow_step()
    _create_workflow_round_chip()
    _create_workflow_artifact()
    _create_feedback_item()
    _create_feedback_cursor()
    _create_review_request()


def _create_workflow_run() -> None:
    op.create_table(
        "workflow_run",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("repo", sa.String(), nullable=False),
        sa.Column("issue_number", sa.Integer(), nullable=True),
        sa.Column("issue_title", sa.String(), nullable=False, default=""),
        sa.Column("base_branch", sa.String(), nullable=False, default=""),
        sa.Column("branch", sa.String(), nullable=False, default=""),
        sa.Column("workspace", sa.Text(), nullable=False, default=""),
        sa.Column(
            "status", sa.String(), nullable=False, server_default="pending"
        ),
        sa.Column("pr_url", sa.String(), nullable=True),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "source", sa.String(), nullable=False,
            server_default="github-issue",
        ),
        sa.Column("task_ref", sa.String(), nullable=False, server_default=""),
        sa.Column(
            "artifact_dir", sa.Text(), nullable=False, server_default=""
        ),
        sa.Column("boundary", sa.Text(), nullable=True),
        sa.Column(
            "active_seconds", sa.Float(), nullable=False, server_default="0"
        ),
        sa.Column(
            "wait_seconds", sa.Float(), nullable=False, server_default="0"
        ),
        sa.Column("clock_state", sa.Text(), nullable=True),
        sa.Column("clock_since", sa.DateTime(), nullable=True),
        sa.Column(
            "parent_run_id", sa.String(),
            sa.ForeignKey("workflow_run.id"), nullable=True,
        ),
        sa.Column("terminal_at", sa.DateTime(), nullable=True),
        sa.Column("pending_gate_decision", sa.Text(), nullable=True),
        sa.Column(
            "prd_approved", sa.Boolean(), nullable=False,
            server_default="0",
        ),
        sa.Column("approved_prd", sa.Text(), nullable=True),
        sa.Column(
            "ci_repair_round", sa.Integer(), nullable=False,
            server_default="0",
        ),
    )


def _create_workflow_step() -> None:
    op.create_table(
        "workflow_step",
        sa.Column(
            "workflow_id", sa.String(),
            sa.ForeignKey("workflow_run.id"), primary_key=True,
        ),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column(
            "status", sa.String(), nullable=False, server_default="pending"
        ),
        sa.Column("deliverable", sa.Text(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column(
            "refine_round", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "verify_round", sa.Integer(), nullable=False, server_default="0"
        ),
    )


def _create_workflow_round_chip() -> None:
    op.create_table(
        "workflow_round_chip",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workflow_id", sa.String(),
            sa.ForeignKey("workflow_run.id"), nullable=False,
        ),
        sa.Column("step_name", sa.String(), nullable=False),
        sa.Column("round_index", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column(
            "badge", sa.String(), nullable=False, server_default="sys"
        ),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("retired_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_workflow_round_chip_workflow_step",
        "workflow_round_chip",
        ["workflow_id", "step_name"],
    )


def _create_workflow_artifact() -> None:
    op.create_table(
        "workflow_artifact",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workflow_id", sa.String(),
            sa.ForeignKey("workflow_run.id"), nullable=False,
        ),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("cleanup_mode", sa.String(), nullable=False),
        sa.Column(
            "state", sa.String(), nullable=False, server_default="pending"
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("cleaned_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_workflow_artifact_workflow_id",
        "workflow_artifact",
        ["workflow_id"],
    )


def _create_feedback_item() -> None:
    op.create_table(
        "feedback_item",
        sa.Column("external_id", sa.Text(), primary_key=True),
        sa.Column(
            "workflow_id", sa.String(),
            sa.ForeignKey("workflow_run.id"), nullable=True,
        ),
        sa.Column("task_ref", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("author", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("target_step", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_feedback_item_workflow_state",
        "feedback_item",
        ["workflow_id", "state"],
    )


def _create_feedback_cursor() -> None:
    op.create_table(
        "feedback_cursor",
        sa.Column("scope", sa.Text(), primary_key=True),
        sa.Column("cursor", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def _create_review_request() -> None:
    op.create_table(
        "review_request",
        sa.Column("token", sa.Text(), primary_key=True),
        sa.Column(
            "workflow_id", sa.String(),
            sa.ForeignKey("workflow_run.id"), nullable=False,
        ),
        sa.Column("gate", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "active", sa.Boolean(), nullable=False, server_default="1"
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "uq_review_request_active_gate",
        "review_request",
        ["workflow_id", "gate"],
        unique=True,
        sqlite_where=sa.text("active = 1"),
    )
