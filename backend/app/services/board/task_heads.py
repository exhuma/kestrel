"""The card that stands for an approved task, and how it ended (#99).

Every task CAB-2 approves gets an ``implementation`` card and the
``verification`` card that checks it (``materialise.py``). The
implementation card is the task's *head*: the card its dependents wait
on, the one holding its ``task_spec``, and the one its work item on the
task source stands for (``work_items.py``).

A head card is done either because kestrel ran it or because a person
finished the work item on the task source (``handover_poll.py``). The
second is recorded on the card itself, as its ``wait_reason``, so the
board can tell the two apart without the task source.
"""
from __future__ import annotations

from app.models_board import CardKind, CardState, WorkCard

#: The card kinds that head a task.
HEAD_KINDS = frozenset({CardKind.IMPLEMENTATION.value})

#: The ``wait_reason`` of a head card a person finished on the task
#: source: kestrel did not run it, and has nothing of it to deliver.
DONE_BY_PERSON = "Done by a person on the task source."

#: Rounds a person asked for after delivery (``change_rounds.py``): not
#: part of an approved plan, so they have no work item.
LATER_ROUND_PREFIX = "changes-"


def task_heads(cards: list[WorkCard]) -> list[WorkCard]:
    """One head card per approved task, in the order the plan created
    them. A remediation card of the same task comes later, so the first
    card of a head kind is the head."""
    seen: set[str] = set()
    heads = []
    for card in cards:
        node = card.task_node_id
        if (
            not node or node in seen or node.startswith(LATER_ROUND_PREFIX)
            or card.kind not in HEAD_KINDS
        ):
            continue
        seen.add(node)
        heads.append(card)
    return heads


def done_by_person(card: WorkCard) -> bool:
    """Whether *card* is a head card a person finished, not kestrel."""
    return (
        card.kind in HEAD_KINDS
        and card.state == CardState.DONE.value
        and card.wait_reason == DONE_BY_PERSON
    )
