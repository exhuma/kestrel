"""Board-domain ORM tables (feature 026).

Mirrors ``specs/026-autonomous-work-board/data-model.md``. Kept separate
from ``tables.py`` for cohesion and module-length budget. Every table
name is prefixed ``board_`` for clarity.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.documents import EMPTY_DOCUMENT, Document
from app.persistence.document_column import DocumentText
from app.persistence.tables import Base, deferred_fk


class BoardWorkflowRow(Base):
    """One accepted task's durable aggregate (data-model.md "Workflow")."""

    __tablename__ = "board_workflow"
    __table_args__ = (
        Index(
            "uq_board_workflow_source_task",
            "source",
            "task_ref",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(Text)
    task_ref: Mapped[str] = mapped_column(Text)
    repo: Mapped[str] = mapped_column(Text)
    base_branch: Mapped[str] = mapped_column(Text, default="")
    #: "public" or "private", copied from the source at creation time and
    #: never changed by later configuration (data-model.md).
    source_visibility: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text)
    #: Monotonic version for snapshots and optimistic interventions.
    revision: Mapped[int] = mapped_column(default=1, server_default="1")
    #: The change request delivery opened, once known (T052).
    change_request_number: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    #: Where that change request is, once delivery opened it (feature 043).
    change_request_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: How many CI-triggered repair cards this workflow's current change
    #: request has gone through; reset on every fresh delivery (T052).
    ci_repair_round: Mapped[int] = mapped_column(default=0, server_default="0")
    #: The most recently observed required-CI verdict, or ``None`` (T052).
    ci_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The task source's own body, safe-screened once at intake (T078).
    task_body: Mapped[Document] = mapped_column(
        DocumentText, default=EMPTY_DOCUMENT, server_default=""
    )
    #: The PRD content a ``prd_gate`` approved, or ``None`` (T078).
    approved_prd: Mapped[Document | None] = mapped_column(
        DocumentText, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime)


class BoardCardRow(Base):
    """One typed, policy-governed unit of work (data-model.md "Work Card")."""

    __tablename__ = "board_card"

    id: Mapped[str] = mapped_column(primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        deferred_fk("board_workflow.id")
    )
    kind: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text)
    #: Validated specialist ids, comma-joined; agents cannot add themselves.
    eligible_roles: Mapped[str] = mapped_column(Text, default="")
    workspace_permission: Mapped[str] = mapped_column(
        Text, default="none", server_default="none"
    )
    #: Closed structured requirement for result validation (JSON).
    acceptance_contract: Mapped[str] = mapped_column(Text, default="{}")
    attempt_limit: Mapped[int] = mapped_column(default=1, server_default="1")
    attempt_count: Mapped[int] = mapped_column(default=0, server_default="0")
    #: Safe explanation for human or dependency waiting; NULL when ready.
    wait_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The exact approved PRD (or successor) artifact this card's scope
    #: authority derives from.
    scope_authority_artifact: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    #: The approved-decomposition task this card works on (feature 031,
    #: research R2); ``NULL`` for every other card.
    task_node_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The card a ``coordinator_review`` escalates (feature 041); ``NULL``
    #: for every other card.
    source_card_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class BoardCardRelationRow(Base):
    """A directed edge between two cards (data-model.md "Card Relation")."""

    __tablename__ = "board_card_relation"
    __table_args__ = (
        Index(
            "uq_board_card_relation_edge",
            "card_id",
            "depends_on_card_id",
            "kind",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    card_id: Mapped[str] = mapped_column(deferred_fk("board_card.id"))
    depends_on_card_id: Mapped[str] = mapped_column(
        deferred_fk("board_card.id")
    )
    kind: Mapped[str] = mapped_column(Text)
    required_artifact_revision: Mapped[int | None] = mapped_column(
        nullable=True
    )
    #: "coordinator" or "operator" (data-model.md).
    created_by_action: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class BoardCardAttemptRow(Base):
    """One specialist's attempt at a card (data-model.md "CardAttempt")."""

    __tablename__ = "board_card_attempt"

    card_id: Mapped[str] = mapped_column(
        deferred_fk("board_card.id"), primary_key=True
    )
    #: Unique per card; terminal attempts never change (data-model.md).
    sequence: Mapped[int] = mapped_column(primary_key=True)
    specialist_id: Mapped[str] = mapped_column(Text)
    backend_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: "active" | "completed" | "interrupted" | "stale".
    status: Mapped[str] = mapped_column(Text, default="active")
    #: Safe structured result payload (JSON); NULL until the attempt ends.
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )


class BoardClaimLeaseRow(Base):
    """The active claim lease for a card, if any (data-model.md).

    ``card_id`` is the primary key: the row exists only while a claim is
    active, which trivially enforces "one active claim per card" — it is
    deleted on completion, or by recovery once its ``expires_at`` passes.

    A writer's claim also holds its repository: ``workspace_repo`` is
    unique, so at most one active claim writes to a repository, and the
    repository is free again as soon as that claim's row is gone.
    """

    __tablename__ = "board_claim_lease"
    __table_args__ = (
        Index(
            "uq_board_claim_lease_workspace_repo",
            "workspace_repo",
            unique=True,
        ),
    )

    card_id: Mapped[str] = mapped_column(
        deferred_fk("board_card.id"), primary_key=True
    )
    attempt_sequence: Mapped[int] = mapped_column()
    holder_specialist_id: Mapped[str] = mapped_column(Text)
    #: The repository this claim writes to; ``NULL`` for a reader.
    workspace_repo: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class BoardArtifactRow(Base):
    """One immutable handoff artifact revision (data-model.md)."""

    __tablename__ = "board_artifact"
    __table_args__ = (
        Index(
            "uq_board_artifact_identity",
            "producer_card_id",
            "logical_name",
            "revision",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True)
    producer_card_id: Mapped[str] = mapped_column(
        deferred_fk("board_card.id")
    )
    logical_name: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column()
    content_ref: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(Text, default="text/plain")
    #: At least "untrusted" | "released" | "agent_output" | "operator_approved".
    trust: Mapped[str] = mapped_column(Text)
    #: Exact consumed input-artifact ids, JSON list; never mutable pointers.
    input_artifacts: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime)


class BoardHumanGateRow(Base):
    """One human-gate card's decision record (data-model.md)."""

    __tablename__ = "board_human_gate"

    id: Mapped[str] = mapped_column(primary_key=True)
    card_id: Mapped[str] = mapped_column(
        deferred_fk("board_card.id"), unique=True
    )
    target_artifact_id: Mapped[str | None] = mapped_column(
        deferred_fk("board_artifact.id"), nullable=True
    )
    requested_decision: Mapped[str] = mapped_column(Text)
    #: NULL until the operator decides.
    decision: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime)


class BoardUntrustedInputRow(Base):
    """One bounded, hashed record of received untrusted content."""

    __tablename__ = "board_untrusted_input"
    __table_args__ = (
        Index(
            "uq_board_untrusted_input_identity",
            "source_identity",
            "content_hash",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True)
    source_identity: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(Text)
    policy_version: Mapped[str] = mapped_column(Text)
    #: Reference to the safely stored content; never the raw body inline.
    safe_content_ref: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class BoardSecurityReviewRow(Base):
    """One quarantine record and its resolution (data-model.md)."""

    __tablename__ = "board_security_review"

    id: Mapped[str] = mapped_column(primary_key=True)
    untrusted_input_id: Mapped[str] = mapped_column(
        deferred_fk("board_untrusted_input.id")
    )
    card_id: Mapped[str] = mapped_column(
        deferred_fk("board_card.id"), unique=True
    )
    classification_category: Mapped[str] = mapped_column(Text)
    #: The deterministic/classifier's own short, safe explanation of why
    #: this content was quarantined; never raw content.
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Safe, deterministic-and-classifier findings (JSON); never raw content.
    findings: Mapped[str] = mapped_column(Text, default="{}")
    #: "pending" | "released" | "discarded".
    review_state: Mapped[str] = mapped_column(Text, default="pending")
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime)


class BoardCoordinatorActionRow(Base):
    """One proposed structured coordinator action and its outcome."""

    __tablename__ = "board_coordinator_action"

    id: Mapped[str] = mapped_column(primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        deferred_fk("board_workflow.id")
    )
    trigger: Mapped[str] = mapped_column(Text)
    sequence: Mapped[int] = mapped_column()
    action_payload: Mapped[str] = mapped_column(Text)
    #: "accepted" | "rejected".
    validation_decision: Mapped[str] = mapped_column(Text)
    rejection_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime)


class BoardEventRow(Base):
    """One append-only board history entry (data-model.md "BoardEvent")."""

    __tablename__ = "board_event"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_id: Mapped[str] = mapped_column(
        deferred_fk("board_workflow.id")
    )
    card_id: Mapped[str | None] = mapped_column(
        deferred_fk("board_card.id"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(Text)
    #: Safe event payload (JSON); never raw suspect content (FR-025).
    payload: Mapped[str] = mapped_column(Text, default="{}")
    causation_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class BoardExternalProjectionRow(Base):
    """One selected, idempotent update sent to a task source."""

    __tablename__ = "board_external_projection"

    id: Mapped[str] = mapped_column(primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        deferred_fk("board_workflow.id")
    )
    #: "gate" | "escalation" | "approved_artifact" | "delivery" |
    #: "gate_opened" | "status" | "reply".
    kind: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(Text, unique=True)
    #: "pending" | "completed" | "retryable_failure".
    state: Mapped[str] = mapped_column(Text, default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The source resource kestrel created for this projection.
    external_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_hash: Mapped[str] = mapped_column(Text)
    #: Where to post, and what, so a failed post can be retried (feature
    #: 046).
    task_ref: Mapped[str] = mapped_column(Text)
    payload: Mapped[Document] = mapped_column(DocumentText)
    #: How many times a retry has taken this row on.
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class BoardCommentCursorRow(Base):
    """How far a request's ticket comments have been read (feature 046)."""

    __tablename__ = "board_comment_cursor"

    workflow_id: Mapped[str] = mapped_column(
        deferred_fk("board_workflow.id"), primary_key=True
    )
    #: Adapter-owned and opaque: passed back to ``list_comments`` as is.
    cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class BoardInboundCommentRow(Base):
    """One ticket comment kestrel considered, so it is acted on at most
    once (feature 046, data-model.md)."""

    __tablename__ = "board_inbound_comment"
    __table_args__ = (
        Index("has_inbound_comment_workflow", "workflow_id"),
    )

    external_id: Mapped[str] = mapped_column(Text, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        deferred_fk("board_workflow.id")
    )
    gate_card_id: Mapped[str | None] = mapped_column(nullable=True)
    author_account_id: Mapped[str] = mapped_column(Text)
    #: "claimed" | "refused" | "held" | "unclear" | "decided" |
    #: "already_decided" | "no_gate" | "interview_pointer".
    state: Mapped[str] = mapped_column(Text)
    security_review_id: Mapped[str | None] = mapped_column(nullable=True)
    #: "approve" | "reject" | "unclear", once the liaison has read it.
    intent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
