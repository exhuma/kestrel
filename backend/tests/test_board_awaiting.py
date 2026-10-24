"""Who a card waits on, and for what (feature 035)."""
from __future__ import annotations

import pytest

from app.models_board import WorkCard
from app.services.board.awaiting import Awaiting, awaiting_all, awaiting_of


def _card(kind: str, state: str = "awaiting_human") -> WorkCard:
    return WorkCard(
        id=kind, workflow_id="wf-1", kind=kind, title=kind, state=state,
        eligible_roles=(),
    )


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("understanding_gate", ("requester", "confirm_understanding")),
        ("strategic_interview_gate", ("requester", "answer")),
        ("cab1_gate", ("cab", "approve_strategic_fit")),
        ("refinement_gate", ("requester", "answer")),
        ("prd_gate", ("requester", "approve_prd")),
        ("decomposition_gate", ("cab", "approve_decomposition")),
        ("manual_task", ("you", "do_task")),
        ("coordinator_review", ("operator", "review")),
    ],
)
def test_a_waiting_card_names_who_acts(
    kind: str, expected: tuple[str, str]
) -> None:
    assert awaiting_of(_card(kind)) == Awaiting(*expected)


def test_quarantine_and_failure_are_the_operators() -> None:
    """Ensure the state decides, whatever the card's kind."""
    assert awaiting_of(_card("security_review", "quarantined")) == Awaiting(
        "operator", "review_input"
    )
    assert awaiting_of(_card("implementation", "failed")) == Awaiting(
        "operator", "retry_or_cancel"
    )


@pytest.mark.parametrize(
    "state", ["ready", "claimed", "waiting_dependency", "done", "cancelled"]
)
def test_a_card_not_held_for_a_human_waits_on_nobody(state: str) -> None:
    assert awaiting_of(_card("cab1_gate", state)) is None


def test_the_answered_interview_gives_way_to_the_cab() -> None:
    """Ensure consecutive decisions read differently (SC-002)."""
    before = awaiting_all([
        _card("strategic_interview_gate"),
        _card("cab1_gate", "waiting_dependency"),
    ])
    after = awaiting_all([
        _card("strategic_interview_gate", "done"), _card("cab1_gate"),
    ])

    assert before == [Awaiting("requester", "answer")]
    assert after == [Awaiting("cab", "approve_strategic_fit")]
