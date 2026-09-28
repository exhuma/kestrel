"""Decomposition-candidate routing and publishing (feature 026, T068;
feature 030).

A ``pm``-worked ``decomposition`` card proposes splitting a task into
follow-up work. Its candidate is validated strictly (``candidate.py``)
and handed to `developer` on an ``estimation`` card; only a valid
estimate opens the ``decomposition_gate`` (CAB-2 — see
``estimation.py``). No child task is ever published without that
approval. Publishing an approved candidate (``publish_decomposition``)
is a separate, later step (see
``bootstrap.py::schedule_decomposition_publish``), since it needs
collaborators (a ``TaskSource``, ``ChildTaskLinks``) this module's
routing half does not.

An unparseable proposal is routed as an escalation too (fail closed),
the same convention ``verification.py`` uses: an untrustworthy result
must reach the coordinator, never be silently discarded or treated as
"nothing to decompose."
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.markers import ManualTaskSentinel, Marker, SubtaskSentinel
from app.models_board import (
    CardKind,
    CardRelation,
    CardState,
    RelationKind,
    WorkCard,
    Workflow,
    WorkspacePermission,
)
from app.persistence.board_store import BoardStore
from app.persistence.child_task_store import ChildTaskLinks
from app.ports import TaskSource
from app.services.board.artifacts import ArtifactDraft, ArtifactsService
from app.services.board.candidate import (
    MANUAL,
    Candidate,
    DecompositionResultError,
    DecompositionTask,
    TaskEstimate,
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
    "publish_decomposition",
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
        [CreateCardAction(kind=CardKind.COORDINATOR_REVIEW.value, title=title)],
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


async def publish_decomposition(
    workflow: Workflow,
    candidate_json: str,
    task_source: TaskSource,
    child_tasks: ChildTaskLinks,
) -> list[str]:
    """Publish every task in an approved decomposition candidate.

    Each child is created via ``create_subtask`` with a
    :class:`SubtaskSentinel` marker, so its own later ingestion never
    forces it through decomposition again (``Workflow.skip_decomposition``),
    plus a :class:`ManualTaskSentinel` for a manual task, so ingestion
    never turns it into agent work at all (FR-018). Each is then
    recorded as a linked child (``ChildTaskLinks.record``) so
    re-adoption/reopen tracking — and cleanup — recognizes it.

    :returns: The new child task refs, in candidate order.
    :raises DecompositionResultError: If *candidate_json* is no longer
        parseable (should not happen — it was validated before the gate
        was created).
    """
    candidate = load_candidate(candidate_json, strict=False)
    refs = []
    for task in candidate.tasks:
        ref = await task_source.create_subtask(
            workflow.task_ref, task.title, published_body(task),
            markers=_markers_for(task),
        )
        child_tasks.record(
            workflow.id, ref,
            task_node_id=task.task_node_id,
            prerequisites=task.prerequisites,
            integration_branch=workflow.base_branch,
        )
        refs.append(ref)
    return refs


def _markers_for(task: DecompositionTask) -> tuple[Marker, ...]:
    if task.classification == MANUAL:
        return (SubtaskSentinel(), ManualTaskSentinel())
    return (SubtaskSentinel(),)


def published_body(task: DecompositionTask) -> str:
    """*task*'s body as published: a manual-task header when it is for a
    human, and its approved estimate when it has one (data-model.md).
    A pre-feature-030 task has neither, so publishes unchanged."""
    body = task.body
    if task.classification == MANUAL:
        body = (
            "**Manual task** — for a human. kestrel will not assign this "
            f"to an agent.\n\n{body}"
        )
    if task.estimate is not None:
        body = f"{body.rstrip()}\n\n{_estimate_section(task.estimate)}"
    return body


def _estimate_section(estimate: TaskEstimate) -> str:
    lines = [
        "## Estimate (agent, unverified)",
        f"Size {estimate.size} · confidence {estimate.confidence} · "
        f"~{estimate.man_hours:.1f} man-hours · "
        f"~{estimate.agent_tokens:,} agent tokens · "
        f"~{estimate.review_hours:.1f} review hours",
    ]
    if estimate.risks:
        lines.append(f"Risks: {', '.join(estimate.risks)}")
    lines.append(f"Rationale: {estimate.rationale}")
    return "\n".join(lines)
