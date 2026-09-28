"""Board DTO assembly: pure mapping from domain objects to safe API views
(feature 026, T057/T058, board-api.md).

Kept separate from ``routers/board.py`` so the route handlers stay thin;
every function here is a pure read — no store/service call of its own —
so a route only needs to gather the raw domain data once per request.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.models_board import (
    CardRelation,
    ClaimLease,
    WorkCard,
    Workflow,
)
from app.models_board_records import (
    BoardEventRecord,
    HandoffArtifact,
    HumanGateRecord,
)
from app.schemas import (
    BoardArtifactRefOut,
    BoardEventOut,
    BoardLeaseOut,
    BoardOwnerOut,
    BoardRoleRefOut,
    BoardSnapshotOut,
    WorkCardGateOut,
    WorkCardRelationOut,
    WorkCardSummaryOut,
    WorkflowSummaryOut,
)
from app.services.board.interventions import allowed_actions_for
from app.services.board.phases import current_phase, stage_of
from app.services.board.specialists import SpecialistRoster

#: Card states an operator needs to look at (board-api.md
#: ``action_required_count``): a decision, retry, or review, not just
#: routine in-progress work.
_ACTION_REQUIRED_STATES = frozenset({"awaiting_human", "quarantined", "failed"})


@dataclass(frozen=True)
class BoardLookups:
    """Per-card data a snapshot needs beyond the card rows themselves."""

    roster: SpecialistRoster
    leases: dict[str, ClaimLease]
    latest_artifacts: dict[str, HandoffArtifact]
    #: card_id -> review id, populated only for ``security_review`` cards.
    security_review_ids: dict[str, str]
    #: card_id -> gate record, populated only for gate-kind cards
    #: (``app.models_board.GATE_CARD_KINDS``) that have one recorded.
    gates: dict[str, HumanGateRecord]


def state_counts(cards: list[WorkCard]) -> dict[str, int]:
    """Count *cards* by state (board-api.md ``state_counts``)."""
    counts: dict[str, int] = {}
    for card in cards:
        counts[card.state] = counts.get(card.state, 0) + 1
    return counts


def action_required_count(cards: list[WorkCard]) -> int:
    """How many of *cards* currently need an operator's attention."""
    return sum(1 for c in cards if c.state in _ACTION_REQUIRED_STATES)


def workflow_summary(
    workflow: Workflow, cards: list[WorkCard]
) -> WorkflowSummaryOut:
    """One workflow's row in the board collection listing."""
    phase = current_phase(cards)
    return WorkflowSummaryOut(
        id=workflow.id,
        task_label=workflow.task_ref,
        status=workflow.state,
        state_counts=state_counts(cards),
        action_required_count=action_required_count(cards),
        phase=phase,
        stage=stage_of(phase),
    )


def board_snapshot(
    workflow: Workflow,
    cards: list[WorkCard],
    relations: list[CardRelation],
    lookups: BoardLookups,
) -> BoardSnapshotOut:
    """One workflow's full board (board-api.md "Board Snapshot")."""
    phase = current_phase(cards)
    return BoardSnapshotOut(
        id=workflow.id,
        revision=workflow.revision,
        task_label=workflow.task_ref,
        status=workflow.state,
        cards=[card_summary(card, relations, lookups) for card in cards],
        relationships=[
            WorkCardRelationOut(
                card_id=r.card_id,
                depends_on_card_id=r.depends_on_card_id,
                kind=r.kind,
            )
            for r in relations
        ],
        state_counts=state_counts(cards),
        phase=phase,
        stage=stage_of(phase),
    )


def card_summary(
    card: WorkCard, relations: list[CardRelation], lookups: BoardLookups
) -> WorkCardSummaryOut:
    """One card's board-visible state (board-api.md ``CardSummary``)."""
    dependency_count = sum(
        1
        for r in relations
        if r.card_id == card.id and r.kind == "dependency"
    )
    lease = lookups.leases.get(card.id)
    roster = lookups.roster
    return WorkCardSummaryOut(
        id=card.id,
        title=card.title,
        card_type=card.kind,
        state=card.state,
        eligible_roles=[_role_ref(roster, r) for r in card.eligible_roles],
        owner=_owner(roster, lease),
        lease=_lease_ref(lease),
        waiting_reason=card.wait_reason,
        dependency_count=dependency_count,
        latest_artifact=_artifact_ref(lookups.latest_artifacts.get(card.id)),
        allowed_actions=[a.value for a in allowed_actions_for(card)],
        security_review_id=lookups.security_review_ids.get(card.id),
        gate=_gate_detail(lookups.gates.get(card.id)),
    )


def _role_ref(roster: SpecialistRoster, role_id: str) -> BoardRoleRefOut:
    specialist = roster.get(role_id)
    label = specialist.label if specialist is not None else role_id
    return BoardRoleRefOut(id=role_id, label=label)


def _owner(
    roster: SpecialistRoster, lease: ClaimLease | None
) -> BoardOwnerOut | None:
    if lease is None:
        return None
    role = _role_ref(roster, lease.specialist_id)
    return BoardOwnerOut(specialist_id=role.id, label=role.label)


def _lease_ref(lease: ClaimLease | None) -> BoardLeaseOut | None:
    if lease is None:
        return None
    return BoardLeaseOut(
        expires_at=lease.expires_at, attempt=lease.attempt_sequence
    )


def _artifact_ref(
    artifact: HandoffArtifact | None,
) -> BoardArtifactRefOut | None:
    if artifact is None:
        return None
    return BoardArtifactRefOut(
        id=artifact.id,
        label=artifact.logical_name,
        revision=artifact.revision,
    )


def _gate_detail(gate: HumanGateRecord | None) -> WorkCardGateOut | None:
    if gate is None:
        return None
    return WorkCardGateOut(
        requested_decision=gate.requested_decision,
        decision=gate.decision,
    )


def board_events(
    events: list[BoardEventRecord],
    cards: list[WorkCard],
    roster: SpecialistRoster,
) -> list[BoardEventOut]:
    """Map raw board history to the narrative feed's safe shape, oldest
    first (board-api.md "Board Event").

    Specialist attribution is derived from each event's card, not
    recorded on the event itself (feature 026 never records who
    actually acted) — a card's first eligible role stands in for who
    this event is about, since a card kind is eligible to exactly the
    role(s) meant to work it.
    """
    cards_by_id = {card.id: card for card in cards}
    return [_event_out(event, cards_by_id, roster) for event in events]


def _event_out(
    event: BoardEventRecord,
    cards_by_id: dict[str, WorkCard],
    roster: SpecialistRoster,
) -> BoardEventOut:
    card = cards_by_id.get(event.card_id) if event.card_id else None
    specialist = (
        _role_ref(roster, card.eligible_roles[0])
        if card is not None and card.eligible_roles
        else None
    )
    return BoardEventOut(
        event_type=event.event_type,
        card_id=event.card_id,
        payload=event.payload,
        created_at=event.created_at,
        specialist=specialist,
    )
