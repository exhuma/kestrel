"""Structured clarification questionnaires: schema, validation,
and deterministic answer formatting.

Kept LLM-free by design (spec: "deterministic first") — the model
only ever produces the JSON text; every check and every rendering
decision here is plain code.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, ValidationError

QuestionType = Literal[
    "single_select", "multi_select", "boolean", "free_text"
]


class QuestionOption(BaseModel):
    """One selectable option for a select-type question."""

    value: str
    label: str


class Question(BaseModel):
    """One question in a clarification questionnaire."""

    id: str
    prompt: str
    why: str = ""
    type: QuestionType
    required: bool = True
    options: list[QuestionOption] = Field(default_factory=list)


class Questionnaire(BaseModel):
    """A set of clarifying questions asked in one interview round."""

    questions: list[Question]


def parse_questionnaire_json(text: str) -> Questionnaire | None:
    """
    Parse bare questionnaire JSON (no surrounding tag).

    :param text: Raw JSON text, e.g. a step's stored deliverable.
    :returns: The parsed questionnaire, or None if it isn't valid
        JSON matching the schema.
    """
    try:
        return Questionnaire.model_validate_json(text)
    except (ValueError, ValidationError):
        return None


class AnswerValidationError(Exception):
    """Raised when a submitted answer set fails validation."""

    def __init__(self, errors: dict[str, str]) -> None:
        self.errors = errors
        super().__init__(f"invalid answers: {errors}")


def _is_missing(value: object) -> bool:
    return value is None or value == "" or value == []


def validate_answers(
    questionnaire: Questionnaire, answers: dict[str, object]
) -> None:
    """
    Validate a submitted answer set against its questionnaire.

    :param questionnaire: The questionnaire being answered.
    :param answers: Question id -> submitted value.
    :raises AnswerValidationError: If any answer is invalid,
        with one message per offending question id.
    """
    errors: dict[str, str] = {}
    by_id = {q.id: q for q in questionnaire.questions}
    for qid in answers:
        if qid not in by_id:
            errors[qid] = "unknown question id"
    for question in questionnaire.questions:
        value = answers.get(question.id)
        if question.required and _is_missing(value):
            errors[question.id] = "answer required"
            continue
        if value is None:
            continue
        if question.type == "single_select":
            valid = {o.value for o in question.options}
            if value not in valid:
                errors[question.id] = (
                    f"must be one of {sorted(valid)}"
                )
        elif question.type == "multi_select":
            valid = {o.value for o in question.options}
            if not isinstance(value, list) or not all(
                v in valid for v in value
            ):
                errors[question.id] = (
                    f"must be a subset of {sorted(valid)}"
                )
        elif question.type == "boolean":
            if not isinstance(value, bool):
                errors[question.id] = "must be true or false"
    if errors:
        raise AnswerValidationError(errors)


def format_answers(
    questionnaire: Questionnaire, answers: dict[str, object]
) -> str:
    """
    Render a validated answer set as a deterministic prompt.

    :param questionnaire: The questionnaire that was answered.
    :param answers: Question id -> submitted value.
    :returns: Human-readable text to resume the claude session
        with, one line per question.
    """
    lines = ["ANSWERS:"]
    for question in questionnaire.questions:
        value = answers.get(question.id)
        if _is_missing(value):
            lines.append(f"- {question.prompt}: (no answer)")
            continue
        if question.type == "boolean":
            rendered = "Yes" if value else "No"
        elif question.type == "single_select":
            labels = {o.value: o.label for o in question.options}
            rendered = labels.get(str(value), str(value))
        elif question.type == "multi_select":
            labels = {o.value: o.label for o in question.options}
            rendered = ", ".join(
                labels.get(str(v), str(v)) for v in value  # type: ignore[union-attr]
            )
        else:
            rendered = str(value)
        lines.append(f"- {question.prompt}: {rendered}")
    return "\n".join(lines)
