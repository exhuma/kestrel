"""Dev-only workflow reset routes (feature 026, T069).

**Temporary.** Only registered when ``board_dev_actions_enabled`` is set
(off by default, ``app/main.py::create_app``) — see
``app/services/board/dev_reset.py``'s module docstring for the full
rationale and what to delete alongside this file once the board is
production-ready.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.persistence.board_store import BoardStore, get_board_store
from app.services.board.bootstrap import (
    get_board_service,
    get_claims_service,
    get_workspace_service,
)
from app.services.board.claims import ClaimsService
from app.services.board.dev_reset import (
    DevActionNotAllowedError,
    cleanup_workflow,
    rerun_workflow,
)
from app.services.board.service import BoardService
from app.services.board.workspace import WorkspaceService

router = APIRouter(prefix="/api/board")


@router.post("/workflows/{workflow_id}/dev/cleanup", status_code=204)
async def dev_cleanup_workflow(
    workflow_id: str,
    store: BoardStore = Depends(get_board_store),
    board: BoardService = Depends(get_board_service),
    claims: ClaimsService = Depends(get_claims_service),
    workspace: WorkspaceService = Depends(get_workspace_service),
) -> None:
    """Cancel every open card and drop the workspace for a workflow.

    :raises HTTPException: 422 if the workflow is unknown or not private.
    """
    try:
        await cleanup_workflow(
            workflow_id, store=store, board_service=board, claims=claims,
            workspace=workspace,
        )
    except DevActionNotAllowedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/workflows/{workflow_id}/dev/rerun", status_code=204)
async def dev_rerun_workflow(
    workflow_id: str,
    store: BoardStore = Depends(get_board_store),
    board: BoardService = Depends(get_board_service),
    claims: ClaimsService = Depends(get_claims_service),
    workspace: WorkspaceService = Depends(get_workspace_service),
) -> None:
    """Reset a workflow and reopen it at a fresh understanding gate.

    :raises HTTPException: 422 if the workflow is unknown or not private.
    """
    try:
        await rerun_workflow(
            workflow_id, store=store, board_service=board, claims=claims,
            workspace=workspace,
        )
    except DevActionNotAllowedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
