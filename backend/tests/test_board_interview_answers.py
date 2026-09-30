"""A human interview never assumes (feature 037)."""
from __future__ import annotations

import json

import pytest

from app.models_board import WorkCard
from app.models_board_records import HumanGateRecord
from app.services.board.interview_answers import (
    GateNotOpenError,
    IncompleteAnswerError,
    check_open,
    missing_answers,
)

_SET = json.dumps({"questions": [
    "Why now?",
    {"prompt": "Which formats?", "options": ["CSV", "PDF"], "multiple": True},
]})


class _Artifacts:
    def read_content(self, artifact_id: str) -> str | None:
        return _SET if artifact_id == "qs" else None


def _gate(decision: str | None = None, asks: str = "answer") -> HumanGateRecord:
    return HumanGateRecord(
        id="g", card_id="gate-1", requested_decision=asks,
        target_artifact_id="qs", decision=decision,
    )


def _card(state: str = "awaiting_human") -> WorkCard:
    return WorkCard(
        id="gate-1", workflow_id="wf-1", kind="refinement_gate",
        title="Interview", state=state, eligible_roles=(),
    )


def test_every_question_answered_is_complete() -> None:
    answer = "Q: Why now?\nA: Quarter close.\n\nQ: Which formats?\nA: CSV, PDF"

    assert missing_answers(_SET, answer) == []


_BOTH = ["Why now?", "Which formats?"]


@pytest.mark.parametrize(
    ("answer", "missing"),
    [
        ("Q: Why now?\nA: \n\nQ: Which formats?\nA: CSV", ["Why now?"]),
        (
            "Q: Why now?\nA: (No answer was given.)"
            "\n\nQ: Which formats?\nA: CSV",
            ["Why now?"],
        ),
        ("Q: Which formats?\nA: CSV", ["Why now?"]),
        ("Because.", _BOTH),
    ],
    ids=["blank", "no-answer-marker", "left-out", "free-text"],
)
def test_a_question_without_a_response_is_missing(
    answer: str, missing: list[str]
) -> None:
    assert missing_answers(_SET, answer) == missing


def test_explicit_dont_know_and_not_relevant_are_responses() -> None:
    """Ensure the operator's own choice to leave a point to the PRD is a
    response, not a gap."""
    answer = (
        "Q: Why now?\nA: (I don't know — let the PRD state an assumption.)"
        "\n\nQ: Which formats?\nA: (Not relevant.)"
    )

    assert missing_answers(_SET, answer) == []


def test_an_incomplete_interview_is_refused() -> None:
    with pytest.raises(IncompleteAnswerError) as refused:
        check_open(_gate(), _card(), _Artifacts(), "approved",
                   "Q: Which formats?\nA: CSV")

    assert refused.value.missing == ["Why now?"]


@pytest.mark.parametrize(
    ("record", "card"),
    [(_gate(decision="approved"), _card()), (_gate(), _card("done"))],
    ids=["decided", "no-longer-waiting"],
)
def test_a_gate_is_decided_once(
    record: HumanGateRecord, card: WorkCard
) -> None:
    with pytest.raises(GateNotOpenError):
        check_open(record, card, _Artifacts(), "approved", None)


def test_an_approval_gate_needs_no_answer() -> None:
    check_open(
        _gate(asks="approve_prd"), _card(), _Artifacts(), "approved", None
    )
