"""Policy-mediated operator interventions against board cards (feature 026,
T046, FR-032, board-api.md "Intervention").

Every intervention is checked against the workflow's current revision
before anything else (optimistic concurrency, board-api.md): a stale
request never applies to a board state the operator didn't actually see.
``release_quarantine``/``discard_quarantine`` are deliberately not
handled here — quarantine isn't card-addressed yet (see
``quarantine.py``), so they stay served by the dedicated review-id
endpoint built for User Story 1 (``routers/board.py``).
"""
from __future__ import annotations

import uuid

from app.models_board import CardAction, CardKind, CardState, WorkCard
from app.persistence.board_claims_store import BoardClaimsStore
from app.persistence.board_store import BoardStore
from app.services.board.gates import GatesService
from app.services.board.service import BoardService

#: DONE and CANCELLED are hard-terminal; FAILED may still be cancelled
#: (an operator giving up rather than retrying), so it is deliberately
#: excluded from this set.
_CANCEL_BLOCKED_STATES = frozenset(
    {CardState.DONE.value, CardState.CANCELLED.value}
)


class StaleInterventionError(Exception):
    """Raised when ``expected_revision`` no longer matches the board."""


class InvalidInterventionError(Exception):
    """Raised when the action is not permitted for the card's state."""


class InterventionsService:
    """Validates and applies one operator action against one card."""

    def __init__(
        self,
        store: BoardStore,
        claims_store: BoardClaimsStore,
        board_service: BoardService,
        gates_service: GatesService,
    ) -> None:
        self._store = store
        self._claims_store = claims_store
        self._board_service = board_service
        self._gates_service = gates_service

    def apply(
        self,
        workflow_id: str,
        card_id: str,
        action: CardAction,
        *,
        expected_revision: int,
        decision: str | None = None,
    ) -> WorkCard:
        """Validate and apply *action* against *card_id*.

        :raises StaleInterventionError: If ``expected_revision`` no
            longer matches the workflow's current revision.
        :raises InvalidInterventionError: If the workflow/card is unknown
            or *action* is not permitted for the card's current state.
        """
        workflow = self._store.get_workflow(workflow_id)
        if workflow is None:
            raise InvalidInterventionError(f"unknown workflow: {workflow_id}")
        if workflow.revision != expected_revision:
            raise StaleInterventionError(
                f"expected revision {expected_revision}, "
                f"board is at {workflow.revision}"
            )
        card = self._store.get_card(card_id)
        if card is None:
            raise InvalidInterventionError(f"unknown card: {card_id}")
        return self._dispatch(card, action, decision)

    def _dispatch(
        self, card: WorkCard, action: CardAction, decision: str | None
    ) -> WorkCard:
        if action == CardAction.RETRY:
            return self._retry(card)
        if action == CardAction.CANCEL:
            return self._cancel(card)
        if action == CardAction.REASSIGN:
            return self._reassign(card)
        if action == CardAction.RESOLVE_GATE:
            return self._resolve_gate(card, decision)
        if action == CardAction.REQUEST_COORDINATOR_REVIEW:
            return self._request_coordinator_review(card)
        raise InvalidInterventionError(f"unsupported intervention: {action}")

    def _retry(self, card: WorkCard) -> WorkCard:
        if card.state != CardState.FAILED.value:
            raise InvalidInterventionError(
                f"cannot retry card in state {card.state}"
            )
        return self._board_service.transition_card(
            card.id, CardState.READY.value, event_type="intervention.retry"
        )

    def _cancel(self, card: WorkCard) -> WorkCard:
        if card.state in _CANCEL_BLOCKED_STATES:
            raise InvalidInterventionError(
                f"cannot cancel card in state {card.state}"
            )
        if card.state == CardState.CLAIMED.value:
            self._claims_store.release_claim(card.id)
        return self._board_service.transition_card(
            card.id,
            CardState.CANCELLED.value,
            event_type="intervention.cancel",
        )

    def _reassign(self, card: WorkCard) -> WorkCard:
        if card.state != CardState.CLAIMED.value:
            raise InvalidInterventionError(
                f"cannot reassign card in state {card.state}"
            )
        self._claims_store.release_claim(card.id)
        return self._board_service.transition_card(
            card.id, CardState.READY.value, event_type="intervention.reassign"
        )

    def _resolve_gate(self, card: WorkCard, decision: str | None) -> WorkCard:
        if decision is None:
            raise InvalidInterventionError(
                "resolve_gate requires a decision"
            )
        return self._gates_service.resolve(card.id, decision)

    def _request_coordinator_review(self, card: WorkCard) -> WorkCard:
        review = WorkCard(
            id=f"card-{uuid.uuid4().hex[:8]}",
            workflow_id=card.workflow_id,
            kind=CardKind.COORDINATOR_REVIEW,
            title=f"Review requested: {card.title}",
            state=CardState.READY,
        )
        self._store.create_card(review)
        return review


def allowed_actions_for(card: WorkCard) -> list[CardAction]:
    """The subset of :class:`CardAction` currently valid for *card*.

    Pure precondition check — no ``apply`` call, so it's safe for a
    read-only DTO (board-api.md's ``allowed_actions``) to call on every
    card in a listing without risking a mutation.
    """
    actions: list[CardAction] = []
    if card.state == CardState.FAILED.value:
        actions.append(CardAction.RETRY)
    if card.state not in _CANCEL_BLOCKED_STATES:
        actions.append(CardAction.CANCEL)
    if card.state == CardState.CLAIMED.value:
        actions.append(CardAction.REASSIGN)
    if card.state == CardState.AWAITING_HUMAN.value:
        actions.append(CardAction.RESOLVE_GATE)
    if card.state not in _CANCEL_BLOCKED_STATES:
        actions.append(CardAction.REQUEST_COORDINATOR_REVIEW)
    return actions
