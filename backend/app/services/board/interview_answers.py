"""Whether an interview answer responds to every question (feature 037).

A human interview never assumes: its gate waits until the operator has
responded to every question — with an answer, "I don't know", or "not
relevant", each an explicit choice. The interview page already refuses
to submit before that; this makes the backend refuse too (constitution
Principle II), so no path can record a question as answered by nobody.

The answer is the ``Q:``/``A:`` text the interview page writes
(``frontend/src/lib/interviewAnswers.ts``): one block per question, in
order, separated by a blank line.
"""
from __future__ import annotations

import json
from typing import Protocol

from app.models_board import CardState, WorkCard
from app.models_board_records import HumanGateRecord


class _ReadsArtifacts(Protocol):
    def read_content(self, artifact_id: str) -> str | None: ...

#: What the page writes for a question left without a response.
UNANSWERED = "(No answer was given.)"


class GateNotOpenError(Exception):
    """Raised when a gate was already decided, or is no longer waiting."""


class IncompleteAnswerError(Exception):
    """Raised when an interview answer leaves questions unanswered.

    :param missing: The prompts with no response.
    """

    def __init__(self, missing: list[str]) -> None:
        super().__init__(
            f"{len(missing)} question(s) have no response: "
            + "; ".join(missing)
        )
        self.missing = missing


def check_open(
    record: HumanGateRecord,
    card: WorkCard | None,
    artifacts: _ReadsArtifacts,
    decision: str,
    answer: str | None,
) -> None:
    """A gate is decided once, while it waits; an interview only with a
    response to every question.

    :raises GateNotOpenError: If the gate is decided or no longer waits.
    :raises IncompleteAnswerError: If an approved interview answer leaves
        a question without a response.
    """
    waiting = card is not None and card.state == CardState.AWAITING_HUMAN
    if record.decision is not None or not waiting:
        raise GateNotOpenError(f"gate {record.card_id} is not open")
    if record.requested_decision != "answer" or decision != "approved":
        return
    questions = (
        artifacts.read_content(record.target_artifact_id)
        if record.target_artifact_id else None
    )
    missing = missing_answers(questions, answer)
    if missing:
        raise IncompleteAnswerError(missing)


def missing_answers(question_set: str | None, answer: str | None) -> list[str]:
    """The prompts in *question_set* that *answer* leaves without a
    response. Empty when every question has one — or when the question
    set cannot be read, since there is then nothing to check against."""
    prompts = _prompts(question_set)
    text = answer or ""
    return [
        prompt
        for index, prompt in enumerate(prompts)
        if _response(text, prompt, _next(prompts, index)) in ("", UNANSWERED)
    ]


def _prompts(question_set: str | None) -> list[str]:
    try:
        questions = json.loads(question_set or "").get("questions")
    except (ValueError, AttributeError):
        return []
    if not isinstance(questions, list):
        return []
    return [p for p in map(_prompt, questions) if p]


def _prompt(question: object) -> str | None:
    if isinstance(question, dict):
        question = question.get("prompt")
    return question if isinstance(question, str) else None


def _next(prompts: list[str], index: int) -> str | None:
    return prompts[index + 1] if index + 1 < len(prompts) else None


def _response(text: str, prompt: str, next_prompt: str | None) -> str:
    """The trimmed response to *prompt*, or '' when it is absent."""
    marker = f"Q: {prompt}\nA: "
    start = text.find(marker)
    if start == -1:
        return ""
    start += len(marker)
    end = -1
    if next_prompt is not None:
        end = text.find(f"\n\nQ: {next_prompt}\nA: ", start)
    return text[start:end if end != -1 else len(text)].strip()


def answer_to(text: str, prompt: str) -> str:
    """The trimmed response to *prompt* in an answered interview's text,
    whatever question follows it; '' when it is absent."""
    marker = f"Q: {prompt}\nA: "
    start = text.find(marker)
    if start == -1:
        return ""
    start += len(marker)
    end = text.find("\n\nQ: ", start)
    return text[start:end if end != -1 else len(text)].strip()
