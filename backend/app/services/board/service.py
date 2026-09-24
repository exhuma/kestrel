"""The board application service (feature 026, FR-005).

Reads, revision increments, policy-mediated transitions, and safe event
append. This is the *only* path that mutates card state directly from a
known-good decision — coordinator actions, interventions, and recovery all
route through it rather than touching ``BoardStore`` themselves, so policy
is enforced consistently regardless of what triggered the transition.
"""
from __future__ import annotations

import uuid

from app.models_board import (
    AcceptedTaskIntake,
    BoardEventRecord,
    CardKind,
    CardState,
    WorkCard,
    Workflow,
)
from app.persistence.board_store import BoardStore
from app.services.board.policy import PolicyViolation, is_valid_transition
from app.storage.workflow_bus import WorkflowBus


class BoardService:
    """Policy-mediated reads, transitions, and event append."""

    def __init__(
        self, store: BoardStore, bus: WorkflowBus | None = None
    ) -> None:
        self._store = store
        self._bus = bus

    def get_workflow(self, workflow_id: str) -> Workflow | None:
        """Return one workflow by id, or ``None`` if it does not exist."""
        return self._store.get_workflow(workflow_id)

    def get_card(self, card_id: str) -> WorkCard | None:
        """Return one card by id, or ``None`` if it does not exist."""
        return self._store.get_card(card_id)

    def list_cards(self, workflow_id: str) -> list[WorkCard]:
        """Return every card belonging to *workflow_id*."""
        return self._store.list_cards(workflow_id)

    def list_events(self, workflow_id: str) -> list[BoardEventRecord]:
        """Return every board event for *workflow_id*, oldest first."""
        return self._store.list_events(workflow_id)

    def create_workflow_from_intake(
        self, intake: AcceptedTaskIntake
    ) -> Workflow:
        """Create a workflow and its initial understanding-gate card (FR-001,
        FR-016) for a safety-cleared task.

        :raises WorkflowAlreadyExistsError: If this (source, task_ref)
            already has a workflow — the durable de-dup guard for a
            ticket delivered by both a webhook and a poll cycle.
        """
        workflow = Workflow(
            id=f"wf-{uuid.uuid4().hex[:8]}",
            source=intake.source,
            task_ref=intake.task_ref,
            repo=intake.repo,
            base_branch=intake.base_branch,
            source_visibility=intake.source_visibility,
            title=intake.title,
        )
        self._store.create_workflow(workflow)
        card = WorkCard(
            id=f"card-{uuid.uuid4().hex[:8]}",
            workflow_id=workflow.id,
            kind=CardKind.UNDERSTANDING_GATE,
            title="Confirm understanding",
            state=CardState.AWAITING_HUMAN,
        )
        self._store.create_card(card)
        self._store.append_event(
            BoardEventRecord(
                workflow_id=workflow.id, event_type="workflow.created"
            )
        )
        if self._bus is not None:
            self._bus.publish(workflow.id)
        return workflow

    def transition_card(
        self,
        card_id: str,
        target_state: str,
        *,
        event_type: str,
        wait_reason: str | None = None,
    ) -> WorkCard:
        """Move a card to *target_state* if policy allows it.

        :param card_id: The card to transition.
        :param target_state: The state to move it to.
        :param event_type: A safe, closed event-type identifier recorded
            for this transition.
        :param wait_reason: Safe explanation, when entering a waiting state.
        :raises PolicyViolation: if the card is unknown or the transition
            is not allowed from its current state.
        """
        card = self._store.get_card(card_id)
        if card is None:
            raise PolicyViolation(f"unknown card: {card_id}")
        from_state = CardState(card.state)
        to_state = CardState(target_state)
        if not is_valid_transition(from_state, to_state):
            raise PolicyViolation(
                f"cannot transition card {card_id} from {card.state} "
                f"to {target_state}"
            )
        self._store.set_card_state(
            card_id, target_state, wait_reason=wait_reason
        )
        self._store.append_event(
            BoardEventRecord(
                workflow_id=card.workflow_id,
                card_id=card_id,
                event_type=event_type,
            )
        )
        self._store.bump_workflow_revision(card.workflow_id)
        if self._bus is not None:
            self._bus.publish(card.workflow_id)
        return self._store.get_card(card_id)
