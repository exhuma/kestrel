"""Which ticket comments are replies for kestrel (feature 046, T031,
research R8).

There is no kestrel service account: kestrel posts through the
operator's Jira account. A reply is recognised by the plain-text marker;
kestrel's own comments by their ownership ``Marker``. kestrel's
announcements tell people to reply with ``@kestrel``, so they contain the
marker too: the ownership marker is what keeps kestrel from answering
itself.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.documents import Document, Marker, Text, document, paragraph
from app.models_board import CardKind
from app.ports import Feedback, Person
from app.services.board.reply_rules import is_reply, mentions_marker
from tests.announcement_support import open_gate
from tests.reply_support import OPERATOR, build_reply_stack, reply_ticket

_MARKER = "@kestrel"


def _feedback(body: Document) -> Feedback:
    return Feedback(
        "jira-comment:KEY-1:1", "ticket", Person("acc-1", "A"), body,
        datetime.now(timezone.utc),
    )


@pytest.mark.parametrize("text", [
    "@kestrel looks right",
    "@Kestrel looks right",
    "@KESTREL, approved",
    "Looks right (@kestrel)",
    "yes\n@kestrel",
])
def test_the_marker_counts_as_a_whole_word_in_any_case(text: str) -> None:
    """Ensure the marker is found however it is written."""
    assert mentions_marker(text, _MARKER)


@pytest.mark.parametrize("text", [
    "looks right",
    "@kestrels looks right",
    "mail me at me@kestrel.example",
    "kestrel looks right",
    "@kestrel_bot approve",
])
def test_the_marker_inside_another_word_does_not_count(text: str) -> None:
    """Ensure only the marker word itself makes a reply."""
    assert not mentions_marker(text, _MARKER)


def test_an_empty_marker_matches_nothing() -> None:
    """Ensure a misconfigured marker fails closed."""
    assert not mentions_marker("@kestrel approve", "")
    assert not mentions_marker("anything", "  ")


def test_kestrels_own_comment_is_skipped_although_it_has_the_marker(
) -> None:
    """Ensure the ownership marker wins over the reply marker."""
    body = document(
        paragraph(Text("To answer, reply with @kestrel and your answer.")),
        Marker("posted"),
    )

    assert not is_reply(_feedback(body), _MARKER)


def test_an_unmarked_comment_with_the_marker_is_a_reply() -> None:
    """Ensure anyone's marked reply, the operator's too, is considered."""
    body = document(paragraph(Text("@kestrel looks right")))

    assert is_reply(_feedback(body), _MARKER)


@pytest.mark.asyncio
async def test_kestrel_never_answers_its_own_announcements(
    tmp_path: Path,
) -> None:
    """Ensure a real announcement, which tells people to reply with
    @kestrel, is never taken as a reply on the next poll."""
    stack = build_reply_stack(tmp_path)
    open_gate(
        stack.board, CardKind.UNDERSTANDING_GATE, None,
        "confirm_understanding",
    )
    await stack.board.service.announce("wf-1")
    (announcement,) = stack.ticket.comments()
    assert "@kestrel" in announcement.plain_text()
    stack.ticket.write(OPERATOR, announcement.plain_text(), posted=True)

    taken = await stack.read()

    assert taken == 0
    assert len(stack.ticket.comments()) == 1
    assert stack.liaison_backend.prompts == []


@pytest.mark.asyncio
async def test_the_operators_own_unmarked_reply_is_considered(
    tmp_path: Path,
) -> None:
    """Ensure the operator (the account kestrel posts with) is read like
    anyone else, and decides when entitled."""
    stack = build_reply_stack(
        tmp_path, ticket=reply_ticket(reporter=OPERATOR)
    )
    gate = open_gate(
        stack.board, CardKind.UNDERSTANDING_GATE, None,
        "confirm_understanding",
    )
    await stack.announce()
    stack.ticket.write(OPERATOR, "@kestrel looks right")

    taken = await stack.read()

    assert taken == 1
    assert stack.board.store.get_card(gate.id).state == "done"


@pytest.mark.asyncio
async def test_a_comment_without_the_marker_is_ignored(
    tmp_path: Path,
) -> None:
    """Ensure an ordinary discussion comment changes nothing and gets no
    answer."""
    stack = build_reply_stack(tmp_path)
    gate = open_gate(
        stack.board, CardKind.UNDERSTANDING_GATE, None,
        "confirm_understanding",
    )
    await stack.announce()
    stack.ticket.write(stack.ticket.task.reporter, "looks right to me")

    taken = await stack.read()

    assert taken == 0
    assert stack.ticket.answers() == []
    assert stack.board.store.get_card(gate.id).state == "awaiting_human"
