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
    :param review_state: ``pending``, ``released``, or ``discarded``.
    :param resolution: Operator-recorded resolution note, once decided.
    """

    id: str
    card_id: str
    workflow_id: str
    classification_category: str
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


class WorkCardSummaryOut(BaseModel):
    """One card's board-visible state (board-api.md ``CardSummary``).

    :param dependency_count: How many ``dependency``-kind edges this card
        has, not their resolution — the detail view carries the full
        relationship list.
    :param allowed_actions: This card's currently valid interventions
        (``app.services.board.interventions.allowed_actions_for``).
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


class WorkCardRelationOut(BaseModel):
    """One directed edge in a workflow's card graph."""

    card_id: str
    depends_on_card_id: str
    kind: str


class BoardSnapshotOut(BaseModel):
    """One workflow's full board (board-api.md "Board Snapshot").

    ``revision`` is the client's optimistic-concurrency token: every
    intervention against a card in this snapshot must echo it back as
    ``expected_revision``.
    """

    id: str
    revision: int
    task_label: str
    status: str
    cards: list[WorkCardSummaryOut]
    relationships: list[WorkCardRelationOut]
    state_counts: dict[str, int]


class WorkflowSummaryOut(BaseModel):
    """One workflow's row in the board collection listing."""

    id: str
    task_label: str
    status: str
    state_counts: dict[str, int]
    action_required_count: int


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
    ]
    expected_revision: int
    decision: str | None = None


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
