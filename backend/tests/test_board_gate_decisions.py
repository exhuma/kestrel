"""What the ticket says when a gate is decided in kestrel (feature 046,
T048, added after the maintainer's review).

A decision gate reads as one plain sentence per kind and outcome; an
answer gate (an interview) says nothing, because the next announcement is
its acknowledgement. The ticket is only ever commented on.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.models_board import CardKind
from app.services.board.announcements.decisions import (
    ANSWER_GATES,
    decision_sentence,
)
from tests.announcement_support import (
    BASE_URL,
    WORKFLOW_ID,
    build_stack,
    open_gate,
)

_PAGE = f"{BASE_URL}/#/requests/{WORKFLOW_ID}"

_SENTENCES = [
    (CardKind.UNDERSTANDING_GATE, "approved", "Understanding confirmed."),
    (
        CardKind.UNDERSTANDING_GATE, "rejected",
        "Understanding corrected, kestrel is rewriting it.",
    ),
    (CardKind.CAB1_GATE, "approved", "CAB approved the strategic fit."),
    (
        CardKind.CAB1_GATE, "rejected",
        "CAB declined the strategic fit; this request stops here.",
    ),
    (CardKind.PRD_GATE, "approved", "PRD signed off."),
    (
        CardKind.PRD_GATE, "rejected",
        "PRD sent back with feedback, kestrel is revising it.",
    ),
    (
        CardKind.DECOMPOSITION_GATE, "approved",
        "CAB approved the plan; work starts.",
    ),
    (CardKind.DECOMPOSITION_GATE, "rejected", "CAB declined the plan."),
]


@pytest.mark.parametrize("kind, decision, sentence", _SENTENCES)
@pytest.mark.asyncio
async def test_a_decision_gate_reads_as_one_plain_sentence(
    tmp_path: Path, kind: CardKind, decision: str, sentence: str
) -> None:
    """Ensure each gate kind and outcome has its own sentence, then the
    kestrel link, and no title or "Gate approved" prefix."""
    stack = build_stack(tmp_path)
    gate = open_gate(stack, kind, None, "decide")

    await stack.service.gate_decided(WORKFLOW_ID, gate, decision)

    (comment,) = stack.source.comments()
    assert comment.plain_text().startswith(sentence)
    assert comment.blocks[0].content[0].value == sentence
    assert comment.blocks[-2].content[0].href == _PAGE
    assert "Gate" not in comment.plain_text()


@pytest.mark.parametrize("kind", [
    CardKind.STRATEGIC_INTERVIEW_GATE, CardKind.REFINEMENT_GATE,
])
@pytest.mark.parametrize("decision", ["approved", "rejected"])
@pytest.mark.asyncio
async def test_an_answer_gate_says_nothing_when_resolved(
    tmp_path: Path, kind: CardKind, decision: str
) -> None:
    """Ensure submitting interview answers posts no comment."""
    stack = build_stack(tmp_path)
    gate = open_gate(stack, kind, None, "answer")

    await stack.service.gate_decided(WORKFLOW_ID, gate, decision)

    assert stack.source.comments() == []
    assert not stack.projections.recorded(f"gate:{gate.id}")


def test_the_answer_gates_are_the_two_interviews() -> None:
    """Ensure no decision gate is silenced by accident."""
    assert {
        CardKind.STRATEGIC_INTERVIEW_GATE.value,
        CardKind.REFINEMENT_GATE.value,
    } == ANSWER_GATES


def test_another_gate_kind_keeps_a_neutral_line() -> None:
    """Ensure a kind without wording still says what was decided."""
    assert decision_sentence("something_gate", True, "A thing") == (
        "Gate approved: A thing"
    )
    assert decision_sentence("something_gate", False, "A thing") == (
        "Gate rejected: A thing"
    )
