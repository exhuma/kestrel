"""Tests for the questionnaire schema, validation, formatting."""
from __future__ import annotations

import pytest

from app.questionnaire import (
    AnswerValidationError,
    InterviewEnvelope,
    Question,
    QuestionOption,
    Questionnaire,
    all_required_answered,
    build_envelope,
    format_answers,
    parse_envelope,
    render_assumptions_and_risks,
    to_entries,
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


_WAIVER = {"waived": True, "reason": "Risk accepted by owner"}


def test_waiver_requires_a_reason() -> None:
    """Ensure a waiver without a reason is rejected."""
    with pytest.raises(AnswerValidationError) as exc:
        validate_answers(_questionnaire(), {"q1": {"waived": True}})
    assert "q1" in exc.value.errors


def test_waiver_with_reason_is_accepted() -> None:
    """Ensure a required question may be waived with a reason."""
    validate_answers(_questionnaire(), {"q1": _WAIVER})


def test_partial_tolerates_missing_required() -> None:
    """Ensure a draft save does not require the missing required answer."""
    validate_answers(_questionnaire(), {}, partial=True)
    with pytest.raises(AnswerValidationError):
        validate_answers(_questionnaire(), {})  # finalize still requires it


def test_completeness_counts_waivers_as_answered() -> None:
    """Ensure a waived (with reason) required question counts as answered."""
    assert all_required_answered(_questionnaire(), {}) is False
    assert all_required_answered(_questionnaire(), {"q1": _WAIVER}) is True
    assert (
        all_required_answered(_questionnaire(), {"q1": {"waived": True}})
        is False
    )


def test_render_assumptions_and_risks_lists_waivers() -> None:
    """Ensure every waived answer appears in the risk section."""
    entries = to_entries(_questionnaire(), {"q1": _WAIVER, "q2": "text"})
    section = render_assumptions_and_risks(entries)
    assert "Assumptions & accepted risks" in section
    assert "Which auth flow?" in section
    assert "Risk accepted by owner" in section
    # A concretely answered question is not a risk.
    assert "Anything else?" not in section


def test_render_assumptions_and_risks_empty_when_none_waived() -> None:
    """Ensure no section is emitted when nothing was waived."""
    entries = to_entries(_questionnaire(), {"q1": "oidc"})
    assert render_assumptions_and_risks(entries) == ""


def test_to_entries_carries_audience_and_waiver() -> None:
    """Ensure accumulated entries carry audience and waiver detail."""
    q = Questionnaire(
        questions=[
            Question(id="s1", prompt="Encrypt at rest?", type="boolean",
                     audience="infosec"),
        ]
    )
    entry = to_entries(q, {"s1": _WAIVER})[0]
    assert entry.audience == "infosec"
    assert entry.waived is True
    assert entry.reason == "Risk accepted by owner"


def test_envelope_round_trips() -> None:
    """Ensure an interview envelope survives serialisation."""
    env = InterviewEnvelope(
        questionnaire=_questionnaire(),
        draft_answers={"q1": "oidc"},
        issue="Original issue text",
    )
    restored = parse_envelope(build_envelope(env))
    assert restored is not None
    assert restored.draft_answers == {"q1": "oidc"}
    assert restored.issue == "Original issue text"


def test_parse_envelope_rejects_non_envelope() -> None:
    """Ensure a bare questionnaire is not mistaken for an envelope."""
    assert parse_envelope('{"questions": []}') is None
    assert parse_envelope("not json") is None
