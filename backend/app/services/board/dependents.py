"""Shared dependency-ready cascade (feature 026).

Both an accepted specialist result (``artifacts.py``) and an approved
gate (``gates.py``) can be the last thing a ``waiting_dependency`` card
was blocked on; both cascade the same way once their own transition
commits, so the cascade itself lives in one place.
"""
from __future__ import annotations

from app.models_board import CardState
from app.persistence.board_store import BoardStore
from app.services.board.policy import dependencies_met
from app.services.board.service import BoardService


def advance_ready_dependents(
    store: BoardStore, board_service: BoardService, workflow_id: str
) -> None:
    """Move every ``waiting_dependency`` card whose dependencies are now
    met to ``ready``."""
    cards = store.list_cards(workflow_id)
    relations = store.list_relations(workflow_id)
    states = {c.id: CardState(c.state) for c in cards}
    for card in cards:
        if card.state != CardState.WAITING_DEPENDENCY.value:
            continue
        if dependencies_met(card.id, relations, states):
            board_service.transition_card(
                card.id, CardState.READY.value, event_type="card.dependency_met"
            )
