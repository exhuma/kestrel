"""Decomposition-candidate routing (feature 026, T068; feature 030).

A ``pm``-worked ``decomposition`` card proposes splitting a task into
follow-up work. Its candidate is validated strictly (``candidate.py``)
and handed to `developer` on an ``estimation`` card; only a valid
estimate opens the ``decomposition_gate`` (CAB-2 — see
``estimation.py``). Approval turns the candidate into cards in the same
workflow (feature 031, ``materialise.py``) — nothing is published as a
ticket.

An unparseable proposal is routed as an escalation too (fail closed),
the same convention ``verification.py`` uses: an untrustworthy result
must reach the coordinator, never be silently discarded or treated as
"nothing to decompose."
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.models_board import (
    CardKind,
    CardRelation,
    CardState,
    RelationKind,
    WorkCard,
    WorkspacePermission,
)
from app.persistence.board_store import BoardStore
from app.services.board.artifacts import ArtifactDraft, ArtifactsService
from app.services.board.candidate import (
    Candidate,
    DecompositionResultError,
    DecompositionTask,
    dump_candidate,
    load_candidate,
)
from app.services.board.coordinator import CoordinatorService, CreateCardAction
from app.services.board.gates import GatesService
from app.text_extract import extract_tag

__all__ = [
    "DecompositionResultError",
    "DecompositionTask",
    "RoutingServices",
    "escalate",
    "parse_decomposition_result",
    "route_decomposition_result",
]

#: Logical name of the normalized candidate stored on the decomposition
#: card — the estimation card reads it back through its dependency edge.
CANDIDATE_LOGICAL_NAME = "decomposition_candidate"


@dataclass(frozen=True)
class RoutingServices:
    """What decomposition/estimation routing needs, bundled to keep the
    route functions within the repo's argument-count limit."""

    store: BoardStore
    coordinator: CoordinatorService
    gates: GatesService
    artifacts: ArtifactsService


def parse_decomposition_result(text: str) -> list[DecompositionTask]:
    """Leniently parse a ``<DECOMPOSITION>`` block's tasks — the reading
    used for a gate target, which may predate feature 030.

    :raises DecompositionResultError: If the tag is absent or the block
        is malformed.
    """
    return list(_candidate_from(text, strict=False).tasks)


def _candidate_from(text: str, *, strict: bool) -> Candidate:
    raw = extract_tag(text, "DECOMPOSITION")
    if raw is None:
        raise DecompositionResultError("no DECOMPOSITION block")
    return load_candidate(raw, strict=strict)


def escalate(
    coordinator: CoordinatorService, card: WorkCard, trigger: str, title: str
) -> None:
    """Fail closed: hand an untrustworthy result to the coordinator as a
    ``coordinator_review`` card instead of acting on it."""
    coordinator.apply_actions(
        card.workflow_id, f"{trigger}:{card.id}:{card.attempt_count}",
        [
            CreateCardAction(
                kind=CardKind.COORDINATOR_REVIEW.value, title=title,
                source_card_id=card.id,
            )
        ],
    )


def route_decomposition_result(
    text: str, card: WorkCard, services: RoutingServices
) -> None:
    """Validate *card*'s proposal and hand it to `developer` to estimate.

    The normalized candidate is stored as a reference artifact (no
    card-acceptance side effect — *card* already has its own
    generically-accepted result by the time this runs), and the new
    ``estimation`` card depends on *card*, which is how it finds the
    candidate again (research R2). No gate yet: CAB-2 opens only on a
    valid estimate.
    """
    try:
        candidate = _candidate_from(text, strict=True)
    except DecompositionResultError as exc:
        escalate(
            services.coordinator, card, "decomposition",
            f"Unparseable decomposition proposal on card {card.id}: {exc}",
        )
        return
    services.artifacts.store_reference_artifact(
        ArtifactDraft(
            producer_card_id=card.id,
            logical_name=CANDIDATE_LOGICAL_NAME,
            revision=card.attempt_count,
            content=dump_candidate(candidate),
            trust="agent_output",
        )
    )
    count = len(candidate.tasks)
    estimation = WorkCard(
        id=f"card-{uuid.uuid4().hex[:8]}",
        workflow_id=card.workflow_id,
        kind=CardKind.ESTIMATION.value,
        title=f"Estimate decomposition ({count} task"
        f"{'s' if count != 1 else ''})",
        state=CardState.READY,
        eligible_roles=("developer",),
        workspace_permission=WorkspacePermission.READ_ONLY,
    )
    services.store.create_card(estimation)
    services.store.add_relation(
        CardRelation(
            card_id=estimation.id,
            depends_on_card_id=card.id,
            kind=RelationKind.DEPENDENCY,
        ),
        created_by_action="decomposition",
    )
