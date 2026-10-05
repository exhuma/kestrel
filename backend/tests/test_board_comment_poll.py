"""Reading replies on the ticket, at most once each (feature 046, T035).

The poll reads each active request's new comments from its cursor and
hands them over oldest first. A comment is acted on at most once, across
cycles, restarts and edits; the first reply that decides wins; a held
reply waits for the operator.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.models_board import CardKind
from app.services.board import bootstrap_replies
from app.services.board.bootstrap_replies import HeldReplies
from app.services.board.comment_poll import CommentPollService
from app.services.board.replies import ReplyService
from tests.announcement_support import REPORTER, WORKFLOW_ID, open_gate
from tests.reply_support import (
    SUSPECT,
    ReplyStack,
    build_reply_stack,
)

_TWO = 2


async def _understanding(stack: ReplyStack):
    """An understanding gate, opened and announced."""
    gate = open_gate(
        stack.board, CardKind.UNDERSTANDING_GATE, None,
        "confirm_understanding",
    )
    await stack.announce()
    return gate


def _state(stack: ReplyStack, card_id: str) -> str:
    return stack.board.store.get_card(card_id).state


def _restarted(stack: ReplyStack) -> CommentPollService:
    """A new reply service and poll over the same database, as after a
    restart."""
    replies = ReplyService(stack.replies._deps)  # same wiring, new state
    return CommentPollService(
        stack.board.store, stack.comments, replies, interval_seconds=1.0
    )


@pytest.mark.asyncio
async def test_the_cursor_advances(tmp_path: Path) -> None:
    """Ensure the next read starts where the last one ended."""
    stack = build_reply_stack(tmp_path)
    await _understanding(stack)
    stack.ticket.write(REPORTER, "an ordinary comment")
    last = stack.ticket.write(REPORTER, "another one")

    await stack.read()
    await stack.read()

    assert stack.ticket.list_calls == [None, last.created_at.isoformat()]
    assert stack.comments.get_cursor(WORKFLOW_ID) == (
        last.created_at.isoformat()
    )


@pytest.mark.asyncio
async def test_a_reply_is_acted_on_once_across_cycles_and_restarts(
    tmp_path: Path,
) -> None:
    """Ensure the re-read boundary comment, a second cycle and a restart
    never answer or decide twice."""
    stack = build_reply_stack(tmp_path)
    gate = await _understanding(stack)
    stack.ticket.write(REPORTER, "@kestrel looks right")

    assert await stack.read() == 1
    assert await stack.read() == 0
    assert await _restarted(stack).poll_once() == 0

    assert _state(stack, gate.id) == "done"
    assert len(stack.ticket.answers()) == 1
    assert len(stack.liaison_backend.prompts) == 1


@pytest.mark.asyncio
async def test_an_edited_reply_is_not_read_again(tmp_path: Path) -> None:
    """Ensure the original version stands and the edit is ignored."""
    stack = build_reply_stack(tmp_path)
    gate = await _understanding(stack)
    reply = stack.ticket.write(REPORTER, "@kestrel looks right")
    await stack.read()

    stack.ticket.edit(reply, "@kestrel no, it must also cover exports")
    stack.comments.set_cursor(WORKFLOW_ID, None)  # even read from the start
    await stack.read()

    assert _state(stack, gate.id) == "done"
    assert len(stack.ticket.answers()) == 1


@pytest.mark.asyncio
async def test_the_first_reply_decides_and_the_rest_are_already_decided(
    tmp_path: Path,
) -> None:
    """Ensure several replies are taken in the order written."""
    stack = build_reply_stack(tmp_path)
    gate = await _understanding(stack)
    stack.ticket.write(REPORTER, "@kestrel looks right")
    stack.ticket.write(REPORTER, "@kestrel no, it must also cover exports")

    assert await stack.read() == _TWO

    assert _state(stack, gate.id) == "done"
    first, second = stack.ticket.answers()
    assert "thank you. Understanding confirmed." in first
    assert "already decided (approved) by Rita Reporter via Jira" in second


@pytest.mark.asyncio
async def test_a_gate_decided_in_the_ui_first_is_already_decided(
    tmp_path: Path,
) -> None:
    """Ensure a reply read after a UI decision changes nothing, and says
    the decision was taken in kestrel."""
    stack = build_reply_stack(tmp_path)
    gate = await _understanding(stack)
    stack.ticket.write(REPORTER, "@kestrel no, it must also cover exports")
    stack.board.gates.resolve(gate.id, "approved")

    await stack.read()

    (answer,) = stack.ticket.answers()
    assert "already decided (approved) in kestrel" in answer
    assert stack.liaison_backend.prompts == []


@pytest.mark.asyncio
async def test_a_late_reply_never_decides_the_next_gate(
    tmp_path: Path,
) -> None:
    """Ensure a reply written to one gate is not applied to the gate that
    opened after it."""
    stack = build_reply_stack(tmp_path)
    understanding = await _understanding(stack)
    stack.ticket.write(REPORTER, "@kestrel looks right")
    stack.board.gates.resolve(understanding.id, "approved")
    prd = open_gate(stack.board, CardKind.PRD_GATE, None, "approve_prd")

    await stack.read()

    assert _state(stack, prd.id) == "awaiting_human"
    assert "already decided" in stack.ticket.answers()[0]


@pytest.mark.asyncio
async def test_a_reasoned_rejection_passes_its_reason_on(
    tmp_path: Path,
) -> None:
    """Ensure the reason reaches the gate as its answer, as the UI's
    correction would."""
    stack = build_reply_stack(tmp_path)
    gate = await _understanding(stack)
    stack.ticket.write(REPORTER, "@kestrel no — it must also cover exports")

    await stack.read()

    assert _state(stack, gate.id) == "cancelled"
    response = stack.board.artifacts.latest_for_card(gate.id, "response")
    assert stack.board.artifacts.read_content(response.id) == (
        "it must also cover exports"
    )
    assert "thank you. Understanding corrected" in stack.ticket.answers()[0]


@pytest.mark.parametrize("text, expected", [
    ("@kestrel no", "needs to know why"),
    ("@kestrel what about exports?", "could not tell"),
])
@pytest.mark.asyncio
async def test_an_unclear_or_reasonless_reply_is_asked_back(
    tmp_path: Path, text: str, expected: str
) -> None:
    """Ensure kestrel asks back and the gate stays open."""
    stack = build_reply_stack(tmp_path)
    gate = open_gate(stack.board, CardKind.PRD_GATE, None, "approve_prd")
    await stack.announce()
    stack.ticket.write(REPORTER, text)

    await stack.read()

    assert _state(stack, gate.id) == "awaiting_human"
    (answer,) = stack.ticket.answers()
    assert expected in answer and "@kestrel" in answer


@pytest.mark.asyncio
async def test_a_held_reply_decides_nothing_until_released(
    tmp_path: Path,
) -> None:
    """Ensure screening holds a suspicious reply, the ticket says so, and
    the release has it acted on, once."""
    stack = build_reply_stack(tmp_path)
    gate = await _understanding(stack)
    reply = stack.ticket.write(REPORTER, f"@kestrel looks right {SUSPECT}")

    await stack.read()

    held = stack.comments.get(reply.external_id)
    assert held.state == "held" and held.security_review_id
    assert _state(stack, gate.id) == "awaiting_human"
    assert "held for a security review" in stack.ticket.answers()[0]
    assert stack.liaison_backend.prompts == []

    stack.quarantine.release(held.security_review_id)
    assert await stack.replies.continue_released(held.security_review_id)
    assert await stack.replies.continue_released(held.security_review_id)

    assert _state(stack, gate.id) == "done"
    assert len(stack.liaison_backend.prompts) == 1
    assert "thank you. Understanding confirmed." in stack.ticket.answers()[1]
    assert len(stack.ticket.answers()) == _TWO


@pytest.mark.asyncio
async def test_a_discarded_reply_is_never_acted_on_and_the_ticket_is_told(
    tmp_path: Path,
) -> None:
    """Ensure a discard leaves the gate open and says so, once."""
    stack = build_reply_stack(tmp_path)
    gate = await _understanding(stack)
    reply = stack.ticket.write(REPORTER, f"@kestrel approve {SUSPECT}")
    await stack.read()
    review_id = stack.comments.get(reply.external_id).security_review_id

    stack.quarantine.discard(review_id)
    assert await stack.replies.discarded(review_id)
    assert await stack.replies.discarded(review_id)
    await stack.read()

    assert _state(stack, gate.id) == "awaiting_human"
    assert len(stack.ticket.answers()) == _TWO
    assert "has not been acted on" in stack.ticket.answers()[1]


@pytest.mark.asyncio
async def test_a_review_that_holds_no_reply_is_left_to_intake(
    tmp_path: Path,
) -> None:
    """Ensure a task-intake review is not mistaken for a held reply."""
    stack = build_reply_stack(tmp_path)

    assert not await stack.replies.continue_released("review-other")
    assert not await stack.replies.discarded("review-other")


@pytest.mark.asyncio
async def test_an_unreadable_ticket_is_tried_again_next_cycle(
    tmp_path: Path,
) -> None:
    """Ensure a failed read neither raises nor loses the reply."""
    stack = build_reply_stack(tmp_path)
    gate = await _understanding(stack)
    stack.ticket.write(REPORTER, "@kestrel looks right")
    stack.ticket._unreadable = True  # the ticket cannot be fetched

    assert await stack.read() == 0
    stack.ticket._unreadable = False
    assert await stack.read() == 1

    assert _state(stack, gate.id) == "done"


@pytest.mark.asyncio
async def test_a_finished_request_is_not_read(tmp_path: Path) -> None:
    """Ensure only requests still in progress are polled."""
    stack = build_reply_stack(tmp_path)
    gate = open_gate(
        stack.board, CardKind.CAB1_GATE, None, "approve_strategic_fit"
    )
    stack.board.gates.resolve(gate.id, "rejected")

    await stack.read()

    assert stack.ticket.list_calls == []


@pytest.mark.asyncio
async def test_nothing_is_read_when_kestrel_cannot_mark_its_comments(
    tmp_path: Path,
) -> None:
    """Ensure kestrel never risks answering itself: without its ownership
    marker the loop reads nothing."""
    stack = build_reply_stack(tmp_path, enabled=False)
    await _understanding(stack)
    stack.ticket.write(REPORTER, "@kestrel looks right")

    assert await stack.read() == 0
    await stack.poll.run_forever()  # returns at once

    assert stack.ticket.list_calls == []


@pytest.mark.asyncio
async def test_the_release_route_continues_a_held_reply_in_the_background(
    tmp_path: Path,
) -> None:
    """Ensure the route's continuation acts on the released reply, and
    leaves a review that holds no reply to task intake."""
    stack = build_reply_stack(tmp_path)
    gate = await _understanding(stack)
    reply = stack.ticket.write(REPORTER, f"@kestrel looks right {SUSPECT}")
    await stack.read()
    review_id = stack.comments.get(reply.external_id).security_review_id
    stack.quarantine.release(review_id)
    held = HeldReplies(stack.comments, stack.replies)

    assert not held.schedule("review-other", released=True)
    assert held.schedule(review_id, released=True)
    await asyncio.gather(*bootstrap_replies._running)

    assert _state(stack, gate.id) == "done"
