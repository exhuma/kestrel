"""Turn an approved CAB-2 decomposition into cards (feature 031).

Approving a ``decomposition_gate`` no longer publishes child tickets to
the task source. The approved tasks stay inside the request's own
workflow, as cards (research R1): per coding task an ``implementation``
card for `coder` and the ``verification`` card that checks it (R5), per
manual task a ``manual_task`` card only the operator completes (R4). A
task's prerequisites become dependency edges between the tasks' head
cards. Every card carries its task's ``task_node_id`` (R2), and each
head card holds the approved task text as a ``task_spec`` reference
artifact — what every later card on the task works from (R3).

Deterministic by design: what runs is exactly what the operator
approved, never a coordinator's reading of it (FR-004).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, replace

from app.documents import (
    Block,
    Document,
    Heading,
    ListItem,
    OrderedList,
    Paragraph,
    Strong,
    Text,
    document,
    paragraph,
)
from app.models_board import (
    CardKind,
    CardRelation,
    CardState,
    RelationKind,
    WorkCard,
    WorkspacePermission,
)
from app.persistence.board_store import BoardStore
from app.services.board.agent_text import from_agent, to_prompt
from app.services.board.artifacts import ArtifactsService
from app.services.board.candidate import (
    MANUAL,
    Candidate,
    DecompositionResultError,
    DecompositionTask,
    TaskEstimate,
    load_candidate,
    with_task_id,
)
from app.services.board.dependents import unblocked_state
from app.services.board.policy import PolicyViolation

_log = logging.getLogger("kestrel.board.materialise")

#: Logical name of the approved task text on a task's head card.
TASK_SPEC_LOGICAL_NAME = "task_spec"

#: The card kinds that head a task: the one card its dependents wait on
#: and the one holding its ``task_spec``.
HEAD_KINDS = frozenset(
    {CardKind.IMPLEMENTATION.value, CardKind.MANUAL_TASK.value}
)


@dataclass(frozen=True)
class MaterialiseTarget:
    """Where materialisation writes, bundled to keep the entry point
    within the repo's argument-count limit."""

    store: BoardStore
    artifacts: ArtifactsService


def approved_candidate(candidate_json: str) -> Candidate | None:
    """Read an approved gate target, which may predate feature 030 or
    031 (lenient parsing), giving id-less tasks ``t<n>`` ids.

    :returns: ``None`` if it no longer parses — it was validated before
        the gate opened, so this should not happen.
    """
    try:
        candidate = load_candidate(candidate_json, strict=False)
    except DecompositionResultError:
        _log.exception("approved decomposition candidate no longer parses")
        return None
    tasks = tuple(
        task if task.task_node_id else with_task_id(task, f"t{index}")
        for index, task in enumerate(candidate.tasks, start=1)
    )
    return Candidate(tasks=tasks, summary=candidate.summary)


def materialise_decomposition(
    workflow_id: str, candidate_json: str, target: MaterialiseTarget
) -> None:
    """Create the cards, edges and ``task_spec`` artifacts for every
    approved task in *candidate_json*.

    A no-op when the workflow already holds a card created from an
    approved task, so applying the same approval twice creates nothing
    new (FR-004).
    """
    if any(c.task_node_id for c in target.store.list_cards(workflow_id)):
        return
    candidate = approved_candidate(candidate_json)
    if candidate is None:
        return
    known = {task.task_node_id for task in candidate.tasks}
    heads = {
        task.task_node_id: _create_task_cards(workflow_id, task, known, target)
        for task in candidate.tasks
    }
    titles = {task.task_node_id: task.title for task in candidate.tasks}
    for task in candidate.tasks:
        _write_task_spec(heads[task.task_node_id], task, titles, target)
        for prerequisite in _known_prerequisites(task, known):
            _depend(
                target.store, heads[task.task_node_id], heads[prerequisite]
            )


@dataclass(frozen=True)
class _Shape:
    """One card's kind-specific fields."""

    kind: CardKind
    title: str
    roles: tuple[str, ...] = ()
    permission: WorkspacePermission = WorkspacePermission.NONE


def _create_task_cards(
    workflow_id: str,
    task: DecompositionTask,
    known: set[str],
    target: MaterialiseTarget,
) -> str:
    """Create *task*'s cards and return its head card's id."""
    blocked = bool(_known_prerequisites(task, known))
    if task.classification == MANUAL:
        shape = _Shape(CardKind.MANUAL_TASK, task.title)
        head = _card(workflow_id, task, shape)
        return _create(target.store, head, blocked)
    head = _card(workflow_id, task, _Shape(
        CardKind.IMPLEMENTATION, task.title, ("coder",),
        WorkspacePermission.WRITE,
    ))
    head_id = _create(target.store, head, blocked)
    verification = _card(workflow_id, task, _Shape(
        CardKind.VERIFICATION, f"Verify: {task.title}", ("verifier",),
        WorkspacePermission.READ_ONLY,
    ))
    _depend(target.store, _create(target.store, verification, True), head_id)
    return head_id


def _card(workflow_id: str, task: DecompositionTask, shape: _Shape) -> WorkCard:
    return WorkCard(
        id=f"card-{uuid.uuid4().hex[:8]}",
        workflow_id=workflow_id,
        kind=shape.kind.value,
        title=shape.title,
        state=CardState.WAITING_DEPENDENCY.value,
        eligible_roles=shape.roles,
        workspace_permission=shape.permission.value,
        task_node_id=task.task_node_id,
    )


def _create(store: BoardStore, card: WorkCard, blocked: bool) -> str:
    """Store *card* waiting when *blocked*, else in its unblocked state."""
    state = CardState.WAITING_DEPENDENCY if blocked else unblocked_state(card)
    store.create_card(replace(card, state=state.value))
    return card.id


def _depend(store: BoardStore, card_id: str, depends_on: str) -> None:
    try:
        store.add_relation(
            CardRelation(
                card_id=card_id,
                depends_on_card_id=depends_on,
                kind=RelationKind.DEPENDENCY,
            ),
            created_by_action="materialise_decomposition",
        )
    except PolicyViolation:
        _log.exception(
            "card %s: dependency on %s rejected", card_id, depends_on
        )


def _known_prerequisites(
    task: DecompositionTask, known: set[str]
) -> tuple[str, ...]:
    """*task*'s prerequisites that name a task in the same candidate.

    Strict parsing already rejects unknown ones (research R11); only a
    gate approved before that check can still carry one, and waiting on
    a card that will never exist would strand the task for ever.
    """
    valid = tuple(p for p in task.prerequisites if p in known)
    if len(valid) != len(task.prerequisites):
        _log.warning(
            "task %s: dropping unknown prerequisite(s) %s",
            task.task_node_id,
            sorted(set(task.prerequisites) - known),
        )
    return valid


def _write_task_spec(
    card_id: str,
    task: DecompositionTask,
    titles: dict[str, str],
    target: MaterialiseTarget,
) -> None:
    target.artifacts.store_document(
        card_id, TASK_SPEC_LOGICAL_NAME, 1, render_task_spec(task, titles),
        trust="operator_approved",
    )


def render_task_spec(
    task: DecompositionTask, titles: dict[str, str]
) -> Document:
    """*task* as approved at CAB-2, for its cards' envelopes and the
    cockpit (data-model.md ``task_spec``). The task body is the agent's
    Markdown, parsed at the agent boundary."""
    blocks: list[Block] = [
        Heading(1, (Text(task.title),)), _classification_line(task),
    ]
    if task.prerequisites:
        names = ", ".join(titles.get(p, p) for p in task.prerequisites)
        blocks.append(paragraph(Text(f"Prerequisites: {names}")))
    blocks += from_agent(task.body).blocks
    if task.estimate is not None:
        blocks += _estimate_section(task.estimate)
    return document(*blocks)


def _classification_line(task: DecompositionTask) -> Paragraph:
    if task.classification == MANUAL:
        return paragraph(
            Strong("Manual task"),
            Text(": for a human. kestrel will not assign this to an agent."),
        )
    return paragraph(
        Strong("Coding task"), Text(": implemented and verified by agents.")
    )


def _estimate_section(estimate: TaskEstimate) -> list[Block]:
    blocks: list[Block] = [
        Heading(2, (Text("Estimate (agent, unverified)"),)),
        paragraph(Text(
            f"Size {estimate.size} · confidence {estimate.confidence} · "
            f"~{estimate.man_hours:.1f} man-hours · "
            f"~{estimate.agent_tokens:,} agent tokens · "
            f"~{estimate.review_hours:.1f} review hours"
        )),
    ]
    if estimate.risks:
        blocks.append(paragraph(Text(f"Risks: {', '.join(estimate.risks)}")))
    blocks.append(paragraph(Text(f"Rationale: {estimate.rationale}")))
    return blocks


def task_context(
    card: WorkCard, cards: list[WorkCard], artifacts: ArtifactsService
) -> str:
    """The envelope extra for any card working on an approved task
    (research R3): its head card's ``task_spec``, or ``""`` for a card
    with no task (or a head card that somehow lost it)."""
    if not card.task_node_id:
        return ""
    head = next(
        (
            c for c in cards
            if c.task_node_id == card.task_node_id and c.kind in HEAD_KINDS
        ),
        None,
    )
    if head is None:
        return ""
    spec = artifacts.latest_document_for_card(head.id, TASK_SPEC_LOGICAL_NAME)
    return f"Approved task:\n{to_prompt(spec)}" if spec else ""


def render_breakdown(candidate: Candidate) -> Document:
    """The one comment posted to the request's ticket on approval
    (FR-006), in place of one child ticket per task."""
    intro = paragraph(Text(
        "Approved task breakdown (CAB-2). kestrel works these tasks inside "
        "this request and delivers them as one change; no separate "
        "tickets are created."
    ))
    if not candidate.tasks:
        return document(intro)
    items = tuple(
        ListItem((paragraph(Text(f"{task.title} ({_who(task)})")),))
        for task in candidate.tasks
    )
    return document(intro, OrderedList(1, items))


def _who(task: DecompositionTask) -> str:
    return "manual, for a human" if task.classification == MANUAL else "coding"

