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
from dataclasses import dataclass

from app.models_board import CardAction, CardKind, CardState, WorkCard
from app.persistence.board_claims_store import BoardClaimsStore
from app.persistence.board_store import BoardStore
from app.services.board.dependents import advance_ready_dependents
from app.services.board.gates import GatesService, UnknownGateError
from app.services.board.interview_answers import (
    GateNotOpenError,
    IncompleteAnswerError,
)
from app.services.board.service import BoardService

#: DONE and CANCELLED are hard-terminal; FAILED may still be cancelled
#: (an operator giving up rather than retrying), so it is deliberately
#: excluded from this set.
_CANCEL_BLOCKED_STATES = frozenset(
    {CardState.DONE.value, CardState.CANCELLED.value}
)


@dataclass(frozen=True)
class GateResolution:
    """A ``resolve_gate`` action's payload (T078).

    Bundled to keep :meth:`InterventionsService.apply`'s argument count
    within the repo's limit. Ignored for every action but
    ``resolve_gate``.
    """

    decision: str | None = None
    answer: str | None = None


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
        resolution: GateResolution | None = None,
    ) -> WorkCard:
        """Validate and apply *action* against *card_id*.

        :param resolution: The decision (and, for T078, an optional
            free-text answer/feedback) for a ``resolve_gate`` action.
            Ignored for every other action.
        :raises StaleInterventionError: If ``expected_revision`` no
            longer matches the workflow's current revision — or, for
            ``resolve_gate``, if the gate is no longer open. A gate's
            question or decision does not change while it waits, so
            unrelated work moving the request on must not reject the
            operator's answer (feature 037); the gate being open is the
            check that matters.
        :raises InvalidInterventionError: If the workflow/card is unknown
            or *action* is not permitted for the card's current state.
        """
        workflow = self._store.get_workflow(workflow_id)
        if workflow is None:
            raise InvalidInterventionError(f"unknown workflow: {workflow_id}")
        gate_scoped = action == CardAction.RESOLVE_GATE
        if not gate_scoped and workflow.revision != expected_revision:
            raise StaleInterventionError(
                f"expected revision {expected_revision}, "
                f"board is at {workflow.revision}"
            )
        card = self._store.get_card(card_id)
        if card is None:
            raise InvalidInterventionError(f"unknown card: {card_id}")
        return self._dispatch(card, action, resolution or GateResolution())

    def _dispatch(
        self, card: WorkCard, action: CardAction, resolution: GateResolution
    ) -> WorkCard:
        handlers = {
            CardAction.RETRY: self._retry,
            CardAction.CANCEL: self._cancel,
            CardAction.REASSIGN: self._reassign,
            CardAction.RESOLVE_GATE: lambda c: self._resolve_gate(
                c, resolution
            ),
            CardAction.REQUEST_COORDINATOR_REVIEW: (
                self._request_coordinator_review
            ),
            CardAction.COMPLETE_MANUAL_TASK: self._complete_manual_task,
        }
        handler = handlers.get(action)
        if handler is None:
            raise InvalidInterventionError(
                f"unsupported intervention: {action}"
            )
        return handler(card)

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

    def _resolve_gate(
        self, card: WorkCard, resolution: GateResolution
    ) -> WorkCard:
        if resolution.decision is None:
            raise InvalidInterventionError(
                "resolve_gate requires a decision"
            )
        try:
            return self._gates_service.resolve(
                card.id, resolution.decision, answer=resolution.answer
            )
        except GateNotOpenError as exc:
            raise StaleInterventionError(str(exc)) from exc
        except (UnknownGateError, IncompleteAnswerError) as exc:
            raise InvalidInterventionError(str(exc)) from exc

    def _complete_manual_task(self, card: WorkCard) -> WorkCard:
        """Mark the operator's own manual task done, releasing every card
        waiting on it (feature 031, FR-007/FR-008)."""
        if not _is_open_manual_task(card):
            raise InvalidInterventionError(
                f"cannot complete a {card.kind} card in state {card.state}"
            )
        done = self._board_service.transition_card(
            card.id, CardState.DONE.value, event_type="manual_task.completed"
        )
        advance_ready_dependents(
            self._store, self._board_service, card.workflow_id
        )
        return done

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
    if _is_open_manual_task(card):
        actions.append(CardAction.COMPLETE_MANUAL_TASK)
    elif card.state == CardState.AWAITING_HUMAN.value:
        actions.append(CardAction.RESOLVE_GATE)
    if card.state not in _CANCEL_BLOCKED_STATES:
        actions.append(CardAction.REQUEST_COORDINATOR_REVIEW)
    return actions


def _is_open_manual_task(card: WorkCard) -> bool:
    """A manual task the operator can mark done right now."""
    return (
        card.kind == CardKind.MANUAL_TASK.value
        and card.state == CardState.AWAITING_HUMAN.value
    )
