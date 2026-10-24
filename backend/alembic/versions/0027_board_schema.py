"""Create the board domain schema (feature 026).

Adds the durable work-board tables described in
``specs/026-autonomous-work-board/data-model.md``: workflows, cards,
relations, attempts, leases, artifacts, human gates, untrusted input,
security reviews, coordinator actions, events, and external projections.
This coexists with the existing fixed-driver ``workflow_run``/
``workflow_step`` tables, which it does not touch or replace.

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-24
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create every board-domain table and its uniqueness index."""
    _create_workflow_and_card_tables()
    _create_lease_and_artifact_tables()
    _create_input_safety_tables()
    _create_coordination_tables()


def _create_workflow_and_card_tables() -> None:
    """Create ``board_workflow``, ``board_card``, ``board_card_relation``."""
    op.create_table(
        "board_workflow",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("task_ref", sa.Text(), nullable=False),
        sa.Column("repo", sa.Text(), nullable=False),
        sa.Column("base_branch", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_visibility", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column(
            "revision", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "uq_board_workflow_source_task",
        "board_workflow",
        ["source", "task_ref"],
        unique=True,
    )
    op.create_table(
        "board_card",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "workflow_id", sa.String(),
            sa.ForeignKey("board_workflow.id"), nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column(
            "eligible_roles", sa.Text(), nullable=False, server_default=""
        ),
        sa.Column(
            "workspace_permission", sa.Text(),
            nullable=False, server_default="none",
        ),
        sa.Column(
            "acceptance_contract", sa.Text(),
            nullable=False, server_default="{}",
        ),
        sa.Column(
            "attempt_limit", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column(
            "attempt_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("wait_reason", sa.Text(), nullable=True),
        sa.Column("scope_authority_artifact", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "board_card_relation",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "card_id", sa.String(),
            sa.ForeignKey("board_card.id"), nullable=False,
        ),
        sa.Column(
            "depends_on_card_id", sa.String(),
            sa.ForeignKey("board_card.id"), nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("required_artifact_revision", sa.Integer(), nullable=True),
        sa.Column("created_by_action", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "uq_board_card_relation_edge",
        "board_card_relation",
        ["card_id", "depends_on_card_id", "kind"],
        unique=True,
    )


def _create_lease_and_artifact_tables() -> None:
    """Create attempt, claim/workspace lease, and artifact tables."""
    op.create_table(
        "board_card_attempt",
        sa.Column(
            "card_id", sa.String(),
            sa.ForeignKey("board_card.id"), primary_key=True,
        ),
        sa.Column("sequence", sa.Integer(), primary_key=True),
        sa.Column("specialist_id", sa.Text(), nullable=False),
        sa.Column("backend_id", sa.Text(), nullable=True),
        sa.Column("session_id", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.Text(), nullable=False, server_default="active"
        ),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "board_claim_lease",
        sa.Column(
            "card_id", sa.String(),
            sa.ForeignKey("board_card.id"), primary_key=True,
        ),
        sa.Column("attempt_sequence", sa.Integer(), nullable=False),
        sa.Column("holder_specialist_id", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "board_workspace_lease",
        sa.Column("repo", sa.Text(), primary_key=True),
        sa.Column(
            "claim_card_id", sa.String(),
            sa.ForeignKey("board_card.id"), nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "board_artifact",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "producer_card_id", sa.String(),
            sa.ForeignKey("board_card.id"), nullable=False,
        ),
        sa.Column("logical_name", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content_ref", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column(
            "mime_type", sa.Text(),
            nullable=False, server_default="text/plain",
        ),
        sa.Column("trust", sa.Text(), nullable=False),
        sa.Column(
            "retention", sa.Text(), nullable=False, server_default="standard"
        ),
        sa.Column(
            "project_material", sa.Boolean(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "input_artifacts", sa.Text(), nullable=False, server_default="[]"
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "uq_board_artifact_identity",
        "board_artifact",
        ["producer_card_id", "logical_name", "revision"],
        unique=True,
    )


def _create_input_safety_tables() -> None:
    """Create human-gate, untrusted-input, and security-review tables."""
    op.create_table(
        "board_human_gate",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "card_id", sa.String(),
            sa.ForeignKey("board_card.id"), nullable=False, unique=True,
        ),
        sa.Column(
            "target_artifact_id", sa.String(),
            sa.ForeignKey("board_artifact.id"), nullable=True,
        ),
        sa.Column("requested_decision", sa.Text(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=True),
        sa.Column("decision_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "board_untrusted_input",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source_identity", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column("safe_content_ref", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "uq_board_untrusted_input_identity",
        "board_untrusted_input",
        ["source_identity", "content_hash"],
        unique=True,
    )
    op.create_table(
        "board_security_review",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "untrusted_input_id", sa.String(),
            sa.ForeignKey("board_untrusted_input.id"), nullable=False,
        ),
        sa.Column(
            "card_id", sa.String(),
            sa.ForeignKey("board_card.id"), nullable=False, unique=True,
        ),
        sa.Column("classification_category", sa.Text(), nullable=False),
        sa.Column(
            "findings", sa.Text(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "review_state", sa.Text(), nullable=False, server_default="pending"
        ),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def _create_coordination_tables() -> None:
    """Create coordinator-action, event, and external-projection tables."""
    op.create_table(
        "board_coordinator_action",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "workflow_id", sa.String(),
            sa.ForeignKey("board_workflow.id"), nullable=False,
        ),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("action_payload", sa.Text(), nullable=False),
        sa.Column("validation_decision", sa.Text(), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "board_event",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workflow_id", sa.String(),
            sa.ForeignKey("board_workflow.id"), nullable=False,
        ),
        sa.Column(
            "card_id", sa.String(),
            sa.ForeignKey("board_card.id"), nullable=True,
        ),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column(
            "payload", sa.Text(), nullable=False, server_default="{}"
        ),
        sa.Column("causation_id", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "board_external_projection",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "workflow_id", sa.String(),
            sa.ForeignKey("board_workflow.id"), nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "state", sa.Text(), nullable=False, server_default="pending"
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    """Drop every board-domain table, children before parents."""
    op.drop_table("board_external_projection")
    op.drop_table("board_event")
    op.drop_table("board_coordinator_action")
    op.drop_table("board_security_review")
    op.drop_table("board_untrusted_input")
    op.drop_table("board_human_gate")
    op.drop_table("board_artifact")
    op.drop_table("board_workspace_lease")
    op.drop_table("board_claim_lease")
    op.drop_table("board_card_attempt")
    op.drop_table("board_card_relation")
    op.drop_table("board_card")
    op.drop_table("board_workflow")
