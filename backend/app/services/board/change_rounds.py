"""One round of work a person asked for on an existing branch: a fix and
its verification, working from a ``task_spec`` (``materialise.py``).

Requested changes on delivered work and a clarified escalation both start
one.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.documents import Document
from app.models_board import (
    CardKind,
    CardRelation,
    CardState,
    RelationKind,
    WorkCard,
    WorkspacePermission,
)
from app.services.board.materialise import (
    TASK_SPEC_LOGICAL_NAME,
    MaterialiseTarget,
)
from app.services.board.retries import detail_of
from app.services.board.service import BoardService

#: The most of a text's first line a card's title shows.
_TITLE_LIMIT = 80


@dataclass(frozen=True)
class Round:
    """One round of work a person asked for on an existing branch.

    :param title: What the fix card is called.
    :param spec: The text every card of the round works from.
    :param event_type: The event that records why the round started.
    :param detail: What that event says.
    """

    title: str
    spec: Document
    event_type: str
    detail: str


def start_round(
    target: MaterialiseTarget,
    board_service: BoardService,
    workflow_id: str,
    work: Round,
) -> WorkCard:
    """Create a fix and its verification, then start the fix last, so
    nothing can pick it up before its task text exists."""
    store = target.store
    node = f"changes-{uuid.uuid4().hex[:8]}"
    fix = _card(workflow_id, node, work.title, CardKind.IMPLEMENTATION)
    check = _card(
        workflow_id, node, f"Verify: {work.title}", CardKind.VERIFICATION
    )
    store.create_card(fix)
    store.create_card(check)
    store.add_relation(
        CardRelation(
            card_id=check.id,
            depends_on_card_id=fix.id,
            kind=RelationKind.DEPENDENCY,
        ),
        created_by_action="request_changes",
    )
    target.artifacts.store_document(
        fix.id, TASK_SPEC_LOGICAL_NAME, 1, work.spec,
        trust="operator_approved",
    )
    # The next push is new code, so its CI has to be watched again.
    store.record_ci_status(workflow_id, "pending")
    return board_service.transition_card(
        fix.id, CardState.READY.value,
        event_type=work.event_type, payload=detail_of(work.detail),
    )


def _card(
    workflow_id: str, node: str, title: str, kind: CardKind
) -> WorkCard:
    """One waiting card of this round of changes."""
    is_fix = kind == CardKind.IMPLEMENTATION
    return WorkCard(
        id=f"card-{uuid.uuid4().hex[:8]}",
        workflow_id=workflow_id,
        kind=kind.value,
        title=title,
        state=CardState.WAITING_DEPENDENCY.value,
        eligible_roles=("coder",) if is_fix else ("verifier",),
        workspace_permission=(
            WorkspacePermission.WRITE.value if is_fix
            else WorkspacePermission.READ_ONLY.value
        ),
        task_node_id=node,
    )


def summary_of(feedback: str) -> str:
    """The feedback's first line, short enough for a card's title."""
    first = feedback.splitlines()[0].strip()
    if len(first) <= _TITLE_LIMIT:
        return first
    return f"{first[:_TITLE_LIMIT].rstrip()}…"
