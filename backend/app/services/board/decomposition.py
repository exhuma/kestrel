"""Decomposition-candidate parsing and routing (feature 026, T068).

A ``pm``-worked ``decomposition`` card proposes splitting a task into
follow-up work; this module turns its parsed candidate into a
``decomposition_gate`` card holding it for operator approval — no child
task is ever published without that approval. Publishing an approved
candidate (``publish_decomposition``) is a separate, later step (see
``bootstrap.py::schedule_decomposition_publish``), since it needs
collaborators (a ``TaskSource``, ``ChildTaskLinks``) this module's
routing half does not.

An unparseable proposal is routed as an escalation too (fail closed),
the same convention ``verification.py`` uses: an untrustworthy result
must reach the coordinator, never be silently discarded or treated as
"nothing to decompose."
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from app.markers import SubtaskSentinel
from app.models_board import CardKind, WorkCard, Workflow
from app.persistence.child_task_store import ChildTaskLinks
from app.ports import TaskSource
from app.services.board.artifacts import ArtifactDraft, ArtifactsService
from app.services.board.coordinator import CoordinatorService, CreateCardAction
from app.services.board.gates import GatesService
from app.text_extract import extract_tag


class DecompositionResultError(Exception):
    """Raised when a decomposition proposal cannot be trusted."""


@dataclass(frozen=True)
class DecompositionTask:
    """One task-source-ready follow-up task, and its design-contract
    identity for dependency ordering (data-model.md-adjacent)."""

    title: str
    body: str
    task_node_id: str = ""
    prerequisites: tuple[str, ...] = ()


def parse_decomposition_result(text: str) -> list[DecompositionTask]:
    """Parse the ``<DECOMPOSITION>`` block.

    :raises DecompositionResultError: If the tag is absent, the block
        isn't valid JSON of the right shape, or any entry is malformed —
        always fail closed rather than guess.
    """
    raw = extract_tag(text, "DECOMPOSITION")
    if raw is None:
        raise DecompositionResultError("no DECOMPOSITION block")
    try:
        data = json.loads(raw)
        entries = data["tasks"]
        if not isinstance(entries, list) or not entries:
            raise DecompositionResultError("tasks must be a nonempty list")
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise DecompositionResultError(f"malformed result: {exc}") from exc
    return [_parse_one(entry) for entry in entries]


def _parse_one(entry: object) -> DecompositionTask:
    if not isinstance(entry, dict):
        raise DecompositionResultError(f"malformed task entry: {entry!r}")
    try:
        return DecompositionTask(
            title=entry["title"],
            body=entry["body"],
            task_node_id=entry.get("task_node_id", ""),
            prerequisites=tuple(entry.get("prerequisites", ())),
        )
    except (KeyError, TypeError) as exc:
        raise DecompositionResultError(
            f"malformed task entry: {entry!r}"
        ) from exc


def route_decomposition_result(
    text: str,
    card: WorkCard,
    coordinator: CoordinatorService,
    gates: GatesService,
    artifacts: ArtifactsService,
) -> None:
    """Parse *card*'s decomposition proposal and hold it behind a gate.

    The raw ``<DECOMPOSITION>`` JSON is stored as a reference artifact
    (no card-acceptance side effect — *card* already has its own
    generically-accepted result by the time this runs) and referenced by
    the new gate's ``target_artifact_id``, so an operator (and, at
    publish time, ``publish_decomposition``) can read back exactly what
    was proposed.
    """
    try:
        raw = extract_tag(text, "DECOMPOSITION") or ""
        tasks = parse_decomposition_result(text)
    except DecompositionResultError:
        trigger = f"decomposition:{card.id}:{card.attempt_count}"
        coordinator.apply_actions(
            card.workflow_id, trigger,
            [
                CreateCardAction(
                    kind=CardKind.COORDINATOR_REVIEW.value,
                    title=f"Unparseable decomposition proposal on card "
                    f"{card.id}",
                )
            ],
        )
        return
    artifact = artifacts.store_reference_artifact(
        ArtifactDraft(
            producer_card_id=card.id,
            logical_name="decomposition_candidate",
            revision=card.attempt_count,
            content=raw,
            trust="agent_output",
        )
    )
    gates.create_gate(
        card.workflow_id,
        kind=CardKind.DECOMPOSITION_GATE.value,
        title=f"Approve decomposition ({len(tasks)} task"
        f"{'s' if len(tasks) != 1 else ''})",
        requested_decision="approve_decomposition",
        target_artifact_id=artifact.id,
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
    then recorded as a linked child (``ChildTaskLinks.record``) so
    re-adoption/reopen tracking recognizes it.

    :returns: The new child task refs, in candidate order.
    :raises DecompositionResultError: If *candidate_json* is no longer
        parseable (should not happen — it was validated before the gate
        was created).
    """
    tasks = parse_decomposition_result(
        f"<DECOMPOSITION>{candidate_json}</DECOMPOSITION>"
    )
    refs = []
    for task in tasks:
        ref = await task_source.create_subtask(
            workflow.task_ref, task.title, task.body,
            markers=(SubtaskSentinel(),),
        )
        child_tasks.record(
            workflow.id, ref,
            task_node_id=task.task_node_id,
            prerequisites=task.prerequisites,
            integration_branch=workflow.base_branch,
        )
        refs.append(ref)
    return refs
