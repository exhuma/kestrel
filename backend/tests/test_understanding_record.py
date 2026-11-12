"""The understanding the reporter confirmed is a record: attached to the
ticket, and what every later step works from."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.documents import Text, document, paragraph
from app.models_board import CardKind, WorkCard
from app.services.board import bootstrap
from app.services.board.dispatch import (
    build_card_envelope,
    build_coordinator_envelope,
)
from app.services.board.reply_rules import _DECISIONS
from app.services.board.understanding import (
    RESTATEMENT_LOGICAL_NAME,
    confirmed_understanding,
    understanding_context,
)
from tests.announcement_support import WORKFLOW_ID, build_stack
from tests.interview_support import specialist

pytestmark = pytest.mark.integration


def _draft(stack, card_id: str, text: str) -> WorkCard:
    """An understanding card with its restatement, and its gate."""
    card = WorkCard(
        id=card_id, workflow_id=WORKFLOW_ID, kind="understanding",
        title="Restate", state="done", eligible_roles=("pm",),
    )
    stack.store.create_card(card)
    artifact = stack.artifacts.store_document(
        card_id, RESTATEMENT_LOGICAL_NAME, 1, document(paragraph(Text(text)))
    )
    return stack.gates.create_gate(
        WORKFLOW_ID, kind=CardKind.UNDERSTANDING_GATE.value,
        title="Confirm understanding",
        requested_decision="confirm_understanding",
        target_artifact_id=artifact.id,
    )


def test_nothing_is_confirmed_before_the_reporter_confirms(
    tmp_path: Path,
) -> None:
    """Ensure an open restatement is not treated as the request."""
    stack = build_stack(tmp_path)
    _draft(stack, "u1", "First take.")

    assert confirmed_understanding(
        WORKFLOW_ID, stack.store, stack.artifacts
    ) == ""


def test_the_confirmed_restatement_is_the_latest_draft(
    tmp_path: Path,
) -> None:
    """Ensure the redraft the reporter confirmed is what later steps get,
    and the redraft before it saw the reporter's whole answer."""
    stack = build_stack(tmp_path)
    first = _draft(stack, "u1", "First take, with three questions.")
    stack.gates.resolve(
        first.id, "rejected", answer="It is for the EU team. I don't know "
        "the deadline.",
    )
    redraft = WorkCard(
        id="u2", workflow_id=WORKFLOW_ID, kind="understanding",
        title="Redraft", state="ready", eligible_roles=("pm",),
    )
    stack.store.create_card(redraft)

    context = understanding_context(redraft, stack.store, stack.artifacts)
    assert "The reporter's answer:\nIt is for the EU team." in context
    assert "Do not ask any of those points again." in context

    stack.store.set_card_state("u2", "done")
    second = stack.gates.create_gate(
        WORKFLOW_ID, kind=CardKind.UNDERSTANDING_GATE.value,
        title="Confirm understanding",
        requested_decision="confirm_understanding",
        target_artifact_id=stack.artifacts.store_document(
            "u2", RESTATEMENT_LOGICAL_NAME, 1,
            document(paragraph(Text("For the EU team; deadline unknown."))),
        ).id,
    )
    stack.gates.resolve(second.id, "approved")

    assert confirmed_understanding(
        WORKFLOW_ID, stack.store, stack.artifacts
    ) == "For the EU team; deadline unknown."


def test_later_prompts_lead_with_the_confirmed_request(
    tmp_path: Path,
) -> None:
    """Ensure work is based on the confirmed text, with the ticket as
    written kept below for reference."""
    stack = build_stack(tmp_path)
    workflow = stack.store.get_workflow(WORKFLOW_ID)
    card = WorkCard(
        id="r1", workflow_id=WORKFLOW_ID, kind="refinement", title="Ask",
        state="ready",
    )

    envelope = build_card_envelope(
        specialist("dba", "refinement"), workflow, card,
        understanding="For the EU team.",
    )
    coordinator = build_coordinator_envelope(
        specialist("coordinator"), workflow, [card],
        understanding="For the EU team.",
    )

    for prompt in (envelope, coordinator):
        confirmed = prompt.index("as the reporter confirmed it")
        assert confirmed < prompt.index("The ticket as written")
        assert "For the EU team." in prompt


@pytest.mark.asyncio
async def test_a_confirmed_understanding_is_attached_to_the_ticket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure the restatement becomes a file on the ticket, numbered when
    confirmed again."""
    stack = build_stack(tmp_path)
    gate = _draft(stack, "u1", "For the EU team.")
    stack.gates.resolve(gate.id, "approved")
    for name, value in (
        ("get_board_store", stack.store), ("get_gates_service", stack.gates),
        ("get_artifacts_service", stack.artifacts),
        ("get_announcement_service", stack.service),
    ):
        monkeypatch.setattr(bootstrap, name, lambda value=value: value)

    await bootstrap._project_attachment(WORKFLOW_ID, gate)

    ((_ref, file_name, attached),) = stack.source.files
    assert file_name == "Understanding.md"
    assert attached.plain_text() == "For the EU team."


def test_the_reply_reader_counts_answers_as_a_correction() -> None:
    """Ensure answering the restatement's questions, even with "I don't
    know", is read as a correction, not as unclear."""
    _words, asked = _DECISIONS["confirm_understanding"]

    assert "I don't know" in asked
    assert "is a correction (a rejection)" in asked
