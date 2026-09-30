"""PRD-rejection triage routing (feature 028).

Split out of ``gates.py`` purely to stay within the repo's 500-line
module cap — this is not a distinct domain concern, it is
``GatesService.resolve()``'s own rejection-branch behavior, just as
tightly coupled to gate resolution as the methods that stayed there.

A ``prd_gate`` rejection is routed to the coordinator for fix-vs-
reinterview triage (see ``coordinator.py``'s own wake-up turn and
``refinement.gather_refinement_context``, which already surfaces the
rejection feedback into that turn's envelope), capped so an
unconvergeable PRD fails visibly instead of redrafting forever.
"""
from __future__ import annotations

import uuid

from app.models_board import CardKind, CardState, WorkCard
from app.persistence.board_store import BoardStore
from app.services.board.coordinator import CoordinatorService, CreateCardAction


def maybe_redraft_prd(
    prd_gate: WorkCard,
    store: BoardStore,
    coordinator: CoordinatorService | None,
    redraft_cap: int,
) -> None:
    """Route *prd_gate*'s rejection, or no-op for any other gate kind.

    Falls back to the pre-028 unconditional, uncapped redraft when
    *coordinator* is ``None`` — most existing tests/callers don't need
    PRD-redraft enforcement (mirrors ``DispatchServices.coordinator``
    being optional elsewhere in this codebase).
    """
    if prd_gate.kind != CardKind.PRD_GATE.value:
        return
    if coordinator is None:
        _redraft_directly(prd_gate, store)
        return
    if _redrafts_so_far(prd_gate.workflow_id, store) >= redraft_cap:
        _escalate_cap(prd_gate, coordinator)
    else:
        _request_triage(prd_gate, coordinator)


def _redrafts_so_far(workflow_id: str, store: BoardStore) -> int:
    """How many ``prd_gate`` cards beyond the original draft's own
    exist for *workflow_id* — the count of redrafts already made."""
    total = sum(
        1 for c in store.list_cards(workflow_id)
        if c.kind == CardKind.PRD_GATE.value
    )
    return max(total - 1, 0)


def _redraft_directly(prd_gate: WorkCard, store: BoardStore) -> None:
    """The pre-028 fallback: deterministically create a fresh ``prd``
    card, unconditional and uncapped."""
    store.create_card(
        WorkCard(
            id=f"card-{uuid.uuid4().hex[:8]}",
            workflow_id=prd_gate.workflow_id,
            kind=CardKind.PRD.value,
            title="Redraft PRD",
            state=CardState.READY,
            eligible_roles=("pm",),
        )
    )


def _request_triage(
    prd_gate: WorkCard, coordinator: CoordinatorService
) -> None:
    """Ask the coordinator's next wake-up turn to judge this rejection
    — reused, not re-derived: the rejection feedback and interview
    history it needs are already gathered by
    ``refinement.gather_refinement_context`` into that same turn's
    envelope (``dispatch.py::build_coordinator_envelope``)."""
    coordinator.apply_actions(
        prd_gate.workflow_id, f"prd_redraft:{prd_gate.id}",
        [
            CreateCardAction(
                kind=CardKind.COORDINATOR_REVIEW.value,
                title=f"PRD rejected on card {prd_gate.id} — decide "
                "whether to redraft directly or return to the "
                "interview",
                source_card_id=prd_gate.id,
            )
        ],
    )


def _escalate_cap(prd_gate: WorkCard, coordinator: CoordinatorService) -> None:
    """Final escalation once the redraft cap is reached — mirrors
    ``ci_poll.py``'s own budget-exhausted escalation shape, never
    auto-resolved, so it stays visible to the operator."""
    coordinator.apply_actions(
        prd_gate.workflow_id, f"prd_redraft:{prd_gate.workflow_id}:exhausted",
        [
            CreateCardAction(
                kind=CardKind.COORDINATOR_REVIEW.value,
                title="PRD redraft budget exhausted — operator "
                "intervention required",
                source_card_id=prd_gate.id,
            )
        ],
    )
