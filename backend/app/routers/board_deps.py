"""Board-view dependency bundles and view assembly, shared by the board
router's read routes (split out of ``board.py`` to stay within the
repo's module-length limit).
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from fastapi import Depends, HTTPException

from app.models_board import (
    GATE_CARD_KINDS,
    CardKind,
    ClaimLease,
    WorkCard,
    Workflow,
)
from app.models_board_records import HandoffArtifact, HumanGateRecord
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
    request_activity,
    visible_workflows,
    workflow_summary,
)
from app.schemas import (
    BoardSnapshotOut,
    WorkflowSummaryOut,
)
from app.services.board.bootstrap import (
    get_board_service,
    get_gates_service,
    get_quarantine_service,
    get_specialist_roster,
)
from app.services.board.gates import GatesService
from app.services.board.live_activity import LiveActivity, get_live_activity
from app.services.board.phases import DONE_PHASE
from app.services.board.quarantine import QuarantineService
from app.services.board.service import BoardService
from app.services.board.specialists import SpecialistRoster


@dataclass(frozen=True)
class BoardReadDeps:
    """The read-side collaborators every board view route needs."""

    board: BoardService
    roster: SpecialistRoster
    claims_store: BoardClaimsStore
    artifact_store: BoardArtifactStore
    quarantine: QuarantineService
    gates: GatesService
    live: LiveActivity


@dataclass(frozen=True)
class BoardCoreDeps:
    """The first half of ``BoardReadDeps`` — split out so neither
    composer function crosses the argument-count limit."""

    board: BoardService
    roster: SpecialistRoster
    claims_store: BoardClaimsStore
    live: LiveActivity


def board_core_deps(
    board: BoardService = Depends(get_board_service),
    roster: SpecialistRoster = Depends(get_specialist_roster),
    claims_store: BoardClaimsStore = Depends(get_board_claims_store),
    live: LiveActivity = Depends(get_live_activity),
) -> BoardCoreDeps:
    return BoardCoreDeps(board, roster, claims_store, live)


def board_read_deps(
    core: BoardCoreDeps = Depends(board_core_deps),
    artifact_store: BoardArtifactStore = Depends(get_board_artifact_store),
    quarantine: QuarantineService = Depends(get_quarantine_service),
    gates: GatesService = Depends(get_gates_service),
) -> BoardReadDeps:
    return BoardReadDeps(
        core.board,
        core.roster,
        core.claims_store,
        artifact_store,
        quarantine,
        gates,
        core.live,
    )


def board_lookups(cards: list[WorkCard], deps: BoardReadDeps) -> BoardLookups:
    leases: dict[str, ClaimLease] = {}
    latest: dict[str, HandoffArtifact] = {}
    security_review_ids: dict[str, str] = {}
    gates: dict[str, HumanGateRecord] = {}
    gate_rounds: dict[str, tuple[int, int]] = {}
    gate_targets: dict[str, HandoffArtifact] = {}
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
                target = _gate_target(gate, deps)
                if target is not None:
                    gate_targets[card.id] = target
                round_number = deps.gates.gate_round(card, cards)
                if round_number is not None:
                    gate_rounds[card.id] = (
                        round_number,
                        deps.gates.refinement_round_cap,
                    )
    return BoardLookups(
        roster=deps.roster,
        leases=leases,
        latest_artifacts=latest,
        security_review_ids=security_review_ids,
        gates=gates,
        gate_rounds=gate_rounds,
        gate_targets=gate_targets,
    )


def _gate_target(
    gate: HumanGateRecord, deps: BoardReadDeps
) -> HandoffArtifact | None:
    """The artifact *gate* asks about, if it has one."""
    if gate.target_artifact_id is None:
        return None
    return deps.artifact_store.get(gate.target_artifact_id)


def all_workflow_summaries(
    deps: BoardListDeps, *, include_completed: bool = False
) -> list[WorkflowSummaryOut]:
    workflows = visible_workflows(deps.board.list_workflows(newest_first=True))
    summaries = [
        _summary(w, deps.board.list_cards(w.id), deps)
        for w in workflows
    ]
    if include_completed:
        return summaries
    return [s for s in summaries if s.phase != DONE_PHASE]


@dataclass(frozen=True)
class BoardListDeps:
    """Collaborators the board collection listing needs (feature 029 A4)
    — bundled to keep the route handlers within the argument-count
    limit."""

    board: BoardService
    gates: GatesService
    core: BoardCoreDeps


def board_list_deps(
    board: BoardService = Depends(get_board_service),
    gates: GatesService = Depends(get_gates_service),
    core: BoardCoreDeps = Depends(board_core_deps),
) -> BoardListDeps:
    return BoardListDeps(board, gates, core)


def _summary(
    workflow: Workflow, cards: list[WorkCard], deps: BoardListDeps
) -> WorkflowSummaryOut:
    return workflow_summary(workflow, cards, deps.gates, request_activity(
        cards, deps.board.list_events(workflow.id),
        deps.core.live.current(workflow.id), deps.core.roster,
    ))


def snapshot_for(workflow_id: str, deps: BoardReadDeps) -> BoardSnapshotOut:
    workflow = deps.board.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="unknown workflow")
    cards = deps.board.list_cards(workflow_id)
    relations = deps.board.list_relations(workflow_id)
    lookups = replace(board_lookups(cards, deps), activity=request_activity(
        cards, deps.board.list_events(workflow_id),
        deps.live.current(workflow_id), deps.roster,
    ))
    return board_snapshot(workflow, cards, relations, lookups)


