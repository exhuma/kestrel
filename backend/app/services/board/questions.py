"""Interview questions: open, or with options to pick from (feature 034).

An interview answered only in free text is slow to answer. A persona
therefore offers options wherever a question has a clear set of answers,
and keeps plain text for open questions. A question is either a plain
string (open) or ``{"prompt": str, "options": [str, …], "multiple":
bool}`` with 2–8 distinct options. Anything else is malformed, and fails
closed like any other unreadable interview.
"""
from __future__ import annotations

import re

from app.models_board import CardKind

MIN_OPTIONS = 2
MAX_OPTIONS = 8

#: One question as stored: an open prompt, or a choice question.
Question = str | dict[str, object]


class QuestionError(ValueError):
    """Raised for a question that is neither open nor a valid choice."""


#: Words only kestrel's own instructions use: card kinds (with an
#: underscore, so plain words like "design" stay askable) and the reply
#: tag. A question naming one is talking about the system, not to the
#: human, and fails closed so the round is retried.
_INTERNAL = re.compile(
    "|".join(
        sorted(re.escape(k.value) for k in CardKind if "_" in k.value)
        + ["REFINEMENT_QUESTIONS"]
    )
)


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
        return _for_the_human(entry)
    if not isinstance(entry, dict):
        raise QuestionError("a question must be a string or an object")
    prompt = entry.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise QuestionError("a choice question needs a prompt")
    _for_the_human(prompt)
    return {
        "prompt": prompt,
        "options": _options(entry.get("options")),
        "multiple": entry.get("multiple", False) is True,
    }


def _for_the_human(prompt: str) -> str:
    found = _INTERNAL.search(prompt)
    if found is not None:
        raise QuestionError(
            f"a question must be addressed to the human, not mention "
            f"{found.group()!r}"
        )
    return prompt


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


def is_open(question: object) -> bool:
    """Whether *question* is asked in free text (feature 045)."""
    return isinstance(question, str)


def prompt_of(question: object) -> str | None:
    """A question's prompt, or ``None`` for something that is not one."""
    if isinstance(question, dict):
        question = question.get("prompt")
    return question if isinstance(question, str) else None


#: How every interviewer answers (feature 038): one block, in this shape.
#: Given by the card, not by each specialist's prompt, so every
#: specialist the coordinator brings in asks the same way.
QUESTION_FORMAT = """\
Answer with a single block:
<REFINEMENT_QUESTIONS>{"questions": [...], "satisfied": false}
</REFINEMENT_QUESTIONS>
Each question is either a plain string, for an open question, or
`{"prompt": "...", "options": ["...", "..."], "multiple": false}` when it
has a clear set of answers: 2 to 8 short, distinct options, with
`"multiple": true` when several may apply.
A question MUST have options when it names its own alternatives ("X or
Y?"), can be answered yes or no, or picks from a known set. Use a plain
string only when the answer is genuinely open: a name, a number, a
description, a reason. These examples show the format only; your own
questions are about this request:
- `{"prompt": "Will it need server-side storage or be ephemeral?",
  "options": ["Server-side storage", "Ephemeral"], "multiple": false}`
- `{"prompt": "Which formats must the export support?",
  "options": ["CSV", "Excel", "PDF"], "multiple": true}`
- `"What should the exported file be called?"`
The human can always add a comment, so do not add an "Other" option. Set
`"satisfied": true` with an empty list only when you need nothing more
from this human."""

#: Every question reaches its human exactly as drafted.
_WORD_FOR_WORD = """\
Each question is shown to that human word for word: address them, never
this system, and never mention cards, card kinds or these instructions."""

#: What an interviewer is doing, whoever it is (feature 038).
INTERVIEWER_BRIEF = """\
You are preparing interview questions for the human who holds your role
on this request. Ask only what that human can answer from your area of
expertise, and only what you need to know: the coordinator chose you
because this request touches your area. Other specialists interview their
own humans; the coordinator removes questions asked twice. Never replace a
question with an assumption — ask it.
""" + _WORD_FOR_WORD

#: What the strategic-fit interviewer is doing (feature 027); until now
#: the only interview card without a brief of its own.
STRATEGIC_BRIEF = """\
You are preparing strategic-fit questions for the human who asked for this
request. A decision-maker reads the answers to judge whether the request
is worth doing at all, before any requirements work.
""" + _WORD_FOR_WORD
