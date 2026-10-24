"""Estimation routing: from `developer`'s estimates to CAB-2 (feature 030).

An ``estimation`` card is created by decomposition routing with a
dependency edge on the decomposition card whose candidate it estimates
(research R2). Its ``<ESTIMATES>`` result is validated against that
candidate (``contracts/estimation-output.md``); only a complete, valid
estimate opens the ``decomposition_gate`` — anything else fails closed
into a ``coordinator_review`` card, the same convention an unparseable
decomposition follows (FR-009).

On success three things are stored, in order: the ``cab2_proposal``
(candidate plus estimates — the gate's target, and the structured
record a later estimate-vs-actual feature reads, FR-016), the gate
itself, and the code-rendered executive summary, produced by the gate
card so it is that card's own ``latest_artifact`` (research R3).
"""
import json

from app.models_board import CardKind, CardState, RelationKind, WorkCard
from app.services.board.artifacts import ArtifactDraft
from app.services.board.candidate import (
    MANUAL,
    Candidate,
    DecompositionResultError,
    DecompositionTask,
    TaskEstimate,
    dump_candidate,
    load_candidate,
    parse_estimate,
)
from app.services.board.decomposition import (
    CANDIDATE_LOGICAL_NAME,
    RoutingServices,
    escalate,
)
from app.services.board.exec_summary import render_executive_summary
from app.services.board.retries import UnreadableResultError
from app.text_extract import extract_tag

PROPOSAL_LOGICAL_NAME = "cab2_proposal"
SUMMARY_LOGICAL_NAME = "executive_summary"


def estimation_candidate(
    card: WorkCard, services: RoutingServices
) -> Candidate | None:
    """The candidate *card* estimates, found through its dependency edge,
    or ``None`` if it has none (e.g. a hand-made card)."""
    for relation in services.store.list_relations(card.workflow_id):
        if (
            relation.card_id == card.id
            and relation.kind == RelationKind.DEPENDENCY
        ):
            raw = services.artifacts.latest_content_for_card(
                relation.depends_on_card_id, CANDIDATE_LOGICAL_NAME
            )
            if raw is not None:
                return load_candidate(raw, strict=False)
    return None


def estimation_context(card: WorkCard, services: RoutingServices) -> str:
    """The envelope extra for an ``estimation`` card: the normalized
    candidate it must estimate, one estimate per ``task_node_id``."""
    candidate = estimation_candidate(card, services)
    if candidate is None:
        return ""
    return (
        "Proposed tasks to estimate (one estimate per task_node_id; "
        "classification is fixed — do not change it):\n"
        f"{dump_candidate(candidate)}"
    )


def parse_estimates(text: str, candidate: Candidate) -> Candidate:
    """Attach ``<ESTIMATES>`` to *candidate*'s tasks, validating both each
    estimate and its fit to its task.

    :raises DecompositionResultError: On any violation — absent block,
        malformed JSON, a missing/unknown/duplicate task id, or a figure
        breaking the coding/manual rules (FR-007/FR-008).
    """
    by_id = _estimates_by_id(text)
    expected = {task.task_node_id for task in candidate.tasks}
    if set(by_id) != expected:
        raise DecompositionResultError(
            f"estimates must cover exactly {sorted(expected)}, "
            f"got {sorted(by_id)}"
        )
    return Candidate(
        tasks=tuple(
            _estimated(task, by_id[task.task_node_id])
            for task in candidate.tasks
        ),
        summary=candidate.summary,
    )


def _estimates_by_id(text: str) -> dict[str, TaskEstimate]:
    raw = extract_tag(text, "ESTIMATES")
    if raw is None:
        raise DecompositionResultError("no ESTIMATES block")
    try:
        entries = json.loads(raw)["estimates"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise DecompositionResultError(f"malformed estimates: {exc}") from exc
    if not isinstance(entries, list):
        raise DecompositionResultError("estimates must be a list")
    by_id: dict[str, TaskEstimate] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise DecompositionResultError(f"malformed estimate: {entry!r}")
        task_id = entry.get("task_node_id")
        if not isinstance(task_id, str) or task_id in by_id:
            raise DecompositionResultError(
                f"missing or duplicate task_node_id: {task_id!r}"
            )
        by_id[task_id] = parse_estimate(entry)
    return by_id


def _estimated(
    task: DecompositionTask, estimate: TaskEstimate
) -> DecompositionTask:
    _check_fit(task, estimate)
    return DecompositionTask(
        title=task.title,
        body=task.body,
        task_node_id=task.task_node_id,
        prerequisites=task.prerequisites,
        classification=task.classification,
        estimate=estimate,
    )


def _check_fit(task: DecompositionTask, estimate: TaskEstimate) -> None:
    """FR-008: every task costs human time; only coding tasks cost agent
    tokens and review time."""
    where = f"task {task.task_node_id!r}"
    if estimate.man_hours <= 0:
        raise DecompositionResultError(f"{where}: man_hours must be > 0")
    agent_cost = (estimate.agent_tokens, estimate.review_hours)
    if task.classification == MANUAL:
        if any(agent_cost):
            raise DecompositionResultError(
                f"{where} is manual: agent_tokens and review_hours must be 0"
            )
    elif not all(agent_cost):
        raise DecompositionResultError(
            f"{where} is coding: agent_tokens and review_hours must be > 0"
        )


def route_estimation_result(
    text: str, card: WorkCard, services: RoutingServices
) -> None:
    """Turn a valid estimate into CAB-2; escalate anything else."""
    candidate = estimation_candidate(card, services)
    if candidate is None:
        escalate(
            services.coordinator, card, "estimation",
            f"Estimation card {card.id} has no decomposition candidate",
        )
        return
    try:
        proposal = parse_estimates(text, candidate)
    except DecompositionResultError as exc:
        raise UnreadableResultError(
            f"Invalid estimates on card {card.id}: {exc}", str(exc)
        ) from exc
    if _gate_awaiting(card.workflow_id, services):
        escalate(
            services.coordinator, card, "estimation",
            f"Estimates on card {card.id} arrived while a CAB-2 gate is "
            "already awaiting a decision; no second gate opened",
        )
        return
    _open_cab2(card, proposal, services)


def _gate_awaiting(workflow_id: str, services: RoutingServices) -> bool:
    return any(
        c.kind == CardKind.DECOMPOSITION_GATE.value
        and c.state == CardState.AWAITING_HUMAN.value
        for c in services.store.list_cards(workflow_id)
    )


def _open_cab2(
    card: WorkCard, proposal: Candidate, services: RoutingServices
) -> None:
    target = services.artifacts.store_reference_artifact(
        ArtifactDraft(
            producer_card_id=card.id,
            logical_name=PROPOSAL_LOGICAL_NAME,
            revision=card.attempt_count,
            content=dump_candidate(proposal),
            trust="agent_output",
            mime_type="application/json",
        )
    )
    coding, manual = proposal.counts()
    gate = services.gates.create_gate(
        card.workflow_id,
        kind=CardKind.DECOMPOSITION_GATE.value,
        title=f"Approve decomposition ({coding} coding, {manual} manual)",
        requested_decision="approve_decomposition",
        target_artifact_id=target.id,
    )
    services.artifacts.store_document(
        gate.id, SUMMARY_LOGICAL_NAME, 1, render_executive_summary(proposal)
    )
