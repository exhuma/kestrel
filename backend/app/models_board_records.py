"""Event/record/outcome value objects for the board domain (feature 026).

Split out of ``models_board.py`` to keep that module (the core
entities — ``Workflow``, ``WorkCard``, the enums) under the repo's
500-line ceiling. Same layering rationale as that module: no dependency
on persistence, routers, or adapters.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.documents import EMPTY_DOCUMENT, Document


@dataclass(frozen=True)
class BoardEventRecord:
    """One append-only board history entry to record (data-model.md).

    :param workflow_id: The owning workflow.
    :param event_type: A safe, closed event-type identifier.
    :param card_id: The related card, when this event is card-scoped.
    :param payload: Safe event payload (JSON-serialized); never raw
        suspect content (FR-025).
    :param causation_id: The id of the event/action that caused this one.
    :param correlation_id: Groups events belonging to one causal chain.
    :param created_at: When this event was recorded — ``None`` on a
        not-yet-appended record; ``BoardStore.list_events`` always fills
        it in from the row, since the server assigns it on append.
    """

    workflow_id: str
    event_type: str
    card_id: str | None = None
    payload: str = "{}"
    causation_id: str | None = None
    correlation_id: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class HandoffArtifact:
    """An immutable version of one card's output (data-model.md).

    :param id: Stable artifact identity.
    :param producer_card_id: The card that produced this artifact.
    :param logical_name: Stable name; unique with ``revision``.
    :param revision: Monotonic version for this ``logical_name``.
    :param content_ref: Durable reference to the content, stored outside
        board snapshots.
    :param content_hash: Integrity hash of the referenced content.
    :param trust: At least ``untrusted``, ``released``, ``agent_output``,
        or ``operator_approved``.
    :param mime_type: The referenced content's media type.
    :param retention: Operational retention policy.
    :param project_material: Explicit opt-in for inclusion in the project
        change; orchestration-only artifacts default to ``False``.
    :param input_artifacts: Exact consumed input-artifact ids, never
        mutable "latest" pointers.
    """

    id: str
    producer_card_id: str
    logical_name: str
    revision: int
    content_ref: str
    content_hash: str
    trust: str
    mime_type: str = "text/plain"
    retention: str = "standard"
    project_material: bool = False
    input_artifacts: tuple[str, ...] = ()


@dataclass(frozen=True)
class AcceptedTaskIntake:
    """A safety-cleared task, ready to become a workflow (FR-001).

    :param source: Source origin (e.g. ``"github-issue"``).
    :param task_ref: Source-native task identity.
    :param repo: Target code repository.
    :param base_branch: The branch write work will target.
    :param source_visibility: ``public`` or ``private``.
    :param title: Safe display title.
    :param body: See ``Workflow.task_body`` — the quarantine-released
        safe content, already screened by the caller (FR-018/FR-024).
    """

    source: str
    task_ref: str
    repo: str
    base_branch: str
    source_visibility: str
    title: str
    body: Document = EMPTY_DOCUMENT


@dataclass(frozen=True)
class UntrustedInputRecord:
    """One bounded, hashed record of received untrusted content.

    :param id: Stable record identity.
    :param source_identity: Bounded source metadata (e.g. ``"github-issue:
        owner/repo#123"``).
    :param content_hash: Integrity hash of the content, for dedup.
    :param policy_version: The screening policy version applied.
    :param safe_content_ref: Reference to the safely stored content; never
        the raw body inline (FR-025).
    """

    id: str
    source_identity: str
    content_hash: str
    policy_version: str
    safe_content_ref: str


@dataclass(frozen=True)
class SecurityReviewRecord:
    """One quarantine record and its resolution (data-model.md).

    :param id: Stable record identity.
    :param untrusted_input_id: The screened content this review covers.
    :param card_id: The one ``security_review`` card this review gates.
    :param workflow_id: The workflow hosting that card (existing, or
        newly created to host a new-task quarantine).
    :param classification_category: The deterministic/classifier finding.
    :param reason: The deterministic/classifier's own short, safe
        explanation of *why* this content was quarantined — an operator
        needs this to decide release vs. discard, not just the category.
    :param review_state: ``"pending"``, ``"released"``, or ``"discarded"``.
    :param resolution: Operator-recorded resolution note, once decided.
    """

    id: str
    untrusted_input_id: str
    card_id: str
    workflow_id: str
    classification_category: str
    review_state: str
    reason: str | None = None
    resolution: str | None = None


@dataclass(frozen=True)
class IntakeOutcome:
    """Result of one :class:`QuarantineService` intake call.

    :param released: Whether the content may proceed as trusted.
    :param safe_content: The screened content, only when ``released``.
    :param security_review_id: The created review, only when quarantined.
    :param workflow_id: The workflow the review card was attached to
        (existing, or newly created to host a new-task quarantine).
    :param card_id: The created ``security_review`` card, when quarantined.
    """

    released: bool
    safe_content: Document | None = None
    security_review_id: str | None = None
    workflow_id: str | None = None
    card_id: str | None = None


@dataclass(frozen=True)
class ClaimOutcome:
    """Result of one :meth:`BoardStore.claim_card` attempt.

    :param success: Whether the claim (and any workspace lease) succeeded.
    :param attempt_sequence: The new attempt's sequence number, when
        successful.
    :param reason: ``"not_ready"`` or ``"workspace_lease_unavailable"``
        when unsuccessful.
    """

    success: bool
    attempt_sequence: int | None = None
    reason: str | None = None


@dataclass(frozen=True)
class CompleteOutcome:
    """Result of one :meth:`BoardStore.complete_attempt` call.

    :param success: Whether the completion advanced the card.
    :param reason: ``"not_found"`` or ``"stale"`` when unsuccessful — a
        stale completion is still recorded as evidence, just not applied.
    """

    success: bool
    reason: str | None = None


@dataclass(frozen=True)
class CoordinatorActionRecord:
    """One proposed structured action and its policy outcome (data-model.md
    "Coordinator Action"; FR-005).

    :param id: Stable record identity.
    :param workflow_id: The workflow this action targets.
    :param trigger: What woke the coordinator (e.g. ``"card.done"``).
    :param sequence: Monotonic per-workflow ordering.
    :param action_payload: The proposed action, JSON-serialized.
    :param validation_decision: ``"accepted"`` or ``"rejected"``.
    :param rejection_reason: Safe reason, when rejected.
    :param applied: Whether the accepted action was actually applied.
    """

    id: str
    workflow_id: str
    trigger: str
    sequence: int
    action_payload: str
    validation_decision: str
    rejection_reason: str | None = None
    applied: bool = False


@dataclass(frozen=True)
class HumanGateRecord:
    """One gate card's decision record (data-model.md "Human Gate"; FR-016).

    :param id: Stable record identity.
    :param card_id: The one gate card this record belongs to.
    :param requested_decision: Safe, closed description of what's asked.
    :param target_artifact_id: The artifact revision this gate decides on,
        if any (e.g. the PRD revision a ``prd_gate`` approves).
    :param decision: ``None`` until the operator decides; then
        ``"approved"`` or ``"rejected"``.
    """

    id: str
    card_id: str
    requested_decision: str
    target_artifact_id: str | None = None
    decision: str | None = None


@dataclass(frozen=True)
class ExternalProjectionRecord:
    """One selected, idempotent milestone update to a task source
    (data-model.md "External Projection"; FR-033/FR-034/FR-035).

    Only five kinds ever project by default (FR-033): ordinary claims,
    retries, and routine completions never reach this ledger at all
    (FR-034) — callers decide what's projection-worthy, this record only
    makes recording that decision idempotent and retryable.

    :param id: Stable record identity.
    :param workflow_id: The workflow this milestone belongs to.
    :param kind: ``"gate"``, ``"escalation"``, ``"approved_artifact"``,
        ``"delivery"``, or (feature 046) ``"gate_opened"``, ``"status"``,
        ``"reply"`` (a legacy row may still read ``"child_work"``, which
        feature 031 no longer writes).
    :param idempotency_key: Unique per real-world event; a webhook and a
        poll cycle racing to report the same milestone still project it
        at most once.
    :param payload_hash: Integrity hash of the safe payload sent.
    :param state: ``"pending"``, ``"completed"``, or
        ``"retryable_failure"``.
    :param error: Safe failure reason, when ``retryable_failure``.
    :param external_id: The task-source resource Kestrel now owns, once
        ``completed`` — the durable cleanup ledger (FR-035).
    :param task_ref: Where to post it (feature 046); ``None`` on a row
        from before the ledger kept its payload.
    :param payload: What to post, kept so a failed post can be retried;
        ``None`` on an old row.
    :param attempts: How many times a retry has taken this row on.
    :param updated_at: When the row last changed: the retry backoff's
        clock.
    """

    id: str
    workflow_id: str
    kind: str
    idempotency_key: str
    payload_hash: str
    state: str = "pending"
    error: str | None = None
    external_id: str | None = None
    task_ref: str | None = None
    payload: Document | None = None
    attempts: int = 0
    updated_at: datetime | None = None
