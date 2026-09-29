"""Dev-only workflow reset helpers (feature 026, T069).

**Temporary.** Exists so a local-task-source dry run can be repeated
without restarting kestrel or hand-editing the database — not a
production feature, and not held to the same design bar as the rest of
the board domain. Delete this module, ``app/routers/board_dev.py``, and
the ``board_dev_actions_enabled`` setting together once the board is
production-ready; nothing else in the codebase depends on any of them.

Restricted to a workflow whose ``source_visibility`` is ``"private"``
(the same safety property the old fixed driver's own ``rerun`` enforced,
``git show 33628b4^:backend/app/services/workflows/reset.py``) so this
can never be pointed at a real GitHub/Jira-tracked workflow, even with
the setting on.

Cleanup only blocks *new* dispatch (cancels every open card, revokes any
active claim) — it does not, and cannot, kill an already-running
specialist turn (see ``dispatch_ready.py``'s module docstring on the
fire-and-forget dispatch loop having no retained task handle to cancel).
An in-flight turn simply finishes and its result is discarded: the card
it was working is already ``cancelled`` by the time it tries to
complete, so ``ClaimsService.complete``'s stale-lease check rejects it.

A decomposed workflow's approved tasks are cards in this same workflow
(feature 031), so resetting it covers them too; a child workflow
published before feature 031 is a separate workflow and untouched.
"""
from __future__ import annotations

from app.models_board import TERMINAL_STATES, CardState
from app.models_board_records import BoardEventRecord
from app.persistence.board_store import BoardStore
from app.services.board.claims import ClaimsService
from app.services.board.service import BoardService
from app.services.board.understanding_redraft import understanding_card
from app.services.board.workspace import WorkspaceService


class DevActionNotAllowedError(Exception):
    """Raised when a dev reset action is attempted on a non-private workflow."""


async def cleanup_workflow(
    workflow_id: str,
    *,
    store: BoardStore,
    board_service: BoardService,
    claims: ClaimsService,
    workspace: WorkspaceService,
) -> None:
    """Cancel every open card, revoke active claims, and drop the
    workspace for *workflow_id*.

    :raises DevActionNotAllowedError: If the workflow is unknown or its
        source is not ``private``.
    """
    workflow = store.get_workflow(workflow_id)
    if workflow is None or workflow.source_visibility != "private":
        raise DevActionNotAllowedError(
            f"workflow {workflow_id!r} is unknown or not private; dev "
            "reset is restricted to private (local) task sources"
        )
    for card in store.list_cards(workflow_id):
        if card.state in TERMINAL_STATES:
            continue
        if card.state == CardState.CLAIMED.value:
            claims.claims_store.release_claim(card.id)
        board_service.transition_card(
            card.id, CardState.CANCELLED.value, event_type="dev_reset.cleanup"
        )
    await workspace.teardown(workflow_id, workflow.repo)


async def rerun_workflow(
    workflow_id: str,
    *,
    store: BoardStore,
    board_service: BoardService,
    claims: ClaimsService,
    workspace: WorkspaceService,
) -> None:
    """Reset *workflow_id* and restart it at the understanding step: a
    fresh restatement for the operator to confirm (feature 032).

    Reuses the same workflow row and id rather than creating a new one —
    the least-change option: no re-ingestion, no dismissal bookkeeping,
    no new store methods for deleting a workflow's rows.

    :raises DevActionNotAllowedError: See :func:`cleanup_workflow`.
    """
    await cleanup_workflow(
        workflow_id, store=store, board_service=board_service,
        claims=claims, workspace=workspace,
    )
    store.create_card(understanding_card(workflow_id))
    store.append_event(
        BoardEventRecord(workflow_id=workflow_id, event_type="dev_reset.rerun")
    )
