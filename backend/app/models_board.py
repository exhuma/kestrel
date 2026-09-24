"""Pure value objects and enums for the board domain (feature 026).

Mirrors ``specs/026-autonomous-work-board/data-model.md``. Lives at the top
level, like ``models_workflow.py``, rather than under ``app.services``,
because both ``app.persistence`` (board stores) and ``app.services``
(board policy/service) need it and the layering contract forbids
persistence from importing services (``.importlinter``). Nothing here
depends on persistence, routers, or adapters — see
``app/services/board/policy.py`` for the pure functions operating on these
types, and ``app/persistence/board_tables.py`` for the ORM rows these are
read from and written to.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class CardState(StrEnum):
    """Universal card states (FR-002). See data-model.md's allowed-origins
    table for which transitions are legal between them."""

    READY = "ready"
    CLAIMED = "claimed"
    WAITING_DEPENDENCY = "waiting_dependency"
    AWAITING_HUMAN = "awaiting_human"
    REVIEW = "review"
    QUARANTINED = "quarantined"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


#: Terminal states accept no further transition.
TERMINAL_STATES = frozenset(
    {CardState.DONE, CardState.FAILED, CardState.CANCELLED}
)


class CardKind(StrEnum):
    """Closed card-kind vocabulary for this feature (FR-037 allows it to
    grow later without changing the universal states). Gate kinds are
    resolved by the operator directly; no specialist ever claims one."""

    UNDERSTANDING_GATE = "understanding_gate"
    REFINEMENT_GATE = "refinement_gate"
    PRD_GATE = "prd_gate"
    DECOMPOSITION_GATE = "decomposition_gate"
    SECURITY_REVIEW = "security_review"
    ANALYSIS = "analysis"
    DESIGN = "design"
    IMPLEMENTATION = "implementation"
    VERIFICATION = "verification"
    RECONCILIATION = "reconciliation"


#: Human-gate kinds: no specialist claims these, only the operator resolves
#: them (data-model.md "Human Gate and Security Review").
GATE_CARD_KINDS = frozenset(
    {
        CardKind.UNDERSTANDING_GATE,
        CardKind.REFINEMENT_GATE,
        CardKind.PRD_GATE,
        CardKind.DECOMPOSITION_GATE,
    }
)


class RelationKind(StrEnum):
    """Kinds of directed edge between two cards (board-api.md)."""

    DEPENDENCY = "dependency"
    RECONCILIATION = "reconciliation"
    SUPERSEDES = "supersedes"


class CardAction(StrEnum):
    """Operator interventions permitted against a card (board-api.md)."""

    RETRY = "retry"
    CANCEL = "cancel"
    REASSIGN = "reassign"
    RESOLVE_GATE = "resolve_gate"
    RELEASE_QUARANTINE = "release_quarantine"
    DISCARD_QUARANTINE = "discard_quarantine"
    REQUEST_COORDINATOR_REVIEW = "request_coordinator_review"


class WorkspacePermission(StrEnum):
    """A card's or specialist's ceiling on repository workspace access."""

    NONE = "none"
    READ_ONLY = "read_only"
    WRITE = "write"


@dataclass(frozen=True)
class Workflow:
    """The durable aggregate for one accepted task (data-model.md).

    :param id: Stable opaque identifier.
    :param source: Source-native origin (e.g. ``"github-issue"``).
    :param task_ref: Source-native task identity; unique with ``source``.
    :param repo: Repository context, fixed before any write work.
    :param base_branch: The branch write work will target.
    :param source_visibility: ``public`` or ``private``, copied from the
        source at creation and never changed by later configuration.
    :param title: Safe display title after input acceptance.
    :param state: Summary state derived from active cards and outcome.
    :param revision: Monotonic version for snapshots and interventions.
    """

    id: str
    source: str
    task_ref: str
    repo: str
    base_branch: str
    source_visibility: str
    title: str
    state: str = "active"
    revision: int = 1


@dataclass(frozen=True)
class ClaimRequest:
    """The parameters of one atomic claim attempt.

    :param card_id: The card to claim.
    :param specialist_id: The claiming specialist's id.
    :param lease_seconds: How long the claim lease lasts.
    :param backend_id: The backend the attempt will run on, if known.
    :param workspace_repo: When set, also acquire this repository's write
        lease; fails the whole claim if it is already held.
    :param workspace_lease_seconds: Workspace lease duration; defaults to
        ``lease_seconds`` when unset.
    """

    card_id: str
    specialist_id: str
    lease_seconds: float
    backend_id: str | None = None
    workspace_repo: str | None = None
    workspace_lease_seconds: float | None = None


@dataclass(frozen=True)
class WorkCard:
    """One typed, policy-governed unit of work (data-model.md).

    :param id: Stable card identity.
    :param workflow_id: The owning workflow.
    :param kind: The closed card-kind vocabulary entry.
    :param title: Safe operator-facing label.
    :param state: Current universal state.
    :param eligible_roles: Validated specialist ids; never self-assigned.
    :param workspace_permission: Ceiling on repository access this card
        grants its claimant; ``write`` requires a workspace lease.
    :param attempt_limit: Bounded retry authority.
    :param attempt_count: Attempts made so far.
    :param wait_reason: Safe explanation when not ``ready``.
    """

    id: str
    workflow_id: str
    kind: CardKind
    title: str
    state: CardState
    eligible_roles: tuple[str, ...] = ()
    workspace_permission: WorkspacePermission = WorkspacePermission.NONE
    attempt_limit: int = 1
    attempt_count: int = 0
    wait_reason: str | None = None


@dataclass(frozen=True)
class CardRelation:
    """A directed edge between two cards in one workflow's graph.

    :param card_id: The dependent card.
    :param depends_on_card_id: The card ``card_id`` depends on.
    :param kind: The relationship kind; only ``dependency`` edges gate
        readiness (see :func:`app.services.board.policy.dependencies_met`).
    """

    card_id: str
    depends_on_card_id: str
    kind: RelationKind = RelationKind.DEPENDENCY


@dataclass(frozen=True)
class ClaimLease:
    """A time-bounded, durable assignment of a card to one specialist.

    :param card_id: The claimed card.
    :param attempt_sequence: This claim's attempt number for the card.
    :param specialist_id: The claiming specialist's id.
    :param expires_at: When the lease is considered abandoned.
    """

    card_id: str
    attempt_sequence: int
    specialist_id: str
    expires_at: datetime


@dataclass(frozen=True)
class WorkspaceLease:
    """A repository write lease; at most one active per repository.

    :param repo: The repository this lease guards.
    :param claim_card_id: The card whose claim holds this lease.
    :param expires_at: When the lease is considered abandoned.
    """

    repo: str
    claim_card_id: str
    expires_at: datetime


@dataclass(frozen=True)
class SpecialistDefinition:
    """One operator-owned role contract (data-model.md "Specialist
    Definition"; FR-007).

    :param id: Stable machine id; matches its directory name under
        ``specialists_root``.
    :param label: Human-readable name shown on the board.
    :param purpose: One-line role summary.
    :param allowed_card_types: Card kinds this specialist may claim; empty
        for a role that never claims a card (e.g. the coordinator).
    :param required_abilities: Backend ``Capability`` values this role
        needs (see ``app/backends/base.py``).
    :param model_policy: ``"default"`` for the configured default session
        backend, or a specific backend id.
    :param workspace_permission: ``none``, ``read_only``, or ``write``.
    :param retry_limit: Maximum attempts before escalation.
    :param prompt: The role's prompt content, loaded from its prompt file.
    """

    id: str
    label: str
    purpose: str
    allowed_card_types: tuple[str, ...]
    required_abilities: tuple[str, ...]
    model_policy: str
    workspace_permission: str
    retry_limit: int
    prompt: str


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
    """

    workflow_id: str
    event_type: str
    card_id: str | None = None
    payload: str = "{}"
    causation_id: str | None = None
    correlation_id: str | None = None


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
    """

    source: str
    task_ref: str
    repo: str
    base_branch: str
    source_visibility: str
    title: str


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
    :param review_state: ``"pending"``, ``"released"``, or ``"discarded"``.
    :param resolution: Operator-recorded resolution note, once decided.
    """

    id: str
    untrusted_input_id: str
    card_id: str
    workflow_id: str
    classification_category: str
    review_state: str
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
    safe_content: str | None = None
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
