"""Understanding redrafts after a rejection (feature 032, research R7).

Split out of ``understanding.py`` so ``gates.py``'s rejection branch can
call it without an import cycle (``understanding.py`` routes results
through ``GatesService``), the same reason ``prd_redraft.py`` exists.
"""
from __future__ import annotations

import uuid

from app.models_board import CardKind, CardState, WorkCard
from app.persistence.board_store import BoardStore


def understanding_card(workflow_id: str, *, redraft: bool = False) -> WorkCard:
    """A ready ``understanding`` card for `pm` to write the restatement."""
    return WorkCard(
        id=f"card-{uuid.uuid4().hex[:8]}",
        workflow_id=workflow_id,
        kind=CardKind.UNDERSTANDING.value,
        title="Redraft the understanding" if redraft
        else "Restate the request",
        state=CardState.READY.value,
        eligible_roles=("pm",),
    )


def maybe_redraft_understanding(
    gate: WorkCard, store: BoardStore, cap: int
) -> None:
    """After an ``understanding_gate`` rejection, redraft — or, once
    *cap* redrafts have been made, open a coordinator review instead.
    A no-op for any other gate kind."""
    if gate.kind != CardKind.UNDERSTANDING_GATE.value:
        return
    drafts = sum(
        1 for c in store.list_cards(gate.workflow_id)
        if c.kind == CardKind.UNDERSTANDING.value
    )
    if drafts <= cap:
        store.create_card(understanding_card(gate.workflow_id, redraft=True))
        return
    store.create_card(
        WorkCard(
            id=f"card-{uuid.uuid4().hex[:8]}",
            workflow_id=gate.workflow_id,
            kind=CardKind.COORDINATOR_REVIEW.value,
            title=f"Understanding not confirmed after {drafts} drafts",
            state=CardState.READY.value,
            source_card_id=gate.id,
        )
    )
