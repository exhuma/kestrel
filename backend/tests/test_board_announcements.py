"""What kestrel says on the ticket (feature 046, T021; data-model.md
"Announcements: event -> comment").

Drives the announcement service over a recording ticket: one test per row
of the table, plus the rules that hold across rows. The ticket is only
ever commented on: it records any status transition it is asked for, and
no announcement asks for one (T023 asserts that over a whole request).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.documents import (
    Document,
    Link,
    Marker,
    Paragraph,
    Text,
    document,
    paragraph,
)
from app.models_board import CardKind, WorkCard
from app.services.board.announcements import gates as words
from app.services.board.announcements import status as status_words
from app.services.board.announcements.common import Context, People
from app.services.board.artifacts import ArtifactDraft
from app.services.board.estimation import SUMMARY_LOGICAL_NAME
from tests.announcement_support import (
    BASE_URL,
    CHANGE_OWNER,
    REPORTER,
    WORKFLOW_ID,
    Stack,
    add_plan,
    build_stack,
    open_document_gate,
    open_gate,
    open_interview_gate,
    producer,
    questions_artifact,
    ticket,
)

_REQUEST_PAGE = f"{BASE_URL}/#/requests/{WORKFLOW_ID}"
_INTERVIEW_PAGE = f"{_REQUEST_PAGE}/interview"
_THREE = 3
_TWO = 2


def _links(comment: Document) -> list[str]:
    return [
        inline.href
        for block in comment.blocks if isinstance(block, Paragraph)
        for inline in block.content if isinstance(inline, Link)
    ]


def _ends_with_link_then_marker(comment: Document, page: str) -> bool:
    *_, link, marker = comment.blocks
    return (
        isinstance(link, Paragraph)
        and isinstance(link.content[0], Link)
        and link.content[0].href == page
        and marker == Marker("posted")
    )


async def _announced(stack: Stack) -> list[Document]:
    await stack.service.announce(WORKFLOW_ID)
    return stack.source.comments()


def _the_one(comments: list[Document]) -> Document:
    assert len(comments) == 1
    return comments[0]


async def _understanding(tmp_path: Path, **stack_options) -> Document:
    stack = build_stack(tmp_path, **stack_options)
    open_document_gate(
        stack, CardKind.UNDERSTANDING_GATE, CardKind.UNDERSTANDING,
        "You want a CSV export of the report.",
    )
    return _the_one(await _announced(stack))


@pytest.mark.asyncio
async def test_understanding_shows_the_restatement_and_asks_the_reporter(
    tmp_path: Path,
) -> None:
    """Ensure the reporter sees what kestrel understood, in full, and is
    mentioned (spec US2, scenario 1)."""
    comment = await _understanding(tmp_path)

    assert "You want a CSV export of the report." in comment.plain_text()
    assert "confirm" in comment.plain_text().lower() or (
        "right" in comment.plain_text()
    )
    assert comment.mentions() == frozenset({REPORTER.account_id})
    assert _ends_with_link_then_marker(comment, _REQUEST_PAGE)


@pytest.mark.asyncio
async def test_the_strategic_interview_links_the_form_and_asks_nothing_here(
    tmp_path: Path,
) -> None:
    """Ensure interview gates link to the form and ask for nothing on the
    ticket (scenario 2)."""
    stack = build_stack(tmp_path)
    card = producer(stack, CardKind.STRATEGIC_INTERVIEW)
    target = questions_artifact(stack, card, _THREE)
    open_gate(stack, CardKind.STRATEGIC_INTERVIEW_GATE, target, "answer")

    comment = _the_one(await _announced(stack))

    assert f"{_THREE} questions" in comment.plain_text()
    assert "Nothing needs to be written here" in comment.plain_text()
    assert comment.mentions() == frozenset({REPORTER.account_id})
    assert _ends_with_link_then_marker(comment, _INTERVIEW_PAGE)


@pytest.mark.asyncio
async def test_a_refinement_batch_gets_one_comment(tmp_path: Path) -> None:
    """Ensure a batch of interview gates is announced once, keyed by its
    plan, saying who asks and how much (scenario 2)."""
    stack = build_stack(tmp_path)
    plan = add_plan(stack)
    open_interview_gate(stack, plan, "dba", _TWO)
    open_interview_gate(stack, plan, "infosec", 1)

    comment = _the_one(await _announced(stack))

    text = comment.plain_text()
    assert f"DBA: {_TWO} questions" in text
    assert "INFOSEC: 1 question" in text
    assert comment.mentions() == frozenset({REPORTER.account_id})
    assert stack.projections.recorded(f"gate_opened:batch:{plan.id}")
    assert _ends_with_link_then_marker(comment, _INTERVIEW_PAGE)


@pytest.mark.asyncio
async def test_the_next_batch_is_a_new_comment(tmp_path: Path) -> None:
    """Ensure each interview round gets its own comment."""
    stack = build_stack(tmp_path)
    open_interview_gate(stack, add_plan(stack), "dba", 1)
    await _announced(stack)
    open_interview_gate(stack, add_plan(stack), "infosec", 1)

    comments = await _announced(stack)

    assert len(comments) == _TWO


@pytest.mark.asyncio
async def test_the_prd_is_shown_in_full(tmp_path: Path) -> None:
    """Ensure the reporter reads the whole PRD on the ticket (scenario
    3)."""
    stack = build_stack(tmp_path)
    open_document_gate(
        stack, CardKind.PRD_GATE, CardKind.PRD, "Export as CSV, nightly."
    )

    comment = _the_one(await _announced(stack))

    assert "Export as CSV, nightly." in comment.plain_text()
    assert comment.mentions() == frozenset({REPORTER.account_id})
    assert _ends_with_link_then_marker(comment, _REQUEST_PAGE)


@pytest.mark.asyncio
async def test_cab1_mentions_the_change_owner_and_nobody_else(
    tmp_path: Path,
) -> None:
    """Ensure CAB-1 says 'ready for CAB' with the strategic-fit answers,
    to the change owner only (scenario 4)."""
    stack = build_stack(tmp_path)
    answered = producer(stack, CardKind.STRATEGIC_INTERVIEW_GATE)
    artifact = stack.artifacts.store_reference_artifact(_response(answered))
    open_gate(stack, CardKind.CAB1_GATE, artifact.id, "approve_strategic_fit")

    comment = _the_one(await _announced(stack))

    assert "ready for CAB" in comment.plain_text()
    assert "Why now?" in comment.plain_text()
    assert "Audit season." in comment.plain_text()
    assert comment.mentions() == frozenset({CHANGE_OWNER.account_id})
    assert _ends_with_link_then_marker(comment, _REQUEST_PAGE)


def _response(card: WorkCard) -> ArtifactDraft:
    return ArtifactDraft(
        producer_card_id=card.id, logical_name="response", revision=1,
        content="Q: Why now?\nA: Audit season.", trust="operator_approved",
    )


@pytest.mark.asyncio
async def test_cab2_shows_the_summary_to_the_change_owner(
    tmp_path: Path,
) -> None:
    """Ensure CAB-2 carries the executive summary and mentions the
    change owner only (scenario 4)."""
    stack = build_stack(tmp_path)
    gate = open_gate(stack, CardKind.DECOMPOSITION_GATE, None, "approve")
    stack.artifacts.store_document(
        gate.id, SUMMARY_LOGICAL_NAME, 1,
        document(paragraph(Text("Two tasks, 8 man-hours."))),
    )

    comment = _the_one(await _announced(stack))

    assert "ready for CAB" in comment.plain_text()
    assert "Two tasks, 8 man-hours." in comment.plain_text()
    assert comment.mentions() == frozenset({CHANGE_OWNER.account_id})


@pytest.mark.asyncio
async def test_without_a_change_owner_the_comment_says_so(
    tmp_path: Path,
) -> None:
    """Ensure a ticket with no change owner is told the decision is taken
    in kestrel, and nobody is mentioned (scenario 8)."""
    stack = build_stack(tmp_path, source=ticket(change_owner=None))
    open_gate(stack, CardKind.DECOMPOSITION_GATE, None, "approve")

    comment = _the_one(await _announced(stack))

    assert "No change owner is set" in comment.plain_text()
    assert "taken in kestrel" in comment.plain_text()
    assert comment.mentions() == frozenset()


@pytest.mark.asyncio
async def test_an_unreadable_ticket_does_not_claim_there_is_no_owner(
    tmp_path: Path,
) -> None:
    """Ensure failing to read the ticket still announces the gate, with no
    mention and without the 'no change owner' claim."""
    stack = build_stack(tmp_path, source=ticket(unreadable=True))
    open_gate(stack, CardKind.DECOMPOSITION_GATE, None, "approve")

    comment = _the_one(await _announced(stack))

    assert "No change owner is set" not in comment.plain_text()
    assert comment.mentions() == frozenset()


@pytest.mark.asyncio
async def test_delivery_tells_the_change_owner_to_move_on(
    tmp_path: Path,
) -> None:
    """Ensure a delivered request links the change request and mentions
    the change owner (scenario 5)."""
    stack = build_stack(tmp_path)
    location = "https://git.example/o/r/pull/7"

    await stack.service.delivered(WORKFLOW_ID, "card-delivery", location)

    comment = _the_one(stack.source.comments())
    assert location in _links(comment)
    assert "should move on" in comment.plain_text()
    assert comment.mentions() == frozenset({CHANGE_OWNER.account_id})
    assert stack.projections.recorded("delivery:card-delivery")
    assert _ends_with_link_then_marker(comment, _REQUEST_PAGE)


@pytest.mark.asyncio
async def test_a_failed_request_tells_the_change_owner_why(
    tmp_path: Path,
) -> None:
    """Ensure a failed outcome is announced to the change owner, with
    what failed (scenario 5)."""
    stack = build_stack(tmp_path)
    stack.store.create_card(WorkCard(
        id="card-x", workflow_id=WORKFLOW_ID,
        kind=CardKind.IMPLEMENTATION.value, title="Write the exporter",
        state="failed",
    ))

    comment = _the_one(await _announced(stack))

    assert "should move on" in comment.plain_text()
    assert "Write the exporter" in comment.plain_text()
    assert comment.mentions() == frozenset({CHANGE_OWNER.account_id})
    assert stack.projections.recorded(f"status:outcome:{WORKFLOW_ID}")


@pytest.mark.asyncio
async def test_a_request_stopped_by_a_rejection_is_announced(
    tmp_path: Path,
) -> None:
    """Ensure a request that ended because a decision was rejected tells
    the change owner (scenario 5)."""
    stack = build_stack(tmp_path)
    gate = open_gate(stack, CardKind.CAB1_GATE, None, "approve_strategic_fit")
    stack.store.set_card_state(gate.id, "cancelled")

    comment = _the_one(await _announced(stack))

    assert "stopped" in comment.plain_text()
    assert comment.mentions() == frozenset({CHANGE_OWNER.account_id})


@pytest.mark.asyncio
async def test_a_board_between_two_steps_is_not_called_cancelled(
    tmp_path: Path,
) -> None:
    """Ensure finished work with nothing yet created after it (which also
    reads as 'stopped') says nothing: a comment cannot be taken back."""
    stack = build_stack(tmp_path)
    stack.store.create_card(WorkCard(
        id="card-y", workflow_id=WORKFLOW_ID,
        kind=CardKind.IMPLEMENTATION.value, title="Done work", state="done",
    ))

    assert await _announced(stack) == []


@pytest.mark.asyncio
async def test_ci_and_escalation_lines_mention_nobody(
    tmp_path: Path,
) -> None:
    """Ensure status lines on CI and escalation are plain (scenario 6)."""
    stack = build_stack(tmp_path)

    await stack.service.ci_changed(WORKFLOW_ID, "status:ci:c:1:failed", "x")
    await stack.service.ci_changed(WORKFLOW_ID, "status:ci:c:1:repaired", None)
    await stack.service.escalated(WORKFLOW_ID, "escalation:c:1:0", "Unclear")

    comments = stack.source.comments()
    assert len(comments) == _THREE
    assert all(c.mentions() == frozenset() for c in comments)
    assert "Unclear" in comments[2].plain_text()


@pytest.mark.asyncio
async def test_the_link_is_left_out_without_a_public_address(
    tmp_path: Path,
) -> None:
    """Ensure no link is invented when kestrel has no public base URL."""
    comment = await _understanding(tmp_path, base_url="")

    assert _links(comment) == []
    assert comment.blocks[-1] == Marker("posted")


@pytest.mark.asyncio
async def test_each_opening_is_announced_once(tmp_path: Path) -> None:
    """Ensure one comment per gate opening, however many passes look."""
    stack = build_stack(tmp_path)
    open_gate(stack, CardKind.PRD_GATE, None, "approve_prd")

    await stack.service.announce(WORKFLOW_ID)
    await stack.service.announce(WORKFLOW_ID)
    await asyncio.gather(
        stack.service.announce(WORKFLOW_ID),
        stack.service.announce(WORKFLOW_ID),
    )

    assert len(stack.source.comments()) == 1
    assert len(stack.source.read_refs) == 1


@pytest.mark.asyncio
async def test_a_gate_answered_before_the_pass_is_not_announced(
    tmp_path: Path,
) -> None:
    """Ensure nobody is asked for a decision that was already taken."""
    stack = build_stack(tmp_path)
    gate = open_gate(stack, CardKind.PRD_GATE, None, "approve_prd")
    stack.store.set_card_state(gate.id, "done")

    assert await _announced(stack) == []


@pytest.mark.asyncio
async def test_the_board_hook_schedules_a_pass(tmp_path: Path) -> None:
    """Ensure the hook BoardService calls leads to the comment."""
    stack = build_stack(tmp_path)
    open_gate(stack, CardKind.PRD_GATE, None, "approve_prd")

    stack.service.schedule(WORKFLOW_ID)
    await asyncio.gather(*stack.service._running)

    assert len(stack.source.comments()) == 1


def test_announcing_outside_an_event_loop_does_nothing(
    tmp_path: Path,
) -> None:
    """Ensure the hook is safe where no loop runs (synchronous callers)."""
    stack = build_stack(tmp_path)

    stack.service.schedule(WORKFLOW_ID)

    assert stack.source.comments() == []


def test_builders_leave_the_ownership_marker_to_the_adapter() -> None:
    """Ensure no builder adds the marker itself: the adapter does, as the
    ticket's own platform shows it."""
    ctx = Context(WORKFLOW_ID, People(REPORTER, CHANGE_OWNER), BASE_URL)
    built = [
        words.understanding(ctx, document(paragraph(Text("x")))),
        words.strategic_interview(ctx, 1),
        words.cab_summary(ctx, document(paragraph(Text("x")))),
        status_words.delivered(ctx, "https://x.example/1"),
        status_words.ci_repaired(ctx),
    ]
    assert all(doc.markers() == frozenset() for doc in built)


def test_nothing_ever_asks_the_ticket_to_change_status(
    tmp_path: Path,
) -> None:
    """Ensure announcing only ever comments."""
    stack = build_stack(tmp_path)
    open_gate(stack, CardKind.CAB1_GATE, None, "approve_strategic_fit")

    asyncio.run(stack.service.announce(WORKFLOW_ID))

    assert stack.source.transitions == []
