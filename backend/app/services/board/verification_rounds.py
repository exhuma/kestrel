"""Verification rounds for an approved CAB-2 task (feature 031, R6).

A task materialised from an approved decomposition is verified on its
own, and delivery waits for its clean verification (research R7). So
every fix a verifier asks for must be verified again, and that loop
needs a bound: after ``cap`` verification rounds for one task, a further
non-clean result escalates to a ``coordinator_review`` instead of
spawning more work (the core of #61, for these tasks only).

Every follow-up carries the verified card's ``task_node_id``, so it
works from the same approved task text and counts towards the same
task. A verification card without one is routed exactly as before
(``verification.py``).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from app.models_board import TERMINAL_STATES, CardKind, CardState, WorkCard
from app.services.board.coordinator import CreateCardAction

_VERIFY_PREFIX = "Verify: "


@dataclass(frozen=True)
class RoundContext:
    """What tagged verification routing needs beyond the coordinator.

    :param list_cards: Reads a workflow's current cards (a fresh read is
        needed after the remediation cards exist).
    :param cap: The most verification rounds one task may have
        (``Settings.max_verify_iterations``).
    """

    list_cards: Callable[[str], list[WorkCard]]
    cap: int


def round_of(task_node_id: str, cards: list[WorkCard]) -> int:
    """How many verification rounds *task_node_id* has had so far."""
    return sum(
        1 for c in cards
        if c.kind == CardKind.VERIFICATION.value
        and c.task_node_id == task_node_id
    )


def task_title(card: WorkCard) -> str:
    """The approved task's title, from its verification card's title."""
    return card.title.removeprefix(_VERIFY_PREFIX)


def tagged_follow_ups(
    card: WorkCard, actions: list[CreateCardAction], context: RoundContext
) -> list[CreateCardAction]:
    """*actions* for tagged verification *card*, tied to its task — or,
    once the task has used up its rounds, one cap escalation in place of
    any remediation."""
    node = card.task_node_id
    tagged = [replace(a, task_node_id=node) for a in actions]
    remediation = [a for a in tagged if _is_remediation(a)]
    if not remediation:
        return tagged
    if round_of(node, context.list_cards(card.workflow_id)) < context.cap:
        return tagged
    escalations = [a for a in tagged if not _is_remediation(a)]
    return [*escalations, CreateCardAction(
        kind=CardKind.COORDINATOR_REVIEW.value,
        title=f"Verification cap reached: {task_title(card)}",
        task_node_id=node,
    )]


def reverification(
    card: WorkCard, context: RoundContext
) -> CreateCardAction | None:
    """The next round's verification for *card*'s task, depending on
    every still-open implementation card of that task — after routing,
    exactly the remediation just created. ``None`` if there is none (a
    clean or escalation-only result, or the cap was reached)."""
    open_work = tuple(
        c.id for c in context.list_cards(card.workflow_id)
        if c.kind == CardKind.IMPLEMENTATION.value
        and c.task_node_id == card.task_node_id
        and CardState(c.state) not in TERMINAL_STATES
    )
    if not open_work:
        return None
    return CreateCardAction(
        kind=CardKind.VERIFICATION.value,
        title=f"{_VERIFY_PREFIX}{task_title(card)}",
        eligible_roles=("verifier",),
        workspace_permission="read_only",
        depends_on=open_work,
        task_node_id=card.task_node_id,
    )


def _is_remediation(action: CreateCardAction) -> bool:
    return action.kind == CardKind.IMPLEMENTATION.value
