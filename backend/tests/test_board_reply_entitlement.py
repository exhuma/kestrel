"""Who may decide from the ticket (feature 046, T032, research R9).

The reporter decides the requester's gates (the understanding, the PRD);
the change owner relays CAB-1 and CAB-2. Anyone else is told so, briefly,
and nothing changes. Interview answers are never taken from the ticket.
Both people are read fresh from the ticket when a reply is handled.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.documents import Text, document, paragraph
from app.models_board import CardKind, WorkCard
from app.ports import Person, Task
from app.services.board.reply_rules import entitled
from tests.announcement_support import (
    CHANGE_OWNER,
    REPORTER,
    TASK_REF,
    WORKFLOW_ID,
    add_plan,
    open_gate,
    open_interview_gate,
)
from tests.reply_support import (
    STRANGER,
    ReplyStack,
    build_reply_stack,
    reply_ticket,
)

_REQUESTER_GATES = [
    (CardKind.UNDERSTANDING_GATE, "confirm_understanding"),
    (CardKind.PRD_GATE, "approve_prd"),
]
_CAB_GATES = [
    (CardKind.CAB1_GATE, "approve_strategic_fit"),
    (CardKind.DECOMPOSITION_GATE, "approve_decomposition"),
]


def _task(reporter: Person | None, owner: Person | None = None) -> Task:
    return Task(
        TASK_REF, "t", document(paragraph(Text("x"))),
        reporter=reporter, change_owner=owner,
    )


async def _reply(stack: ReplyStack, author: Person, text: str) -> str:
    """Write *text* as *author*, poll once, and return kestrel's answer."""
    before = len(stack.ticket.comments())
    stack.ticket.write(author, text)
    await stack.read()
    (answer,) = stack.ticket.comments()[before:]
    return answer


def _state(stack: ReplyStack, card_id: str) -> str:
    return stack.board.store.get_card(card_id).state


@pytest.mark.parametrize("kind, decision", _REQUESTER_GATES)
@pytest.mark.asyncio
async def test_the_reporter_decides_a_requester_gate(
    tmp_path: Path, kind: CardKind, decision: str
) -> None:
    """Ensure the reporter's approval resolves the gate, is credited to
    them, and is confirmed to them."""
    stack = build_reply_stack(tmp_path)
    gate = open_gate(stack.board, kind, None, decision)

    answer = await _reply(stack, REPORTER, "@kestrel looks right")

    assert _state(stack, gate.id) == "done"
    assert stack.decided == [(gate.id, "approved")]
    assert answer.mentions() == {REPORTER.account_id}
    assert "recorded that you approved" in answer.plain_text()
    (event,) = [
        e for e in stack.board.store.list_events(WORKFLOW_ID)
        if e.event_type == "gate.approved"
    ]
    assert json.loads(event.payload)["channel"] == "jira"
    assert json.loads(event.payload)["account_id"] == REPORTER.account_id


@pytest.mark.parametrize("kind, decision", _CAB_GATES)
@pytest.mark.asyncio
async def test_the_change_owner_relays_a_cab_decision(
    tmp_path: Path, kind: CardKind, decision: str
) -> None:
    """Ensure the change owner resolves CAB-1 and CAB-2."""
    stack = build_reply_stack(tmp_path)
    gate = open_gate(stack.board, kind, None, decision)

    answer = await _reply(stack, CHANGE_OWNER, "@kestrel CAB approved")

    assert _state(stack, gate.id) == "done"
    assert answer.mentions() == {CHANGE_OWNER.account_id}


@pytest.mark.parametrize("kind, decision, author", [
    *[(k, d, CHANGE_OWNER) for k, d in _REQUESTER_GATES],
    *[(k, d, REPORTER) for k, d in _CAB_GATES],
    *[(k, d, STRANGER) for k, d in _REQUESTER_GATES + _CAB_GATES],
])
@pytest.mark.asyncio
async def test_anyone_else_is_refused_and_nothing_changes(
    tmp_path: Path, kind: CardKind, decision: str, author: Person
) -> None:
    """Ensure a reply from someone not entitled decides nothing, never
    reaches the liaison, and is answered briefly."""
    stack = build_reply_stack(tmp_path)
    gate = open_gate(stack.board, kind, None, decision)

    answer = await _reply(stack, author, "@kestrel approve")

    assert _state(stack, gate.id) == "awaiting_human"
    assert stack.liaison_backend.prompts == []
    assert "can decide this here" in answer.plain_text()
    assert stack.comments.get(stack.ticket.thread[-1].external_id).state == (
        "refused"
    )


@pytest.mark.parametrize("gate_kind", [
    CardKind.REFINEMENT_GATE, CardKind.STRATEGIC_INTERVIEW_GATE,
])
@pytest.mark.asyncio
async def test_an_interview_gets_the_pointer_to_the_form(
    tmp_path: Path, gate_kind: CardKind
) -> None:
    """Ensure interview answers are never taken from the ticket."""
    stack = build_reply_stack(tmp_path)
    if gate_kind == CardKind.REFINEMENT_GATE:
        gate = open_interview_gate(stack.board, add_plan(stack.board), "dba", 2)
    else:
        gate = open_gate(stack.board, gate_kind, None, "answer")

    answer = await _reply(stack, REPORTER, "@kestrel yes, by Friday")

    assert _state(stack, gate.id) == "awaiting_human"
    assert "form in kestrel" in answer.plain_text()
    assert stack.liaison_backend.prompts == []


@pytest.mark.asyncio
async def test_nothing_open_gets_no_gate(tmp_path: Path) -> None:
    """Ensure a reply while work goes on, with no decision waiting, is
    told so."""
    stack = build_reply_stack(tmp_path)
    stack.board.store.create_card(WorkCard(
        id="card-work", workflow_id=WORKFLOW_ID,
        kind=CardKind.ANALYSIS.value, title="Analyse", state="ready",
    ))

    answer = await _reply(stack, REPORTER, "@kestrel approve")

    assert "nothing on this request is waiting" in answer.plain_text()
    assert stack.comments.get(stack.ticket.thread[-1].external_id).state == (
        "no_gate"
    )


@pytest.mark.asyncio
async def test_the_people_are_read_again_for_each_reply(
    tmp_path: Path,
) -> None:
    """Ensure a reporter changed on the ticket is respected at once."""
    stack = build_reply_stack(tmp_path)
    gate = open_gate(
        stack.board, CardKind.UNDERSTANDING_GATE, None,
        "confirm_understanding",
    )
    stack.ticket.task = _task(STRANGER)
    reads = len(stack.ticket.read_refs)

    refused = await _reply(stack, REPORTER, "@kestrel looks right")
    await _reply(stack, STRANGER, "@kestrel looks right")

    assert "can decide this here" in refused.plain_text()
    assert _state(stack, gate.id) == "done"
    assert len(stack.ticket.read_refs) > reads


@pytest.mark.asyncio
async def test_a_reporter_who_is_also_change_owner_decides_both(
    tmp_path: Path,
) -> None:
    """Ensure one person in both roles may act on both kinds of gate."""
    stack = build_reply_stack(
        tmp_path, ticket=reply_ticket(change_owner=REPORTER)
    )
    understanding = open_gate(
        stack.board, CardKind.UNDERSTANDING_GATE, None,
        "confirm_understanding",
    )
    await _reply(stack, REPORTER, "@kestrel looks right")
    cab = open_gate(
        stack.board, CardKind.CAB1_GATE, None, "approve_strategic_fit"
    )
    await _reply(stack, REPORTER, "@kestrel CAB approved")

    assert _state(stack, understanding.id) == "done"
    assert _state(stack, cab.id) == "done"


@pytest.mark.parametrize("author, reporter", [
    (Person(""), Person("")),
    (Person("", "Rita Reporter"), Person("", "Rita Reporter")),
    (Person("acc-1"), None),
    (Person(""), REPORTER),
])
def test_an_empty_or_missing_account_never_matches(
    author: Person, reporter: Person | None
) -> None:
    """Ensure people are matched by account, never by name, and an
    account-less author (Jira Server) matches nobody."""
    task = _task(reporter, reporter)

    assert not entitled(CardKind.UNDERSTANDING_GATE.value, author, task)
    assert not entitled(CardKind.CAB1_GATE.value, author, task)


def test_a_gate_not_put_on_the_ticket_is_decided_by_nobody() -> None:
    """Ensure only the ticket's gates can be decided from it."""
    task = _task(REPORTER, CHANGE_OWNER)

    assert not entitled(CardKind.SECURITY_REVIEW.value, REPORTER, task)
