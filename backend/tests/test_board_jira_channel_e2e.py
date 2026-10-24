"""One request, from intake to delivery, decided only on the ticket
(feature 046, T043).

A fake Jira ticket carries the request through every gate: the reporter
and the change owner answer every decision with an ``@kestrel`` reply;
interviews are answered through the existing UI path; a stranger tries at
every step. It checks the success criteria:

- SC-001: every decision but the interviews is taken from the ticket;
- SC-003: one comment per gate opening, and every reply acted on at most
  once, across cycles and a restart;
- SC-004: nobody but the people on the ticket is ever mentioned, and the
  ticket's status is never changed;
- SC-005: a stranger never changes the request.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models_board import CardKind, WorkCard
from app.services.board.comment_poll import CommentPollService
from app.services.board.replies import ReplyService
from tests.announcement_support import (
    CHANGE_OWNER,
    REPORTER,
    WORKFLOW_ID,
    add_plan,
    open_gate,
    open_interview_gate,
)
from tests.reply_support import STRANGER, ReplyStack, build_reply_stack

#: Gate openings in this request: understanding, strategic interview,
#: CAB-1, one refinement batch, two PRD drafts, CAB-2.
_OPENINGS = 7


async def _announce(stack: ReplyStack) -> None:
    await stack.board.service.announce(WORKFLOW_ID)


async def _decide(stack: ReplyStack, gate: WorkCard, person, text: str) -> None:
    """A stranger tries first; then *person* replies *text*. Each poll
    runs twice, so nothing may be acted on twice."""
    await _announce(stack)
    stack.ticket.write(STRANGER, "@kestrel approve")
    stack.ticket.write(person, text)
    await stack.read()
    await stack.read()
    assert stack.board.store.get_card(gate.id).state != "awaiting_human"


def _gate(stack: ReplyStack, kind: CardKind) -> WorkCard:
    """The newest gate of *kind*."""
    (*_, card) = [
        c for c in stack.board.store.list_cards(WORKFLOW_ID)
        if c.kind == kind.value
    ]
    return card


def _answer_in_the_ui(stack: ReplyStack, gate: WorkCard, text: str) -> None:
    stack.board.gates.resolve(gate.id, "approved", answer=text)


async def _carry_the_request(stack: ReplyStack) -> None:
    understanding = open_gate(
        stack.board, CardKind.UNDERSTANDING_GATE, None,
        "confirm_understanding",
    )
    await _decide(stack, understanding, REPORTER, "@kestrel looks right")
    strategic = open_gate(
        stack.board, CardKind.STRATEGIC_INTERVIEW_GATE, None, "answer"
    )
    await _announce(stack)
    _answer_in_the_ui(stack, strategic, "It fits the export roadmap.")
    await _decide(
        stack, _gate(stack, CardKind.CAB1_GATE), CHANGE_OWNER,
        "@kestrel CAB approved",
    )
    interview = open_interview_gate(
        stack.board, add_plan(stack.board), "dba", 1
    )
    await _announce(stack)
    _answer_in_the_ui(stack, interview, "Q: Question 0?\nA: Postgres.")
    first_prd = open_gate(stack.board, CardKind.PRD_GATE, None, "approve_prd")
    await _decide(
        stack, first_prd, REPORTER, "@kestrel no — it must cover exports"
    )
    second_prd = open_gate(stack.board, CardKind.PRD_GATE, None, "approve_prd")
    await _decide(stack, second_prd, REPORTER, "@kestrel looks right")
    cab2 = open_gate(
        stack.board, CardKind.DECOMPOSITION_GATE, None,
        "approve_decomposition",
    )
    await _decide(stack, cab2, CHANGE_OWNER, "@kestrel CAB approved")
    await stack.board.service.delivered(
        WORKFLOW_ID, "card-delivery", "https://git.example/pr/1"
    )


def _decisions(stack: ReplyStack) -> list[dict]:
    return [
        json.loads(e.payload)
        for e in stack.board.store.list_events(WORKFLOW_ID)
        if e.event_type in ("gate.approved", "gate.rejected")
    ]


@pytest.mark.asyncio
async def test_a_request_is_carried_to_delivery_on_the_ticket(
    tmp_path: Path,
) -> None:
    """Ensure the whole request runs on replies, with the success
    criteria holding at every step."""
    stack = build_reply_stack(tmp_path)

    await _carry_the_request(stack)
    restarted = CommentPollService(
        stack.board.store, stack.comments,
        ReplyService(stack.replies._deps), interval_seconds=1.0,
    )
    await restarted.poll_once()

    decisions = _decisions(stack)
    from_ticket = [d for d in decisions if d.get("channel") == "jira"]
    # SC-001: all five decisions from the ticket; only interviews in UI.
    assert len(from_ticket) == len(decisions) - 2
    assert {d["account_id"] for d in from_ticket} == {
        REPORTER.account_id, CHANGE_OWNER.account_id,
    }
    # SC-003: one comment per opening, one answer per reply, nothing twice.
    replies = [f for f in stack.ticket.thread if "@kestrel" in
               f.body.plain_text()]
    assert len(stack.ticket.comments()) == _OPENINGS + len(replies) + 1
    # SC-004: only the people on the ticket are mentioned; no transition.
    mentioned = set().union(*(c.mentions() for c in stack.ticket.comments()))
    assert mentioned <= {
        REPORTER.account_id, CHANGE_OWNER.account_id, STRANGER.account_id,
    }
    assert stack.ticket.transitions == []
    # SC-005: every stranger reply was refused, none decided.
    assert all(
        stack.comments.get(f.external_id).state == "refused"
        for f in stack.ticket.thread if f.author == STRANGER
    )
