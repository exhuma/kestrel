"""Only replies written after the announcement count (feature 046, T049,
added after the maintainer's review).

A comment written before kestrel posted a gate's announcement was not
written in answer to it: it is never acted on for that gate and gets no
answer. While the announcement is unposted (it failed and is retrying)
nothing counts either. The poll's first read after a deploy, which sees
the whole thread, therefore never answers old comments.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.models_board import CardKind, WorkCard
from app.models_board_records import HumanGateRecord
from app.services.board.reply_rules import OpenedGate, counts_for
from tests.announcement_support import REPORTER, open_gate
from tests.reply_support import ReplyStack, build_reply_stack, reply_ticket

_NOW = datetime(2026, 10, 5, 12, 0, 0)


def _open(stack: ReplyStack, kind: CardKind, decision: str):
    return open_gate(stack.board, kind, None, decision)


def _state(stack: ReplyStack, card_id: str) -> str:
    return stack.board.store.get_card(card_id).state


def _recorded(stack: ReplyStack, comment_id: str) -> str:
    return stack.comments.get(comment_id).state


def _gate(announced_at: datetime | None) -> OpenedGate:
    card = WorkCard(
        id="card-1", workflow_id="wf-1", kind="prd_gate", title="PRD",
        state="awaiting_human",
    )
    record = HumanGateRecord("gate-1", card.id, "approve_prd")
    return OpenedGate(card, record, _NOW, announced_at)


@pytest.mark.asyncio
async def test_a_reply_from_before_the_announcement_is_ignored(
    tmp_path: Path,
) -> None:
    """Ensure an @kestrel comment written before the announcement decides
    nothing, reaches no liaison, and is not answered."""
    stack = build_reply_stack(tmp_path)
    gate = _open(
        stack, CardKind.UNDERSTANDING_GATE, "confirm_understanding"
    )
    old = stack.ticket.write(REPORTER, "@kestrel looks right")
    await stack.announce()

    await stack.read()

    assert _state(stack, gate.id) == "awaiting_human"
    assert _recorded(stack, old.external_id) == "ignored"
    assert stack.liaison_backend.prompts == []
    assert stack.ticket.answers() == []


@pytest.mark.asyncio
async def test_a_reply_from_after_the_announcement_decides(
    tmp_path: Path,
) -> None:
    """Ensure the same words, written after the announcement, count."""
    stack = build_reply_stack(tmp_path)
    gate = _open(
        stack, CardKind.UNDERSTANDING_GATE, "confirm_understanding"
    )
    stack.ticket.write(REPORTER, "@kestrel looks right")
    await stack.announce()
    new = stack.ticket.write(REPORTER, "@kestrel looks right")

    await stack.read()

    assert _state(stack, gate.id) == "done"
    assert _recorded(stack, new.external_id) == "decided"
    assert len(stack.ticket.answers()) == 1


@pytest.mark.asyncio
async def test_nothing_counts_while_the_announcement_is_unposted(
    tmp_path: Path,
) -> None:
    """Ensure a failed announcement, still retrying, means no reply
    counts yet, and the ignored one is not acted on later either."""
    stack = build_reply_stack(tmp_path, ticket=reply_ticket(failures=1))
    gate = _open(
        stack, CardKind.UNDERSTANDING_GATE, "confirm_understanding"
    )
    await stack.announce()
    early = stack.ticket.write(REPORTER, "@kestrel looks right")

    await stack.read()
    await stack.announce()  # nothing is retried by a pass; still unposted
    await stack.read()

    assert stack.ticket.posted == []
    assert _state(stack, gate.id) == "awaiting_human"
    assert _recorded(stack, early.external_id) == "ignored"
    assert stack.liaison_backend.prompts == []


@pytest.mark.asyncio
async def test_a_reply_before_the_next_announcement_is_not_for_the_old_gate(
    tmp_path: Path,
) -> None:
    """Ensure a comment written once the next gate is open but before its
    announcement neither decides it nor is told the old gate is decided."""
    stack = build_reply_stack(tmp_path)
    first = _open(
        stack, CardKind.UNDERSTANDING_GATE, "confirm_understanding"
    )
    await stack.announce()
    stack.board.gates.resolve(first.id, "approved")
    second = _open(stack, CardKind.PRD_GATE, "approve_prd")
    early = stack.ticket.write(REPORTER, "@kestrel looks right")
    await stack.announce()

    await stack.read()

    assert _state(stack, second.id) == "awaiting_human"
    assert _recorded(stack, early.external_id) == "ignored"
    assert stack.ticket.answers() == []


@pytest.mark.asyncio
async def test_the_first_read_of_a_long_thread_answers_nothing_old(
    tmp_path: Path,
) -> None:
    """Ensure a thread of old comments, read in one go after the
    announcement, yields no answers at all."""
    stack = build_reply_stack(tmp_path)
    _open(stack, CardKind.PRD_GATE, "approve_prd")
    for text in ("@kestrel approve", "@kestrel what is this?", "@kestrel no"):
        stack.ticket.write(REPORTER, text)
    await stack.announce()

    await stack.read()

    assert stack.ticket.answers() == []
    assert stack.liaison_backend.prompts == []


def test_counts_for_needs_a_posted_announcement_before_the_reply() -> None:
    """Ensure the rule is strict: unposted, equal and earlier all fail."""
    moment = timedelta(seconds=1)

    assert not counts_for(_gate(None), _NOW + moment)
    assert not counts_for(_gate(_NOW), _NOW)
    assert not counts_for(_gate(_NOW), _NOW - moment)
    assert counts_for(_gate(_NOW), _NOW + moment)
