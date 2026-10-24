"""Baseline: the whole kestrel schema on PostgreSQL.

Generated from the ORM models (``app/persistence/tables.py`` and
``board_tables.py``) and reviewed by hand. Replaces the earlier
migration history; there is no data migration. Every foreign key is checked at
commit (``deferred_fk`` in ``tables.py`` says why).

Revision ID: 0001
Revises:
Create Date: 2026-10-24
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create every table, its keys and its indexes."""
    op.create_table(
        "board_untrusted_input",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("source_identity", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column("safe_content_ref", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_board_untrusted_input"),
    )
    op.create_index(
        "uq_board_untrusted_input_identity",
        "board_untrusted_input",
        ["source_identity", "content_hash"],
        unique=True,
    )
    op.create_table(
        "board_workflow",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("task_ref", sa.Text(), nullable=False),
        sa.Column("repo", sa.Text(), nullable=False),
        sa.Column("base_branch", sa.Text(), nullable=False),
        sa.Column("source_visibility", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("change_request_number", sa.Integer(), nullable=True),
        sa.Column("change_request_url", sa.Text(), nullable=True),
        sa.Column(
            "ci_repair_round", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("ci_status", sa.Text(), nullable=True),
        sa.Column("task_body", sa.Text(), server_default="", nullable=False),
        sa.Column("approved_prd", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_board_workflow"),
    )
    op.create_index(
        "uq_board_workflow_source_task",
        "board_workflow",
        ["source", "task_ref"],
        unique=True,
    )
    op.create_table(
        "webhook_delivery",
        sa.Column("delivery_id", sa.String(), nullable=False),
        sa.Column("event", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("repo", sa.String(), nullable=True),
        sa.Column("issue_number", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("delivery_id", name="pk_webhook_delivery"),
    )
    op.create_table(
        "board_card",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workflow_id", sa.String(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("eligible_roles", sa.Text(), nullable=False),
        sa.Column(
            "workspace_permission",
            sa.Text(),
            server_default="none",
            nullable=False,
        ),
        sa.Column("acceptance_contract", sa.Text(), nullable=False),
        sa.Column(
            "attempt_limit", sa.Integer(), server_default="1", nullable=False
        ),
        sa.Column(
            "attempt_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("wait_reason", sa.Text(), nullable=True),
        sa.Column("scope_authority_artifact", sa.Text(), nullable=True),
        sa.Column("task_node_id", sa.Text(), nullable=True),
        sa.Column("source_card_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["board_workflow.id"],
            name="fk_board_card_workflow_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_board_card"),
    )
    op.create_table(
        "board_comment_cursor",
        sa.Column("workflow_id", sa.String(), nullable=False),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["board_workflow.id"],
            name="fk_board_comment_cursor_workflow_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("workflow_id", name="pk_board_comment_cursor"),
    )
    op.create_table(
        "board_external_projection",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workflow_id", sa.String(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.Column("task_ref", sa.Text(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["board_workflow.id"],
            name="fk_board_external_projection_workflow_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_board_external_projection"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_board_external_projection_idempotency_key",
        ),
    )
    op.create_table(
        "board_inbound_comment",
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("workflow_id", sa.String(), nullable=False),
        sa.Column("gate_card_id", sa.String(), nullable=True),
        sa.Column("author_account_id", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("security_review_id", sa.String(), nullable=True),
        sa.Column("intent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["board_workflow.id"],
            name="fk_board_inbound_comment_workflow_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("external_id", name="pk_board_inbound_comment"),
    )
    op.create_index(
        "has_inbound_comment_workflow",
        "board_inbound_comment",
        ["workflow_id"],
        unique=False,
    )
    op.create_table(
        "board_artifact",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("producer_card_id", sa.String(), nullable=False),
        sa.Column("logical_name", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content_ref", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("trust", sa.Text(), nullable=False),
        sa.Column("input_artifacts", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["producer_card_id"],
            ["board_card.id"],
            name="fk_board_artifact_producer_card_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_board_artifact"),
    )
    op.create_index(
        "uq_board_artifact_identity",
        "board_artifact",
        ["producer_card_id", "logical_name", "revision"],
        unique=True,
    )
    op.create_table(
        "board_card_attempt",
        sa.Column("card_id", sa.String(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("specialist_id", sa.Text(), nullable=False),
        sa.Column("backend_id", sa.Text(), nullable=True),
        sa.Column("session_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["card_id"],
            ["board_card.id"],
            name="fk_board_card_attempt_card_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint(
            "card_id", "sequence", name="pk_board_card_attempt"
        ),
    )
    op.create_table(
        "board_card_relation",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("card_id", sa.String(), nullable=False),
        sa.Column("depends_on_card_id", sa.String(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("required_artifact_revision", sa.Integer(), nullable=True),
        sa.Column("created_by_action", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["card_id"],
            ["board_card.id"],
            name="fk_board_card_relation_card_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["depends_on_card_id"],
            ["board_card.id"],
            name="fk_board_card_relation_depends_on_card_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_board_card_relation"),
    )
    op.create_index(
        "uq_board_card_relation_edge",
        "board_card_relation",
        ["card_id", "depends_on_card_id", "kind"],
        unique=True,
    )
    op.create_table(
        "board_claim_lease",
        sa.Column("card_id", sa.String(), nullable=False),
        sa.Column("attempt_sequence", sa.Integer(), nullable=False),
        sa.Column("holder_specialist_id", sa.Text(), nullable=False),
        sa.Column("workspace_repo", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["card_id"],
            ["board_card.id"],
            name="fk_board_claim_lease_card_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("card_id", name="pk_board_claim_lease"),
    )
    op.create_index(
        "uq_board_claim_lease_workspace_repo",
        "board_claim_lease",
        ["workspace_repo"],
        unique=True,
    )
    op.create_table(
        "board_event",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workflow_id", sa.String(), nullable=False),
        sa.Column("card_id", sa.String(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("causation_id", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["card_id"],
            ["board_card.id"],
            name="fk_board_event_card_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["board_workflow.id"],
            name="fk_board_event_workflow_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_board_event"),
    )
    op.create_table(
        "board_security_review",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("untrusted_input_id", sa.String(), nullable=False),
        sa.Column("card_id", sa.String(), nullable=False),
        sa.Column("classification_category", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("findings", sa.Text(), nullable=False),
        sa.Column("review_state", sa.Text(), nullable=False),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["card_id"],
            ["board_card.id"],
            name="fk_board_security_review_card_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["untrusted_input_id"],
            ["board_untrusted_input.id"],
            name="fk_board_security_review_untrusted_input_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_board_security_review"),
        sa.UniqueConstraint("card_id", name="uq_board_security_review_card_id"),
    )
    op.create_table(
        "board_human_gate",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("card_id", sa.String(), nullable=False),
        sa.Column("target_artifact_id", sa.String(), nullable=True),
        sa.Column("requested_decision", sa.Text(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=True),
        sa.Column("decision_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["card_id"],
            ["board_card.id"],
            name="fk_board_human_gate_card_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["target_artifact_id"],
            ["board_artifact.id"],
            name="fk_board_human_gate_target_artifact_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_board_human_gate"),
        sa.UniqueConstraint("card_id", name="uq_board_human_gate_card_id"),
    )


def downgrade() -> None:
    """Drop every table, dependents first."""
    for table in (
        "board_human_gate",
        "board_security_review",
        "board_event",
        "board_claim_lease",
        "board_card_relation",
        "board_card_attempt",
        "board_artifact",
        "board_inbound_comment",
        "board_external_projection",
        "board_comment_cursor",
        "board_card",
        "webhook_delivery",
        "board_workflow",
        "board_untrusted_input",
    ):
        op.drop_table(table)
