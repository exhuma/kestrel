"""Response/DTO schemas shared across the service and router layers.

These mirror the frontend business types in ``frontend/src/types/``;
keep them in sync when the API changes (see the type contract in
``.specify/memory/constitution.md``).
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class SessionSummary(BaseModel):
    """Summary of one session for the list endpoint.

    :param session_id: Unique id of the session.
    :param status: Current lifecycle status (e.g. running, idle).
    :param event_count: Number of events recorded so far.
    :param created_at: When the session started, if known.
    :param workflow: The run that used this session ("repo#issue"),
        or None for a free-form session.
    """

    session_id: str
    status: str
    event_count: int
    created_at: datetime | None = None
    workflow: str | None = None


class SecurityReviewOut(BaseModel):
    """Safe, read-only view of a quarantine decision (feature 026).

    Carries only safe metadata (board-api.md) — never the raw suspect
    content that triggered the review (FR-025): full suspect input is
    never copied into an API response, log field, or operator summary.

    :param id: Stable review identity.
    :param card_id: The ``security_review`` card this review gates.
    :param workflow_id: The workflow hosting that card.
    :param classification_category: The deterministic/classifier finding.
    :param reason: The deterministic/classifier's own short, safe
        explanation of *why* — an operator needs this to decide release
        vs. discard, not just the category.
    :param review_state: ``pending``, ``released``, or ``discarded``.
    :param resolution: Operator-recorded resolution note, once decided.
    """

    id: str
    card_id: str
    workflow_id: str
    classification_category: str
    reason: str | None = None
    review_state: Literal["pending", "released", "discarded"]
    resolution: str | None = None


class QuarantineInterventionIn(BaseModel):
    """Request body to resolve a pending security review (FR-022).

    Action names match the board-api.md ``CardAction`` vocabulary.
    """

    action: Literal["release_quarantine", "discard_quarantine"]


class BoardRoleRefOut(BaseModel):
    """One specialist role reference (board-api.md ``CardSummary``)."""

    id: str
    label: str


class BoardOwnerOut(BaseModel):
    """The specialist currently holding a card's claim, if any."""

    specialist_id: str
    label: str


class BoardLeaseOut(BaseModel):
    """A claimed card's active lease (board-api.md ``CardSummary``)."""

    expires_at: datetime
    attempt: int


class BoardArtifactRefOut(BaseModel):
    """A safe pointer to one card's latest artifact — never its content."""

    id: str
    label: str
    revision: int


class WorkCardGateOut(BaseModel):
    """A gate card's decision detail (board-api.md ``CardSummary``).

    Lets the frontend tell an "approve/reject" gate
    (``requested_decision`` of ``confirm_understanding``,
    ``approve_prd``, or ``approve_decomposition``) apart from an
    "answer these questions" gate (``answer``), and shows a decision
    already recorded rather than only the pending ask.

    :param requested_decision: Safe, closed description of what's asked
        (``HumanGateRecord.requested_decision``).
    :param decision: ``None`` until the operator decides; then
        ``"approved"`` or ``"rejected"``.
    :param round: This gate's 1-based interview round (feature 029 A3),
        or ``None`` if it is not a round-capped ``refinement_gate``.
    :param cap: The configured round cap in force when ``round`` is set.
    :param target_artifact: What the gate asks about — the interview's
        questions, the PRD draft, the CAB-2 proposal, the strategic-fit
        answers (``HumanGateRecord.target_artifact_id``). It belongs to
        the card that produced it, never to the gate card itself, so it
        is not the gate's ``latest_artifact``. ``None`` when the gate
        has no target.
    :param persona: For an interview gate, the profile whose human
        answers it (feature 038).
    """

    requested_decision: str
    decision: str | None = None
    round: int | None = None
    cap: int | None = None
    target_artifact: BoardArtifactRefOut | None = None
    persona: BoardRoleRefOut | None = None


class AwaitingOut(BaseModel):
    """Who a card waits on, and for what (feature 035), as codes the
    frontend phrases (``app.services.board.awaiting``). ``role`` names
    the profile whose human answers an interview (feature 038)."""

    actor: Literal["requester", "cab", "you", "operator", "role"]
    ask: str
    role: BoardRoleRefOut | None = None


class WorkCardSummaryOut(BaseModel):
    """One card's board-visible state (board-api.md ``CardSummary``).

    :param dependency_count: How many ``dependency``-kind edges this card
        has, not their resolution — the detail view carries the full
        relationship list.
    :param allowed_actions: This card's currently valid interventions
        (``app.services.board.interventions.allowed_actions_for``).
    :param security_review_id: The pending review this ``security_review``
        card gates, when it has one — lets the frontend address
        ``POST /security-reviews/{id}/resolve`` (release/discard-quarantine
        stay off ``allowed_actions``/``interventions``, see
        ``app.services.board.interventions``).
    :param gate: This card's gate decision detail, for a gate-kind card
        that has one recorded (``app.models_board.GATE_CARD_KINDS``).
    """

    id: str
    title: str
    card_type: str
    state: str
    eligible_roles: list[BoardRoleRefOut]
    owner: BoardOwnerOut | None = None
    lease: BoardLeaseOut | None = None
    waiting_reason: str | None = None
    dependency_count: int
    latest_artifact: BoardArtifactRefOut | None = None
    allowed_actions: list[str]
    security_review_id: str | None = None
    gate: WorkCardGateOut | None = None
    awaiting: AwaitingOut | None = None


class BoardArtifactContentOut(BaseModel):
    """One artifact's full content and trust level.

    The frontend must render ``content`` as text, never as HTML — it is
    agent output crossing into the browser — and must visibly
    distinguish ``agent_output`` from ``operator_approved`` via
    ``trust``.

    :param content: The artifact's raw stored content.
    :param trust: At least ``untrusted``, ``released``, ``agent_output``,
        or ``operator_approved`` (mirrors ``HandoffArtifact.trust``).
    """

    content: str
    trust: str


class WorkCardRelationOut(BaseModel):
    """One directed edge in a workflow's card graph."""

    card_id: str
    depends_on_card_id: str
    kind: str


class PhaseStatusOut(BaseModel):
    """One spine step and its status (feature 034) — display-only, like
    the phase projection itself.

    :param status: ``done``, ``active``, ``waiting``, ``problem``,
        ``skipped`` or ``upcoming``.
    """

    name: str
    status: Literal[
        "done", "active", "waiting", "problem", "skipped", "upcoming"
    ]


class RequestActivityOut(BaseModel):
    """What a request is doing right now (feature 033) — see
    ``app.services.board.activity.RequestActivity``. Structured, not
    phrased: the frontend words it.

    :param state: ``working``, ``problem``, ``waiting``, ``queued``,
        ``done`` or ``stalled``.
    :param actor: Who is working, or who queued work is for.
    :param subject: The card concerned, by title.
    :param detail: For ``problem``: the safe recorded reason.
    :param reason: For ``stalled``: ``interrupted_screening``,
        ``interrupted_claim`` or ``nothing_ready``.
    :param since: When this state began (UTC), as far as is known.
    :param tool: For ``working``: the last tool the agent called
        (feature 036).
    :param tool_calls: For ``working``: tool calls the turn has made.
    """

    state: Literal[
        "working", "problem", "waiting", "queued", "done", "stalled"
    ]
    actor: str | None = None
    subject: str | None = None
    detail: str | None = None
    reason: str | None = None
    since: datetime | None = None
    tool: str | None = None
    tool_calls: int | None = None


class BoardSnapshotOut(BaseModel):
    """One workflow's full board (board-api.md "Board Snapshot").

    ``revision`` is the client's optimistic-concurrency token: every
    intervention against a card in this snapshot must echo it back as
    ``expected_revision``. ``phase``/``stage`` are a pure, derived,
    display-only projection (``app.services.board.phases``) — never a
    driver: they never decide what happens next. ``title`` (feature 029
    A2) falls back to ``task_label`` when unrecorded. ``task_body``
    (feature 030) is the request as screened once at intake and frozen
    since — a later edit to the source ticket is not reflected. It is on
    the snapshot only, never on :class:`WorkflowSummaryOut`: every board
    row carrying a full issue body would bloat the listing for nothing.
    """

    id: str
    revision: int
    task_label: str
    title: str
    status: str
    cards: list[WorkCardSummaryOut]
    relationships: list[WorkCardRelationOut]
    state_counts: dict[str, int]
    phase: str
    stage: str
    task_body: str = ""
    activity: RequestActivityOut | None = None
    phases: list[PhaseStatusOut] = []


class WorkflowSummaryOut(BaseModel):
    """One workflow's row in the board collection listing.

    ``phase``/``stage`` are a pure, derived, display-only projection
    (``app.services.board.phases``) — never a driver. ``title`` (feature
    029 A2) falls back to ``task_label`` when unrecorded.

    :param cap_exhausted: Whether an interview round cap has been hit
        without a usable answer (feature 029 A4) — the board's
        ``cap-reached`` treatment.
    :param open_manual_task_count: How many ``manual_task`` cards are
        neither done nor cancelled (feature 031) — the stage board's
        "N manual tasks assigned to you".
    """

    id: str
    task_label: str
    title: str
    status: str
    state_counts: dict[str, int]
    action_required_count: int
    phase: str
    stage: str
    cap_exhausted: bool = False
    open_manual_task_count: int = 0
    activity: RequestActivityOut | None = None
    awaiting: list[AwaitingOut] = []


class BoardInterventionIn(BaseModel):
    """Request body for one card intervention (board-api.md
    "Intervention").

    ``expected_revision`` is mandatory (optimistic concurrency): a stale
    value is rejected with 409 rather than silently applying to a board
    state the operator never actually saw.
    """

    action: Literal[
        "retry",
        "cancel",
        "reassign",
        "resolve_gate",
        "request_coordinator_review",
        "complete_manual_task",
    ]
    expected_revision: int
    decision: str | None = None
    #: Free-text response for a ``resolve_gate`` action (T078) — a
    #: ``refinement_gate``'s answer, or a ``prd_gate`` rejection's
    #: feedback for `pm`'s redraft. Ignored for every other action.
    answer: str | None = None


class BoardEventOut(BaseModel):
    """One board-history entry (data-model.md "Board Event"), safe for
    the narrative feed.

    :param specialist: The role eligible to own this event's card, when
        it has one — derived from the card's eligible roles at read
        time, not a recorded actor (feature 026 never records who
        actually acted on an event). A workflow-level event (no card) or
        an operator-resolved gate (no eligible role) carries ``None``.
    """

    event_type: str
    card_id: str | None
    payload: str
    created_at: datetime | None
    specialist: BoardRoleRefOut | None = None


class NotificationOut(BaseModel):
    """One notification for the API."""

    id: int
    workflow_id: str
    repo: str
    #: GitHub issue number; ``null`` for a Jira-sourced run (feature 003).
    issue_number: int | None
    status: str
    #: Derived from status: "action_required" gate vs terminal "summary".
    signal_class: str
    message: str
    created_at: datetime
    read: bool


class HealthOut(BaseModel):
    """One configured source's current health (feature 014).

    ``state`` is only ever ``"unknown"``/``"healthy"``/``"unhealthy"`` —
    the underlying cause (network vs. auth) never crosses this boundary.
    """

    name: str
    state: str
    checked_at: datetime | None


class IdentityOut(BaseModel):
    """The authenticated identity, as forwarded by oauth2-proxy.

    All fields are ``null`` when no reverse proxy sits in front of the
    backend (e.g. local dev) — this is not an error state.
    """

    username: str | None
    email: str | None
    preferred_username: str | None
