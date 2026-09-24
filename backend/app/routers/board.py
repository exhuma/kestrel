"""HTTP routes for the board domain (feature 026, T027/T057/T058).

Additive alongside the old driver's ``/api/workflows`` surface, under its
own ``/api/board`` prefix — it never replaces or modifies that surface,
which stays the only thing operators actually drive until the Phase 10
clean break. Route shapes mirror board-api.md as closely as that
additive placement allows; card detail returns the same summary shape
as the listing for this pass (the richer detail — attempt/event history,
gate/security-review summary — is a follow-up, not yet built).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app import sse
from app.models_board import CardAction, ClaimLease, HandoffArtifact, WorkCard
from app.persistence.board_artifact_store import (
    BoardArtifactStore,
    get_board_artifact_store,
)
from app.persistence.board_claims_store import (
    BoardClaimsStore,
    get_board_claims_store,
)
from app.routers.board_views import (
    BoardLookups,
    board_snapshot,
    card_summary,
    workflow_summary,
)
from app.schemas import (
    BoardInterventionIn,
    BoardSnapshotOut,
    QuarantineInterventionIn,
    SecurityReviewOut,
    WorkCardSummaryOut,
    WorkflowSummaryOut,
)
from app.services.board.bootstrap import (
    get_board_service,
    get_interventions_service,
    get_quarantine_service,
    get_specialist_roster,
)
from app.services.board.interventions import (
    InterventionsService,
    InvalidInterventionError,
    StaleInterventionError,
)
from app.services.board.quarantine import QuarantineService
from app.services.board.service import BoardService
from app.services.board.specialists import SpecialistRoster
from app.storage.workflow_bus import WorkflowBus, get_workflow_bus

router = APIRouter(prefix="/api/board")


@router.post(
    "/security-reviews/{review_id}/resolve",
    response_model=SecurityReviewOut,
)
async def resolve_security_review(
    review_id: str,
    body: QuarantineInterventionIn,
    quarantine: QuarantineService = Depends(get_quarantine_service),
) -> SecurityReviewOut:
    """Release or discard a pending quarantine review.

    Release records a new decision permitting the content to be trusted;
    discard leaves the original input unmodified (FR-022). Both are
    idempotent no-ops on an already-resolved review's terminal state —
    the store still returns the review's current recorded state.

    :raises HTTPException: 404 if ``review_id`` is unknown.
    """
    if body.action == "release_quarantine":
        review = quarantine.release(review_id)
    else:
        review = quarantine.discard(review_id)
    if review is None:
        raise HTTPException(
            status_code=404, detail="unknown security review"
        )
    return SecurityReviewOut(
        id=review.id,
        card_id=review.card_id,
        workflow_id=review.workflow_id,
        classification_category=review.classification_category,
        review_state=review.review_state,
        resolution=review.resolution,
    )


@dataclass(frozen=True)
class _BoardReadDeps:
    """The read-side collaborators every board view route needs."""

    board: BoardService
    roster: SpecialistRoster
    claims_store: BoardClaimsStore
    artifact_store: BoardArtifactStore


def _board_read_deps(
    board: BoardService = Depends(get_board_service),
    roster: SpecialistRoster = Depends(get_specialist_roster),
    claims_store: BoardClaimsStore = Depends(get_board_claims_store),
    artifact_store: BoardArtifactStore = Depends(get_board_artifact_store),
) -> _BoardReadDeps:
    return _BoardReadDeps(board, roster, claims_store, artifact_store)


def _lookups(cards: list[WorkCard], deps: _BoardReadDeps) -> BoardLookups:
    leases: dict[str, ClaimLease] = {}
    latest: dict[str, HandoffArtifact] = {}
    for card in cards:
        lease = deps.claims_store.get_active_lease(card.id)
        if lease is not None:
            leases[card.id] = lease
        artifacts = deps.artifact_store.list_for_card(card.id)
        if artifacts:
            latest[card.id] = max(artifacts, key=lambda a: a.revision)
    return BoardLookups(
        roster=deps.roster, leases=leases, latest_artifacts=latest
    )


def _all_workflow_summaries(board: BoardService) -> list[WorkflowSummaryOut]:
    return [
        workflow_summary(w, board.list_cards(w.id))
        for w in board.list_workflows()
    ]


@router.get("/workflows", response_model=list[WorkflowSummaryOut])
async def list_board_workflows(
    board: BoardService = Depends(get_board_service),
) -> list[WorkflowSummaryOut]:
    """List every workflow's board summary row."""
    return _all_workflow_summaries(board)


@router.get("/workflows/events")
async def stream_board_workflows(
    board: BoardService = Depends(get_board_service),
    bus: WorkflowBus = Depends(get_workflow_bus),
) -> StreamingResponse:
    """Stream the board collection listing as Server-Sent Events.

    Emits the current listing immediately, then a fresh one after every
    committed board mutation to any workflow (``BoardService`` publishes
    a tick on every one, see ``service.py``).
    """

    def _snapshot() -> bytes:
        return sse.encode(
            [s.model_dump(mode="json") for s in _all_workflow_summaries(board)]
        )

    async def _frames() -> AsyncIterator[bytes]:
        q = bus.subscribe_list()
        try:
            yield _snapshot()
            async for tick in sse.with_heartbeat(q):
                yield sse.KEEPALIVE if tick is None else _snapshot()
        finally:
            bus.unsubscribe_list(q)

    return StreamingResponse(
        _frames(), media_type="text/event-stream", headers=sse.HEADERS
    )


def _snapshot_for(workflow_id: str, deps: _BoardReadDeps) -> BoardSnapshotOut:
    workflow = deps.board.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="unknown workflow")
    cards = deps.board.list_cards(workflow_id)
    relations = deps.board.list_relations(workflow_id)
    return board_snapshot(workflow, cards, relations, _lookups(cards, deps))


@router.get(
    "/workflows/{workflow_id}/board", response_model=BoardSnapshotOut
)
async def get_board(
    workflow_id: str, deps: _BoardReadDeps = Depends(_board_read_deps)
) -> BoardSnapshotOut:
    """Return one workflow's full board snapshot.

    :raises HTTPException: 404 if ``workflow_id`` is unknown.
    """
    return _snapshot_for(workflow_id, deps)


@router.get("/workflows/{workflow_id}/board/events")
async def stream_board(
    workflow_id: str,
    deps: _BoardReadDeps = Depends(_board_read_deps),
    bus: WorkflowBus = Depends(get_workflow_bus),
) -> StreamingResponse:
    """Stream one workflow's board snapshot as Server-Sent Events.

    Emits the current snapshot immediately, then a fresh one after every
    committed board mutation. Every snapshot carries a monotonic
    ``revision``; the client treats it as authoritative rather than
    applying incremental patches (board-api.md).

    :raises HTTPException: 404 before streaming starts, if
        ``workflow_id`` is unknown.
    """
    _snapshot_for(workflow_id, deps)  # 404 before we start streaming

    def _frame() -> bytes:
        return sse.encode(
            _snapshot_for(workflow_id, deps).model_dump(mode="json")
        )

    async def _frames() -> AsyncIterator[bytes]:
        q = bus.subscribe(workflow_id)
        try:
            yield _frame()
            async for tick in sse.with_heartbeat(q):
                yield sse.KEEPALIVE if tick is None else _frame()
        finally:
            bus.unsubscribe(workflow_id, q)

    return StreamingResponse(
        _frames(), media_type="text/event-stream", headers=sse.HEADERS
    )


@router.get(
    "/workflows/{workflow_id}/cards/{card_id}",
    response_model=WorkCardSummaryOut,
)
async def get_board_card(
    workflow_id: str,
    card_id: str,
    deps: _BoardReadDeps = Depends(_board_read_deps),
) -> WorkCardSummaryOut:
    """Return one card's board-visible summary.

    :raises HTTPException: 404 if the workflow or card is unknown, or the
        card does not belong to ``workflow_id``.
    """
    card = deps.board.get_card(card_id)
    if card is None or card.workflow_id != workflow_id:
        raise HTTPException(status_code=404, detail="unknown card")
    relations = deps.board.list_relations(workflow_id)
    return card_summary(card, relations, _lookups([card], deps))


@router.post(
    "/workflows/{workflow_id}/cards/{card_id}/interventions",
    response_model=WorkCardSummaryOut,
)
async def apply_board_intervention(
    workflow_id: str,
    card_id: str,
    body: BoardInterventionIn,
    deps: _BoardReadDeps = Depends(_board_read_deps),
    interventions: InterventionsService = Depends(get_interventions_service),
) -> WorkCardSummaryOut:
    """Apply one operator intervention against a card (board-api.md).

    :raises HTTPException: 404 if the workflow or card is unknown; 409 if
        ``expected_revision`` is stale; 422 if policy rejects the action.
    """
    card = deps.board.get_card(card_id)
    if card is None or card.workflow_id != workflow_id:
        raise HTTPException(status_code=404, detail="unknown card")
    try:
        updated = interventions.apply(
            workflow_id,
            card_id,
            CardAction(body.action),
            expected_revision=body.expected_revision,
            decision=body.decision,
        )
    except StaleInterventionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InvalidInterventionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    relations = deps.board.list_relations(workflow_id)
    return card_summary(updated, relations, _lookups([updated], deps))
