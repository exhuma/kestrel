"""Interview questions: open, or with options to pick from (feature 034).

An interview answered only in free text is slow to answer. A persona
therefore offers options wherever a question has a clear set of answers,
and keeps plain text for open questions. A question is either a plain
string (open) or ``{"prompt": str, "options": [str, …], "multiple":
bool}`` with 2–8 distinct options. Anything else is malformed, and fails
closed like any other unreadable interview.
"""
from __future__ import annotations

MIN_OPTIONS = 2
MAX_OPTIONS = 8

#: One question as stored: an open prompt, or a choice question.
Question = str | dict[str, object]


class QuestionError(ValueError):
    """Raised for a question that is neither open nor a valid choice."""


def normalise_questions(raw: object) -> list[Question]:
    """Validate *raw* as a question list, returning it normalised.

    :raises QuestionError: On any malformed entry.
    """
    if not isinstance(raw, list):
        raise QuestionError("questions must be a list")
    return [_normalise(entry) for entry in raw]


def _normalise(entry: object) -> Question:
    if isinstance(entry, str):
        if not entry.strip():
            raise QuestionError("a question must not be empty")
        return entry
    if not isinstance(entry, dict):
        raise QuestionError("a question must be a string or an object")
    prompt = entry.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise QuestionError("a choice question needs a prompt")
    return {
        "prompt": prompt,
        "options": _options(entry.get("options")),
        "multiple": entry.get("multiple", False) is True,
    }


def _options(raw: object) -> list[str]:
    if not isinstance(raw, list) or not all(
        isinstance(o, str) and o.strip() for o in raw
    ):
        raise QuestionError("options must be non-empty strings")
    if len(set(raw)) != len(raw):
        raise QuestionError("options must be distinct")
    if not MIN_OPTIONS <= len(raw) <= MAX_OPTIONS:
        raise QuestionError(
            f"a choice question needs {MIN_OPTIONS}-{MAX_OPTIONS} options"
        )
    return list(raw)
