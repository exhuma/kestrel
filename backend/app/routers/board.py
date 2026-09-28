"""HTTP routes for the board domain (feature 026, T027/T057/T058), under
the ``/api/board`` prefix. Route shapes mirror board-api.md as closely
as practical; card detail returns the same summary shape as the listing
(gate/security-review detail now included). Event history and artifact
content each get their own dedicated route rather than growing the
snapshot payload.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app import sse
from app.models_board import (
    GATE_CARD_KINDS,
    CardAction,
    CardKind,
    ClaimLease,
    WorkCard,
)
from app.models_board_records import HandoffArtifact, HumanGateRecord
from app.persistence.board_artifact_content_store import ContentNotFoundError
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
    board_events,
    board_snapshot,
    card_summary,
    visible_workflows,
    workflow_summary,
)
from app.schemas import (
    BoardArtifactContentOut,
    BoardEventOut,
    BoardInterventionIn,
    BoardSnapshotOut,
    QuarantineInterventionIn,
    SecurityReviewOut,
    WorkCardSummaryOut,
    WorkflowSummaryOut,
)
from app.services.board.artifacts import ArtifactsService
from app.services.board.bootstrap import (
    get_artifacts_service,
    get_board_service,
    get_gates_service,
    get_interventions_service,
    get_quarantine_service,
    get_specialist_roster,
    schedule_decomposition_publish,
    schedule_escalation_projection,
    schedule_gate_projection,
    schedule_prd_approval_projection,
)
from app.services.board.gates import GatesService
from app.services.board.interventions import (
    GateResolution,
    InterventionsService,
    InvalidInterventionError,
    StaleInterventionError,
)
from app.services.board.phases import DONE_PHASE
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
    bus: WorkflowBus = Depends(get_workflow_bus),
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
    # Unlike ordinary interventions, resolve/discard bypasses BoardService
    # (quarantine may not have a hosting workflow's cards to route through)
    # and so never ticks the bus on its own — without this, the board and
    # card detail SSE streams would never reflect the resolved state.
    bus.publish(review.workflow_id)
    return SecurityReviewOut(
        id=review.id,
        card_id=review.card_id,
        workflow_id=review.workflow_id,
        classification_category=review.classification_category,
        reason=review.reason,
        review_state=review.review_state,
        resolution=review.resolution,
    )


@router.get(
    "/artifacts/{artifact_id}/content",
    response_model=BoardArtifactContentOut,
)
async def get_artifact_content(
    artifact_id: str,
    artifact_store: BoardArtifactStore = Depends(get_board_artifact_store),
    artifacts: ArtifactsService = Depends(get_artifacts_service),
) -> BoardArtifactContentOut:
    """Return one artifact's full content and trust level.

    The frontend must render this as text, never HTML — it is agent
    output crossing into the browser.

    :raises HTTPException: 404 if the artifact, or its stored content, is
        unknown.
    """
    artifact = artifact_store.get(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="unknown artifact")
    try:
        content = artifacts.read_content(artifact_id)
    except ContentNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="artifact content missing"
        ) from exc
    return BoardArtifactContentOut(content=content or "", trust=artifact.trust)


@dataclass(frozen=True)
class _BoardReadDeps:
    """The read-side collaborators every board view route needs."""

    board: BoardService
    roster: SpecialistRoster
    claims_store: BoardClaimsStore
    artifact_store: BoardArtifactStore
    quarantine: QuarantineService
    gates: GatesService


@dataclass(frozen=True)
class _BoardCoreDeps:
    """The first half of ``_BoardReadDeps`` — split out so neither
    composer function crosses the argument-count limit."""

    board: BoardService
    roster: SpecialistRoster
    claims_store: BoardClaimsStore


def _board_core_deps(
    board: BoardService = Depends(get_board_service),
    roster: SpecialistRoster = Depends(get_specialist_roster),
    claims_store: BoardClaimsStore = Depends(get_board_claims_store),
) -> _BoardCoreDeps:
    return _BoardCoreDeps(board, roster, claims_store)


def _board_read_deps(
    core: _BoardCoreDeps = Depends(_board_core_deps),
    artifact_store: BoardArtifactStore = Depends(get_board_artifact_store),
    quarantine: QuarantineService = Depends(get_quarantine_service),
    gates: GatesService = Depends(get_gates_service),
) -> _BoardReadDeps:
    return _BoardReadDeps(
        core.board,
        core.roster,
        core.claims_store,
        artifact_store,
        quarantine,
        gates,
    )


def _lookups(cards: list[WorkCard], deps: _BoardReadDeps) -> BoardLookups:
    leases: dict[str, ClaimLease] = {}
    latest: dict[str, HandoffArtifact] = {}
    security_review_ids: dict[str, str] = {}
    gates: dict[str, HumanGateRecord] = {}
    for card in cards:
        lease = deps.claims_store.get_active_lease(card.id)
        if lease is not None:
            leases[card.id] = lease
        artifacts = deps.artifact_store.list_for_card(card.id)
        if artifacts:
            latest[card.id] = max(artifacts, key=lambda a: a.revision)
        if card.kind == CardKind.SECURITY_REVIEW.value:
            review = deps.quarantine.review_for_card(card.id)
            if review is not None:
                security_review_ids[card.id] = review.id
        if CardKind(card.kind) in GATE_CARD_KINDS:
            gate = deps.gates.get_gate(card.id)
            if gate is not None:
                gates[card.id] = gate
    return BoardLookups(
        roster=deps.roster,
        leases=leases,
        latest_artifacts=latest,
        security_review_ids=security_review_ids,
        gates=gates,
    )


def _all_workflow_summaries(
    board: BoardService, *, include_completed: bool = False
) -> list[WorkflowSummaryOut]:
    workflows = visible_workflows(board.list_workflows(newest_first=True))
    summaries = [
        workflow_summary(w, board.list_cards(w.id)) for w in workflows
    ]
    if include_completed:
        return summaries
    return [s for s in summaries if s.phase != DONE_PHASE]


@router.get("/workflows", response_model=list[WorkflowSummaryOut])
async def list_board_workflows(
    include_completed: bool = False,
    board: BoardService = Depends(get_board_service),
) -> list[WorkflowSummaryOut]:
    """List every workflow's board summary row, newest first.

    A quarantine placeholder collapses into its real workflow once one
    exists (GitHub #45), and a workflow whose cards are all terminal is
    hidden unless ``include_completed`` is set.
    """
    return _all_workflow_summaries(board, include_completed=include_completed)


@router.get("/workflows/events")
async def stream_board_workflows(
    include_completed: bool = False,
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
            [
                s.model_dump(mode="json")
                for s in _all_workflow_summaries(
                    board, include_completed=include_completed
                )
            ]
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
    "/workflows/{workflow_id}/events", response_model=list[BoardEventOut]
)
async def list_board_events(
    workflow_id: str, deps: _BoardReadDeps = Depends(_board_read_deps)
) -> list[BoardEventOut]:
    """Return one workflow's board event history, oldest first — the
    narrative feed's data source.

    Not streamed: board SSE is full-snapshot replacement (never
    incremental patches), and a growing append-only log does not fit
    that shape. The client re-fetches this after the snapshot stream
    ticks instead.

    :raises HTTPException: 404 if ``workflow_id`` is unknown.
    """
    workflow = deps.board.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="unknown workflow")
    events = deps.board.list_events(workflow_id)
    cards = deps.board.list_cards(workflow_id)
    return board_events(events, cards, deps.roster)


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
            resolution=GateResolution(
                decision=body.decision, answer=body.answer
            ),
        )
    except StaleInterventionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InvalidInterventionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.action == CardAction.RESOLVE_GATE.value and body.decision:
        schedule_gate_projection(workflow_id, updated, body.decision)
        _schedule_gate_followup(workflow_id, updated, body.decision)
    elif body.action == CardAction.REQUEST_COORDINATOR_REVIEW.value:
        schedule_escalation_projection(workflow_id, updated)
    relations = deps.board.list_relations(workflow_id)
    return card_summary(updated, relations, _lookups([updated], deps))


def _schedule_gate_followup(
    workflow_id: str, updated: WorkCard, decision: str
) -> None:
    """Schedule a resolved gate's kind-specific follow-up, if it has one
    (T068's decomposition publish, T078's PRD-approval projection)."""
    if decision != "approved":
        return
    if updated.kind == CardKind.DECOMPOSITION_GATE.value:
        schedule_decomposition_publish(workflow_id, updated)
    elif updated.kind == CardKind.PRD_GATE.value:
        schedule_prd_approval_projection(workflow_id, updated)
