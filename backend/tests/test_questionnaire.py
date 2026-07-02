"""Tests for the questionnaire schema, validation, formatting."""
from __future__ import annotations

import pytest

from app.questionnaire import (
    AnswerValidationError,
    Question,
    QuestionOption,
    Questionnaire,
    format_answers,
    validate_answers,
)


def _questionnaire() -> Questionnaire:
    return Questionnaire(
        questions=[
            Question(
                id="q1",
                prompt="Which auth flow?",
                why="The issue says 'login' but not the mechanism.",
                type="single_select",
                required=True,
                options=[
                    QuestionOption(value="oidc", label="OIDC"),
                    QuestionOption(
                        value="local", label="Local password"
                    ),
                ],
            ),
            Question(
                id="q2",
                prompt="Anything else?",
                type="free_text",
                required=False,
            ),
        ]
    )


def test_validate_accepts_valid_answers() -> None:
    """Ensure a fully valid answer set raises nothing."""
    validate_answers(
        _questionnaire(), {"q1": "oidc", "q2": "no"}
    )


def test_validate_allows_optional_question_omitted() -> None:
    """Ensure an unanswered non-required question is fine."""
    validate_answers(_questionnaire(), {"q1": "oidc"})


def test_validate_rejects_missing_required() -> None:
    """Ensure a missing required answer is rejected."""
    with pytest.raises(AnswerValidationError) as exc:
        validate_answers(_questionnaire(), {})
    assert "q1" in exc.value.errors


def test_validate_rejects_unknown_option() -> None:
    """Ensure an option value outside the list is rejected."""
    with pytest.raises(AnswerValidationError) as exc:
        validate_answers(_questionnaire(), {"q1": "saml"})
    assert "q1" in exc.value.errors


def test_validate_rejects_unknown_question_id() -> None:
    """Ensure an answer to an unknown question id is rejected."""
    with pytest.raises(AnswerValidationError) as exc:
        validate_answers(
            _questionnaire(), {"q1": "oidc", "qX": "huh"}
        )
    assert "qX" in exc.value.errors


def test_validate_multi_select_and_boolean() -> None:
    """Ensure multi_select and boolean types validate correctly."""
    q = Questionnaire(
        questions=[
            Question(
                id="m", prompt="Which?", type="multi_select",
                options=[
                    QuestionOption(value="a", label="A"),
                    QuestionOption(value="b", label="B"),
                ],
            ),
            Question(id="b", prompt="Ship it?", type="boolean"),
        ]
    )
    validate_answers(q, {"m": ["a", "b"], "b": True})
    with pytest.raises(AnswerValidationError):
        validate_answers(q, {"m": ["a", "z"], "b": True})
    with pytest.raises(AnswerValidationError):
        validate_answers(q, {"m": ["a"], "b": "yes"})


def test_format_answers_renders_labels() -> None:
    """Ensure formatting resolves option values to labels."""
    text = format_answers(
        _questionnaire(), {"q1": "oidc", "q2": "Nothing else"}
    )
    assert "Which auth flow?" in text
    assert "OIDC" in text
    assert "Nothing else" in text
