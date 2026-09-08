"""The describe step: the understanding-checkpoint gate."""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.backends.base import TurnRequest
from app.models_workflow import Step, StepSession, WorkflowRun
from app.policy import get_policy
from app.services.time_tracking import set_clock
from app.services.workflow_text import extract_understanding
from app.services.workflows.prompts import (
    DESCRIBE_FEEDBACK_PROMPT,
    DESCRIBE_PROMPT,
    MID_RUN_FEEDBACK_APPENDIX,
)
from app.services.workflows.sessions import _bind
from app.services.workflows.shared import _now_utc, _Rejected

if TYPE_CHECKING:
    from app.services.workflows import WorkflowService


async def describe(
    service: "WorkflowService", run: WorkflowRun, body: str | None = None,
    feedback: str = "",
) -> None:
    """Drive the understanding-checkpoint gate to a confirmed restatement.

    Restates kestrel's read of the ingested task in plain language and
    parks for the requester to confirm or amend it — before any
    clarifying question is asked (FR-001/FR-002/FR-003). Structurally
    identical to :func:`refine`'s approve / reject-with-feedback /
    reject-without-feedback gate loop, minus the multi-round interview
    and the publish-to-ticket step (the restatement is never itself
    published — only used to confirm intent before refine begins).

    :param feedback: Ticket/triage feedback drained at the boundary just
        before this step started (feature 013, US2/US3) — folded into
        the prompt when present.
    """
    step = run.steps[0]
    step.model = get_policy().model_for(Step.DESCRIBE)
    if step.status != "awaiting_approval":
        await _run_turn(service, run, step, body, feedback)
    while True:
        decision = await service._await_gate(run.id)
        set_clock(run, "active", _now_utc())
        if decision.approved:
            step.deliverable = decision.deliverable or (
                step.deliverable or ""
            )
            step.status = "done"
            service._save(run)
            return
        if decision.refinement is None:
            raise _Rejected()
        await _run_feedback_turn(service, run, step, decision.refinement)


async def _run_turn(
    service: "WorkflowService",
    run: WorkflowRun,
    step,
    body: str | None,
    feedback: str,
) -> None:
    if body is None:
        body = (await service._task_source(run).get_task(run.task_ref)).body
    run.status = "describing"
    step.status = "running"
    slot = StepSession(
        profile_id="describer", label="Understanding", badge="agent"
    )
    step.active_sessions = [slot]
    service._save(run)
    prompt = DESCRIBE_PROMPT.format(issue=body)
    if feedback:
        prompt += MID_RUN_FEEDBACK_APPENDIX.format(feedback=feedback)
    result = await service._run_turn_tracked(
        run,
        service.backends.backend_for(Step.DESCRIBE),
        TurnRequest(
            prompt=prompt,
            cwd=run.workspace,
            permission_mode="plan",
            model=step.model,
            resume_id=step.session_id,
        ),
        slot,
        _bind(step, slot),
    )
    _park_awaiting_approval(service, run, step, result.final_text)


async def _run_feedback_turn(
    service: "WorkflowService", run: WorkflowRun, step, refinement: str
) -> None:
    slot = StepSession(
        profile_id="describer", label="Understanding", badge="agent"
    )
    service._retire_sessions(run, step)
    step.active_sessions = [slot]
    service._save(run)
    result = await service._run_turn_tracked(
        run,
        service.backends.backend_for(Step.DESCRIBE),
        TurnRequest(
            prompt=DESCRIBE_FEEDBACK_PROMPT.format(
                current=step.deliverable or "", feedback=refinement,
            ),
            cwd=run.workspace,
            permission_mode="plan",
            model=step.model,
            resume_id=None,
        ),
        slot,
        _bind(step, slot),
    )
    _park_awaiting_approval(service, run, step, result.final_text)


def _park_awaiting_approval(
    service: "WorkflowService", run: WorkflowRun, step, final_text: str
) -> None:
    step.deliverable = extract_understanding(final_text) or final_text
    service._retire_sessions(run, step)  # chips off at the gate
    step.status = "awaiting_approval"
    run.status = "awaiting_describe_approval"
    set_clock(run, "waiting", _now_utc())
    service._save(run)
