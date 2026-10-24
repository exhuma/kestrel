"""A question with a closed set of answers is asked as a choice (feature
045).

An interviewer may still draft "X or Y?" as free text. The question
review, which sees every new question before any human does, may give
such an open question its options — never changing its wording. Code
enforces that: an attachment to anything but a kept, open new question,
or with options 034 would reject, makes the whole review unusable, so
every question is then asked as drafted.
"""
from __future__ import annotations

import json

from app.services.board.questions import (
    Question,
    QuestionError,
    is_open,
    normalise_questions,
)
from app.text_extract import extract_tag

#: What the review card adds to its instructions about options.
CHOICE_INSTRUCTIONS = """\
A question marked (open) is answered in free text. When its answers form
a clear closed set — it names its own alternatives ("X or Y?"), can be
answered yes or no, or picks from a known set — give it 2 to 8 short,
distinct options under "options", with "multiple": true when several may
apply. Never change its wording, and never give options to a question you
drop or one marked (choice)."""


def parse_choices(
    text: str, tag: str, questions: dict[str, Question], dropped: set[str]
) -> dict[str, Question] | None:
    """``{question id: its choice form}`` from the review's ``options``
    list (``{}`` when it has none), or ``None`` when an entry breaks a
    rule. *questions* are the new questions by id."""
    try:
        entries = json.loads(extract_tag(text, tag) or "").get("options", [])
    except (ValueError, AttributeError):
        return None
    if not isinstance(entries, list):
        return None
    choices: dict[str, Question] = {}
    for entry in entries:
        found = _choice(entry, questions)
        if found is None or found[0] in choices or found[0] in dropped:
            return None
        choices[found[0]] = found[1]
    return choices


def _choice(
    entry: object, questions: dict[str, Question]
) -> tuple[str, Question] | None:
    """One entry as (question id, choice form), keeping the drafted
    prompt; ``None`` unless it targets an open question validly."""
    if not isinstance(entry, dict):
        return None
    qid = entry.get("question")
    if not isinstance(qid, str) or not is_open(questions.get(qid)):
        return None
    try:
        (choice,) = normalise_questions([{**entry, "prompt": questions[qid]}])
    except QuestionError:
        return None
    return qid, choice


def converted(
    persona: str, questions: list[Question], choices: dict[str, Question]
) -> list[dict[str, object]]:
    """What the review turned into a choice in *persona*'s set."""
    return [
        {"persona": persona, **choice}
        for index, _question in enumerate(questions, 1)
        if (choice := choices.get(f"{persona}-{index}")) is not None
    ]
