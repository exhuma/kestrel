"""Human-gate decisions and structured interview-reply plumbing."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable

from app.models_workflow import Step, WorkflowRun, WorkflowStep
from app.questionnaire import (
    InterviewEnvelope,
    build_envelope,
    format_answers,
    parse_envelope,
    parse_questionnaire_json,
    validate_answers,
)
from app.services.exceptions import InvalidWorkflowStateError


@dataclass
class _Control:
    """Async coordination for one run (kept off the serialisable model).

    Always build via :func:`new_control` so the future binds to the
    running loop — never rely on defaults here.
    """

    gate: asyncio.Future
    replies: asyncio.Queue


@dataclass
class _Decision:
    approved: bool
    deliverable: str | None = None
    refinement: str | None = None


def new_control() -> _Control:
    loop = asyncio.get_running_loop()
    return _Control(gate=loop.create_future(), replies=asyncio.Queue())


async def await_gate(control: _Control) -> _Decision:
    decision = await control.gate
    control.gate = asyncio.get_running_loop().create_future()
    return decision


def awaiting_input_step(run: WorkflowRun) -> WorkflowStep:
    """
    Return whichever step is currently awaiting a reply.

    :param run: The run to search.
    :returns: The step with status "awaiting_input".
    :raises InvalidWorkflowStateError: If no step is awaiting
        input.
    """
    for step in run.steps:
        if step.status == "awaiting_input":
            return step
    raise InvalidWorkflowStateError("not awaiting a reply")


def reply(run: WorkflowRun, control: _Control, text: str) -> None:
    step = awaiting_input_step(run)
    if step.name == Step.REFINE:
        # The refine interview is always structured now; only the
        # implement blocker still accepts a free-text reply.
        raise InvalidWorkflowStateError(
            "this interview expects structured answers; use /answers"
        )
    control.replies.put_nowait(text)


def interview_state(
    run: WorkflowRun,
) -> tuple[WorkflowRun, WorkflowStep, InterviewEnvelope]:
    """Return the run/step/envelope for a pending refine interview.

    :raises InvalidWorkflowStateError: If the refine step is not
        currently awaiting structured answers.
    """
    step = run.steps[0]
    if step.name != Step.REFINE or step.status != "awaiting_input":
        raise InvalidWorkflowStateError("not awaiting a refine reply")
    envelope = parse_envelope(step.deliverable or "")
    if envelope is None:
        raise InvalidWorkflowStateError("no pending questionnaire")
    return run, step, envelope


def save_draft(
    run: WorkflowRun,
    step: WorkflowStep,
    envelope: InterviewEnvelope,
    answers: dict[str, object],
    persist: Callable[[WorkflowRun], None],
) -> None:
    """
    Persist a partial answer set without finalizing the interview.

    Answers may be incomplete, so only well-formedness is checked —
    never completeness — and the agent is not resumed. The draft is
    stored in the interview envelope so it survives a reload.

    :param persist: The raw registry save (not the service's ``_save``,
        which would also re-run the notifier for a non-transition).
    :raises AnswerValidationError: If a provided answer is malformed.
    """
    validate_answers(envelope.questionnaire, answers, partial=True)
    envelope.draft_answers = answers
    step.deliverable = build_envelope(envelope)
    persist(run)


def submit_answers(
    control: _Control,
    step: WorkflowStep,
    answers: dict[str, object],
    *,
    partial: bool,
) -> None:
    """
    Answer whichever step's pending structured questionnaire.

    The refine interview carries a persisted envelope and is resumed
    with the raw answers (which its loop folds into the accumulated
    Q&A); the implement blocker uses the simpler bare questionnaire
    and is resumed with the formatted answer text ``reply`` uses.

    :raises InvalidWorkflowStateError: If the step has no pending
        questionnaire.
    :raises AnswerValidationError: If any answer is invalid.
    """
    if step.name == Step.REFINE:
        envelope = parse_envelope(step.deliverable or "")
        if envelope is None:
            raise InvalidWorkflowStateError("no pending questionnaire")
        validate_answers(envelope.questionnaire, answers, partial=partial)
        control.replies.put_nowait(answers)
        return
    questionnaire = parse_questionnaire_json(step.deliverable or "")
    if questionnaire is None:
        raise InvalidWorkflowStateError("no pending questionnaire")
    validate_answers(questionnaire, answers, partial=partial)
    prompt = format_answers(questionnaire, answers)
    control.replies.put_nowait(prompt)


def resolve(run: WorkflowRun, control: _Control, decision: _Decision) -> None:
    # Only an approval gate accepts approve/reject. Guarding on the
    # run's phase (not gate.done()) closes the window between gates
    # where a fresh, not-yet-awaited future would be pre-armed.
    if not run.status.endswith("_approval"):
        raise InvalidWorkflowStateError("no gate awaiting a decision")
    control.gate.set_result(decision)
