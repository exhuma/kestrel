"""A work item given back to a person after kestrel took it (#99).

Once a task's work item is no longer kestrel's, and not done, while
kestrel is working on it, the task stops: nothing new is dispatched for
it, a turn already running finishes, and whatever follows from that turn
is cancelled on the next pass. The branch keeps its commits. kestrel
posts one note on the work item naming the branch and its last commit,
and puts the request to the change owner as a ``policy_risk_gate``: the
request never delivers part of its work.

The note's ledger row (``handback:<workflow>:<task>``) is what records
that a task was handed back, so every step here is safe to repeat.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.documents import Code, Document, Text, document, paragraph
from app.models_board import CardKind, CardState, WorkCard, Workflow
from app.persistence.board_store import BoardStore
from app.ports import TaskSource
from app.services.board.escalations import RISK_DECISION
from app.services.board.gates import GatesService
from app.services.board.projections import (
    ProjectionRequest,
    ProjectionsService,
)
from app.services.board.service import BoardService
from app.services.board.workspace import WorkspaceService
from app.services.board.write_back import post_projection

#: States in which a card of a handed-back task is stopped: anything not
#: yet running. A claimed card finishes its turn.
_STOPPABLE = frozenset({
    CardState.READY.value,
    CardState.WAITING_DEPENDENCY.value,
    CardState.WAITING_HANDOVER.value,
})


@dataclass(frozen=True)
class HandbackDeps:
    """What a hand-back acts through, bundled for the argument limit."""

    store: BoardStore
    board: BoardService
    projections: ProjectionsService
    gates: GatesService
    workspace: WorkspaceService | None = None


def handback_key(workflow_id: str, task_node_id: str) -> str:
    """The ledger key of the note on a handed-back task's work item."""
    return f"handback:{workflow_id}:{task_node_id}"


def handed_back(
    projections: ProjectionsService, workflow_id: str, task_node_id: str
) -> bool:
    """Whether the task was handed back to a person after kestrel took
    it."""
    return projections.recorded(handback_key(workflow_id, task_node_id))


async def hand_back(
    deps: HandbackDeps,
    workflow: Workflow,
    head: WorkCard,
    item: tuple[TaskSource, str],
) -> None:
    """Record that *head*'s task was handed back, say so once on its work
    item (*item*: the source and the item's ref), and stop the task."""
    source, ref = item
    node = head.task_node_id or ""
    note = await _note(deps.workspace, workflow.id)
    await post_projection(
        ProjectionRequest(
            workflow.id, ref, "handback", handback_key(workflow.id, node),
            note,
        ),
        source, deps.projections,
    )
    keep_stopped(deps, head, ref)


def keep_stopped(deps: HandbackDeps, head: WorkCard, ref: str) -> None:
    """Cancel every card of *head*'s task that is not running yet, and
    make sure the change owner has been asked. Run on every pass, so
    that what a finishing turn creates is cancelled too."""
    for card in deps.store.list_cards(head.workflow_id):
        if card.task_node_id == head.task_node_id and (
            card.state in _STOPPABLE
        ):
            deps.board.transition_card(
                card.id, CardState.CANCELLED.value,
                event_type="card.handed_back",
            )
    _escalate(deps, head, ref)


def _escalate(deps: HandbackDeps, head: WorkCard, ref: str) -> None:
    """Put the request to the change owner, once per handed-back task."""
    cards = deps.store.list_cards(head.workflow_id)
    if any(
        c.kind == CardKind.POLICY_RISK_GATE.value
        and c.source_card_id == head.id
        for c in cards
    ):
        return
    gate = WorkCard(
        id=f"card-{uuid.uuid4().hex[:8]}",
        workflow_id=head.workflow_id,
        kind=CardKind.POLICY_RISK_GATE.value,
        title=f"Work item {ref} was given back: {head.title}",
        state=CardState.AWAITING_HUMAN.value,
        source_card_id=head.id,
    )
    deps.gates.open_gate(gate, RISK_DECISION)


async def _note(
    workspace: WorkspaceService | None, workflow_id: str
) -> Document:
    """The note on the work item: the task stopped, and where kestrel's
    work on it is."""
    commit = (
        await workspace.last_commit(workflow_id)
        if workspace is not None else None
    )
    where = [Text("kestrel has stopped working on this item.")]
    if workspace is not None:
        where += [
            Text(" Its work so far is on the branch "),
            Code(workspace.branch_name(workflow_id)),
            Text(f", last commit {commit}." if commit else "."),
        ]
    return document(
        paragraph(Text(
            "This item was given back to a person after kestrel started "
            "it, so kestrel will not deliver it."
        )),
        paragraph(*where),
    )
