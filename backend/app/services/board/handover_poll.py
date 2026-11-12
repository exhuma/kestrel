"""Watching the work items of approved tasks (#99).

On a source that can say who has a work item (``supports_handover``,
Jira), nothing an approved plan holds starts on its own: each task's
head card waits in ``waiting_handover``. Every
``board_handover_poll_interval_seconds`` this loop reads the work items
of each request still in progress, in one batch per request, and acts on
what it finds:

- **handed to kestrel** (assigned to kestrel's account, or matching the
  source's ``work_items_jql``): the head card goes to
  ``waiting_dependency``, and the dependency cascade makes it ``ready``
  once its prerequisites are done;
- **done** while waiting: a person finished it. The head card is done
  without running, its verification is cancelled, and the tasks that
  depend on it may start;
- **no longer kestrel's, and not done**, after kestrel took it: the task
  is handed back (``handback.py``).

An item that does not exist yet (no ledger row for it) is left waiting;
a source that cannot be read is tried again on the next pass.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.models_board import (
    TERMINAL_STATES,
    CardKind,
    CardState,
    WorkCard,
    Workflow,
)
from app.persistence.board_store import BoardStore
from app.ports import TaskSource, WorkItemState
from app.services.board import decision_log
from app.services.board.coordinator import CoordinatorService
from app.services.board.delivery_readiness import (
    kestrel_built,
    request_delivery,
)
from app.services.board.dependents import advance_ready_dependents
from app.services.board.handback import (
    HandbackDeps,
    hand_back,
    handed_back,
    keep_stopped,
)
from app.services.board.task_heads import DONE_BY_PERSON, task_heads
from app.services.board.work_items import work_item_key
from app.services.task_sources import TaskSourceRegistry

_log = logging.getLogger("kestrel.board.handover_poll")

#: Head card states in which kestrel has taken a task on.
_TAKEN = frozenset({
    CardState.WAITING_DEPENDENCY.value,
    CardState.READY.value,
    CardState.CLAIMED.value,
})


@dataclass(frozen=True)
class HandoverDeps:
    """What the poll reads and acts through, bundled for the argument
    limit."""

    handback: HandbackDeps
    task_sources: TaskSourceRegistry
    coordinator: CoordinatorService
    interval_seconds: float


def handover_supported(
    store: BoardStore, task_sources: TaskSourceRegistry, workflow_id: str
) -> bool:
    """Whether *workflow_id*'s task source can say who has a work item,
    so that its approved tasks wait to be handed to kestrel."""
    workflow = store.get_workflow(workflow_id)
    source = (
        task_sources.sources.get(workflow.source)
        if workflow is not None else None
    )
    return source is not None and source.supports_handover()


class HandoverPollService:
    """Reads the work items of approved tasks and acts on who has them."""

    def __init__(self, deps: HandoverDeps) -> None:
        self._deps = deps

    async def run_forever(self) -> None:
        """Poll until cancelled; one bad cycle never stops the loop."""
        while True:
            try:
                await self.poll_once()
            except Exception:  # the loop must outlive a cycle
                _log.exception("hand-over poll cycle failed")
            await asyncio.sleep(self._deps.interval_seconds)

    async def poll_once(self) -> None:
        """One pass over every request still in progress."""
        for workflow in self._deps.handback.store.list_workflows():
            source = self._source(workflow)
            if source is None:
                continue
            try:
                await self._poll(workflow, source)
            except Exception:  # one request must not stop the others
                _log.exception(
                    "hand-over poll failed for a request",
                    extra={"workflow_id": workflow.id},
                )

    def _source(self, workflow: Workflow) -> TaskSource | None:
        if workflow.state == "quarantined":
            return None
        source = self._deps.task_sources.sources.get(workflow.source)
        if source is None or not source.supports_handover():
            return None
        return source

    async def _poll(self, workflow: Workflow, source: TaskSource) -> None:
        cards = self._deps.handback.store.list_cards(workflow.id)
        if all(card.state in TERMINAL_STATES for card in cards):
            return
        watched = self._watched(workflow.id, cards)
        if not watched:
            return
        try:
            states = await source.work_item_states(list(watched))
        except Exception:  # the source is down: try again next pass
            _log.warning(
                "work items could not be read; trying again next pass",
                extra={"workflow_id": workflow.id}, exc_info=True,
            )
            return
        decisions = [
            await self._decide(
                workflow, (source, ref), watched[ref], states[ref]
            )
            for ref in watched if ref in states
        ]
        self._follow_up(workflow.id, decisions)

    def _watched(
        self, workflow_id: str, cards: list[WorkCard]
    ) -> dict[str, WorkCard]:
        """The head cards to read the work items of, by item ref. A
        handed-back task is kept stopped instead of read again."""
        projections = self._deps.handback.projections
        watched: dict[str, WorkCard] = {}
        for head in task_heads(cards):
            node = head.task_node_id or ""
            ref = projections.external_id(work_item_key(workflow_id, node))
            if not ref:
                continue  # the item is not created yet: keep waiting
            if handed_back(projections, workflow_id, node):
                keep_stopped(self._deps.handback, head, ref)
            elif _open(head, cards):
                watched[ref] = head
        return watched

    async def _decide(
        self,
        workflow: Workflow,
        item: tuple[TaskSource, str],
        head: WorkCard,
        state: WorkItemState,
    ) -> str | None:
        """Act on one work item's state (*item*: its source and ref);
        returns what was decided."""
        decision = _decision(head, state, self._deps.handback.store)
        if decision is None:
            return None
        if decision == "handed_over":
            self._deps.handback.board.transition_card(
                head.id, CardState.WAITING_DEPENDENCY.value,
                event_type="card.handed_over",
            )
        elif decision == "done_by_person":
            self._done_by_person(head)
        else:
            await hand_back(self._deps.handback, workflow, head, item)
        decision_log.handover(head, item[1], decision)
        return decision

    def _done_by_person(self, head: WorkCard) -> None:
        """A person finished the task: its head card is done without
        running, and the task's verification has nothing to check."""
        board = self._deps.handback.board
        board.transition_card(
            head.id, CardState.DONE.value,
            event_type="card.done_by_person", wait_reason=DONE_BY_PERSON,
        )
        for card in self._deps.handback.store.list_cards(head.workflow_id):
            if (
                card.task_node_id == head.task_node_id
                and card.kind == CardKind.VERIFICATION.value
                and card.state not in TERMINAL_STATES
            ):
                board.transition_card(
                    card.id, CardState.CANCELLED.value,
                    event_type="card.done_by_person",
                )

    def _follow_up(self, workflow_id: str, decisions: list[str | None]) -> None:
        """Let the cascade move what the decisions unblocked, and deliver
        once a person's task was the last thing holding delivery."""
        if not any(decisions):
            return
        deps = self._deps.handback
        advance_ready_dependents(deps.store, deps.board, workflow_id)
        if "done_by_person" not in decisions:
            return
        if kestrel_built(deps.store.list_cards(workflow_id)):
            request_delivery(workflow_id, deps.store, self._deps.coordinator)


def _decision(
    head: WorkCard, state: WorkItemState, store: BoardStore
) -> str | None:
    """What one work item's state means for its task, or ``None``."""
    if head.state == CardState.WAITING_HANDOVER.value:
        if state.done:
            return "done_by_person"
        return "handed_over" if state.handed_to_kestrel else None
    if state.handed_to_kestrel or state.done:
        return None
    taken = head.state in _TAKEN or _verifying(
        head, store.list_cards(head.workflow_id)
    )
    return "handed_back" if taken else None


def _open(head: WorkCard, cards: list[WorkCard]) -> bool:
    """Whether *head*'s task can still change: its head card waits or
    works, or its verification is still open."""
    return (
        head.state == CardState.WAITING_HANDOVER.value
        or head.state in _TAKEN
        or _verifying(head, cards)
    )


def _verifying(head: WorkCard, cards: list[WorkCard]) -> bool:
    return any(
        c.task_node_id == head.task_node_id
        and c.kind == CardKind.VERIFICATION.value
        and c.state not in TERMINAL_STATES
        for c in cards
    )
