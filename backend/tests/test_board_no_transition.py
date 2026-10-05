"""kestrel never changes the status of an ingested ticket (feature 046,
T023; constitution, access model, fourth recorded constraint).

The responsible human is told in a comment instead. A request is carried
through every gate, a delivery, a CI failure and a failure outcome over a
ticket that records any status transition it is asked for: it must be
asked for none.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.models_board import CardKind, WorkCard
from tests.announcement_support import (
    WORKFLOW_ID,
    Stack,
    add_plan,
    build_stack,
    open_document_gate,
    open_gate,
    open_interview_gate,
)

_APP = Path(__file__).resolve().parent.parent / "app"
#: A task source being asked for a lifecycle transition, however it was
#: looked up.
_TRANSITION_ON_A_SOURCE = re.compile(
    r"(task_source|sources\[[^\]]*\]|sources\.get\([^)]*\)|_source)"
    r"\s*\.\s*transition\s*\("
)


async def _announced(stack: Stack) -> None:
    await stack.service.announce(WORKFLOW_ID)


@pytest.mark.asyncio
async def test_a_whole_request_never_transitions_the_ticket(
    tmp_path: Path,
) -> None:
    """Ensure every gate, notice and status line is a comment, never a
    status change."""
    stack = build_stack(tmp_path)
    understanding = open_document_gate(
        stack, CardKind.UNDERSTANDING_GATE, CardKind.UNDERSTANDING, "Restated."
    )
    await _announced(stack)
    stack.gates.resolve(understanding.id, "approved")
    open_interview_gate(stack, add_plan(stack), "dba", 1)
    await _announced(stack)
    open_document_gate(
        stack, CardKind.PRD_GATE, CardKind.PRD, "The requirements."
    )
    await _announced(stack)
    open_gate(stack, CardKind.CAB1_GATE, None, "approve_strategic_fit")
    open_gate(stack, CardKind.DECOMPOSITION_GATE, None, "approve")
    await _announced(stack)
    await stack.service.ci_changed(WORKFLOW_ID, "status:ci:c:1:failed", "x")
    await stack.service.escalated(WORKFLOW_ID, "escalation:c:1:0", "Unclear")
    await stack.service.delivered(WORKFLOW_ID, "card-d", "https://x.test/1")
    stack.store.create_card(WorkCard(
        id="card-f", workflow_id=WORKFLOW_ID,
        kind=CardKind.IMPLEMENTATION.value, title="Build", state="failed",
    ))
    await _announced(stack)

    assert len(stack.source.comments()) > 1
    assert stack.source.transitions == []


def test_no_board_code_asks_a_task_source_to_transition() -> None:
    """Ensure the call is not made anywhere a request's ticket could be
    reached from: the board, the routers, ingestion."""
    offenders = [
        str(path.relative_to(_APP))
        for folder in ("services/board", "routers")
        for path in (_APP / folder).rglob("*.py")
        if _TRANSITION_ON_A_SOURCE.search(path.read_text())
    ]
    ingestion = _APP / "services" / "ingestion.py"
    if _TRANSITION_ON_A_SOURCE.search(ingestion.read_text()):
        offenders.append("services/ingestion.py")

    assert offenders == []
