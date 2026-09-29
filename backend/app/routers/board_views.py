"""Board DTO assembly: pure mapping from domain objects to safe API views
(feature 026, T057/T058, board-api.md).

Kept separate from ``routers/board.py`` so the route handlers stay thin;
every function here is a pure read — no store/service call of its own —
so a route only needs to gather the raw domain data once per request.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.models_board import (
    CardKind,
    CardRelation,
    CardState,
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
from app.services.board.gates import GatesService
from app.services.board.interventions import allowed_actions_for
from app.services.board.phases import current_phase, stage_of
from app.services.board.specialists import SpecialistRoster

#: Card states an operator needs to look at (board-api.md
#: ``action_required_count``): a decision, retry, or review, not just
#: routine in-progress work.
_ACTION_REQUIRED_STATES = frozenset({"awaiting_human", "quarantined", "failed"})

#: A manual task in either state no longer asks anything of the operator.
_CLOSED_STATES = frozenset({CardState.DONE.value, CardState.CANCELLED.value})


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
    #: card_id -> (round, cap), populated only for a ``refinement_gate``
    #: whose persona is recoverable (feature 029 A3).
    gate_rounds: dict[str, tuple[int, int]]


#: ``BoardWorkflowRow.state`` for a synthetic quarantine-hosting workflow
#: (``BoardQuarantineStore._create_hosting_workflow``); never used for a
#: workflow accepted through ordinary intake, and never changed after
#: creation, so it reliably marks a placeholder row.
_QUARANTINE_WORKFLOW_STATE = "quarantined"


def visible_workflows(workflows: list[Workflow]) -> list[Workflow]:
    """Collapse a quarantine placeholder into its real workflow, once one
    exists for the same ticket (GitHub #45).

    A quarantine review that later clears leaves its synthetic hosting
    workflow behind forever (nothing ever deletes or repurposes it), and
    a subsequent ingest of the same ticket creates a second, real
    workflow next to it — one ticket, two board entries. A still-pending
    quarantine (no real workflow yet) is left alone: its one row *is*
    the request, shown in its quarantined state.
    """
    real_refs = {
        (w.source, w.task_ref)
        for w in workflows
        if w.state != _QUARANTINE_WORKFLOW_STATE
    }
    return [
        w
        for w in workflows
        if w.state != _QUARANTINE_WORKFLOW_STATE
        or (w.source, _quarantine_ticket_ref(w)) not in real_refs
    ]


def _quarantine_ticket_ref(workflow: Workflow) -> str:
    """Recover the real ticket ref from a quarantine placeholder's
    ``task_ref``, which is stored as ``"{source}:{ticket}"``
    (``QuarantineService.intake_for_new_task``)."""
    return workflow.task_ref.removeprefix(f"{workflow.source}:")


def state_counts(cards: list[WorkCard]) -> dict[str, int]:
    """Count *cards* by state (board-api.md ``state_counts``)."""
    counts: dict[str, int] = {}
    for card in cards:
        counts[card.state] = counts.get(card.state, 0) + 1
    return counts


def action_required_count(cards: list[WorkCard]) -> int:
    """How many of *cards* currently need an operator's attention."""
    return sum(1 for c in cards if c.state in _ACTION_REQUIRED_STATES)


def open_manual_task_count(cards: list[WorkCard]) -> int:
    """How many of *cards* are manual tasks still open (feature 031)."""
    return sum(
        1 for c in cards
        if c.kind == CardKind.MANUAL_TASK.value
        and c.state not in _CLOSED_STATES
    )


def workflow_summary(
    workflow: Workflow,
    cards: list[WorkCard],
    gates: GatesService,
) -> WorkflowSummaryOut:
    """One workflow's row in the board collection listing."""
    phase = current_phase(cards)
    return WorkflowSummaryOut(
        id=workflow.id,
        task_label=workflow.task_ref,
        title=workflow.title or workflow.task_ref,
        status=workflow.state,
        state_counts=state_counts(cards),
        action_required_count=action_required_count(cards),
        phase=phase,
        stage=stage_of(phase),
        cap_exhausted=_cap_exhausted(cards, gates),
        open_manual_task_count=open_manual_task_count(cards),
    )


def _cap_exhausted(cards: list[WorkCard], gates: GatesService) -> bool:
    """Whether an interview round has hit its cap while still awaiting
    the operator's answer (feature 029 A4) — the board's ``cap-reached``
    treatment, a judgement made here rather than left to client-side
    arithmetic (FR-043)."""
    cap = gates.refinement_round_cap
    for card in cards:
        if card.kind != CardKind.REFINEMENT_GATE.value:
            continue
        if card.state != CardState.AWAITING_HUMAN.value:
            continue
        round_number = gates.gate_round(card, cards)
        if round_number is not None and round_number >= cap:
            return True
    return False


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
        title=workflow.title or workflow.task_ref,
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
        task_body=workflow.task_body,
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
        gate=_gate_detail(card.id, lookups),
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


def _gate_detail(
    card_id: str, lookups: BoardLookups
) -> WorkCardGateOut | None:
    gate = lookups.gates.get(card_id)
    if gate is None:
        return None
    round_state = lookups.gate_rounds.get(card_id)
    return WorkCardGateOut(
        requested_decision=gate.requested_decision,
        decision=gate.decision,
        round=round_state[0] if round_state else None,
        cap=round_state[1] if round_state else None,
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
