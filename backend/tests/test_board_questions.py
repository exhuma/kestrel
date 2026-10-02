"""Interview questions: open or multiple choice (feature 034)."""
from __future__ import annotations

import pytest

from app.services.board.questions import (
    QUESTION_FORMAT,
    QuestionError,
    normalise_questions,
)
from app.services.board.refinement import (
    RefinementResultError,
    parse_refinement_round,
)


def test_open_and_choice_questions_are_both_accepted() -> None:
    questions = normalise_questions([
        "Anything else we should know?",
        {"prompt": "Who uses it?", "options": ["Finance", "Sales"]},
        {"prompt": "Which formats?", "options": ["CSV", "XLSX", "PDF"],
         "multiple": True},
    ])

    assert questions == [
        "Anything else we should know?",
        {"prompt": "Who uses it?", "options": ["Finance", "Sales"],
         "multiple": False},
        {"prompt": "Which formats?", "options": ["CSV", "XLSX", "PDF"],
         "multiple": True},
    ]


@pytest.mark.parametrize(
    "entry",
    [
        {"prompt": "Pick", "options": ["Only one"]},
        {"prompt": "Pick", "options": ["A", "A"]},
        {"prompt": "Pick", "options": [str(i) for i in range(9)]},
        {"prompt": "", "options": ["A", "B"]},
        {"prompt": "Pick", "options": "A, B"},
        "   ",
        7,
    ],
    ids=["one-option", "duplicate", "too-many", "no-prompt", "not-a-list",
         "blank", "number"],
)
def test_a_malformed_question_is_rejected(entry: object) -> None:
    with pytest.raises(QuestionError):
        normalise_questions([entry])


def test_a_round_with_a_malformed_question_fails_closed() -> None:
    """Ensure the persona's round is escalated, not half-shown."""
    text = (
        '<REFINEMENT_QUESTIONS>{"questions": [{"prompt": "Pick", '
        '"options": ["A"]}]}</REFINEMENT_QUESTIONS>'
    )

    with pytest.raises(RefinementResultError, match="malformed question"):
        parse_refinement_round(text)


def test_every_interviewer_is_told_when_a_question_needs_options() -> None:
    """Feature 045: a closed question is drafted as a choice."""
    assert "MUST have options when it names its own alternatives" in (
        " ".join(QUESTION_FORMAT.split())
    )
    assert '"multiple": true}' in QUESTION_FORMAT
    assert '"multiple": false}' in QUESTION_FORMAT


@pytest.mark.parametrize(
    "entry",
    [
        "This is on a strategic_interview card -- what should I ask instead?",
        {"prompt": "Answer in REFINEMENT_QUESTIONS?", "options": ["A", "B"]},
    ],
    ids=["open", "choice"],
)
def test_a_question_about_the_system_fails_closed(entry: object) -> None:
    """Ensure internal instructions never reach the human as a question;
    the round is retried instead."""
    with pytest.raises(QuestionError, match="addressed to the human"):
        normalise_questions([entry])


def test_ordinary_words_that_are_card_kinds_stay_askable() -> None:
    assert normalise_questions(["Is there a design to follow?"]) == [
        "Is there a design to follow?"
    ]
