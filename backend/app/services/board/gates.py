"""Human-gate resolution and targeted downstream invalidation (feature 026,
T045, FR-016/FR-017).

A gate card is never claimed by a specialist (data-model.md "Card
States") — its own approval or rejection is the only exit from
``awaiting_human``. Approval cascades ready-dependent work the same way
an accepted specialist result does (see ``artifacts.py``); rejection
invalidates only the work that actually named this gate as a dependency,
never the whole workflow (User Story 4).
"""
from __future__ import annotations

import uuid

from app.models_board import CardState, HumanGateRecord, WorkCard
from app.persistence.board_gate_store import BoardGateStore
from app.persistence.board_store import BoardStore
from app.services.board.dependents import advance_ready_dependents
from app.services.board.service import BoardService

_DECISION_TARGET_STATE = {
    "approved": CardState.DONE,
    "rejected": CardState.CANCELLED,
}


class UnknownGateError(Exception):
    """Raised when a card has no gate record to resolve."""


class GatesService:
    """Creates gate cards and resolves their operator decisions."""

    def __init__(
        self,
        store: BoardStore,
        gate_store: BoardGateStore,
        board_service: BoardService,
    ) -> None:
        self._store = store
        self._gate_store = gate_store
        self._board_service = board_service

    def create_gate(
        self,
        workflow_id: str,
        *,
        kind: str,
        title: str,
        requested_decision: str,
        target_artifact_id: str | None = None,
    ) -> WorkCard:
        """Create an ``awaiting_human`` gate card and its decision record."""
        card = WorkCard(
            id=f"card-{uuid.uuid4().hex[:8]}",
            workflow_id=workflow_id,
            kind=kind,
            title=title,
            state=CardState.AWAITING_HUMAN,
        )
        self._store.create_card(card)
        self._gate_store.create_gate(
            HumanGateRecord(
                id=f"gate-{uuid.uuid4().hex[:8]}",
                card_id=card.id,
                requested_decision=requested_decision,
                target_artifact_id=target_artifact_id,
            )
        )
        return card

    def get_gate(self, card_id: str) -> HumanGateRecord | None:
        """Return *card_id*'s gate record, or ``None`` if it has none."""
        return self._gate_store.get_for_card(card_id)

    def resolve(self, card_id: str, decision: str) -> WorkCard:
        """Record the operator's *decision* and apply its consequence.

        :param decision: ``"approved"`` or ``"rejected"``.
        :raises UnknownGateError: If *card_id* has no gate record.
        :raises ValueError: If *decision* is not a recognized value.
        """
        if self._gate_store.get_for_card(card_id) is None:
            raise UnknownGateError(f"no gate for card: {card_id}")
        target = _DECISION_TARGET_STATE.get(decision)
        if target is None:
            raise ValueError(f"unrecognized gate decision: {decision}")
        self._gate_store.record_decision(card_id, decision)
        card = self._board_service.transition_card(
            card_id, target.value, event_type=f"gate.{decision}"
        )
        if decision == "approved":
            advance_ready_dependents(
                self._store, self._board_service, card.workflow_id
            )
        else:
            self._invalidate_dependents(card.workflow_id, card_id)
        return card

    def _invalidate_dependents(self, workflow_id: str, gate_id: str) -> None:
        """Cancel only the not-yet-terminal cards that depended on *gate_id*."""
        relations = self._store.list_relations(workflow_id)
        dependents = {
            r.card_id for r in relations if r.depends_on_card_id == gate_id
        }
        for card in self._store.list_cards(workflow_id):
            if card.id not in dependents or card.id == gate_id:
                continue
            if not self._is_terminal(card.state):
                self._board_service.transition_card(
                    card.id,
                    CardState.CANCELLED.value,
                    event_type="gate.rejected_dependent_cancelled",
                )

    @staticmethod
    def _is_terminal(state: str) -> bool:
        return CardState(state) in {
            CardState.DONE,
            CardState.FAILED,
            CardState.CANCELLED,
        }
