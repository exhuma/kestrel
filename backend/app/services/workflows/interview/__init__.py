"""Coordinator-driven interview round loop over per-profile questions."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from app.models_workflow import StepSession, WorkflowRun
from app.profiles import roster_summary
from app.questionnaire import (
    InterviewEnvelope,
    QAEntry,
    build_envelope,
    parse_envelope,
    render_assumptions_and_risks,
    render_qa,
    to_entries,
)
from app.services.exceptions import InvalidWorkflowStateError
from app.services.time_tracking import set_clock
from app.services.workflow_text import extract_profiles, extract_refined_issue
from app.services.workflows.interview.agent import run_refine_agent
from app.services.workflows.interview.questions import (
    dedup_questions,
    generate_questions,
)
from app.services.workflows.prompts import (
    COORDINATOR_PROMPT,
    MAX_REFINE_ROUNDS,
    MAX_REFINE_ROUNDS_HARD,
    MAX_SPECIALIST_RETRIES,
    REFINE_FEEDBACK_PROMPT,
    WRITE_REFINED_PROMPT,
)
from app.services.workflows.shared import _now_utc

if TYPE_CHECKING:
    from app.services.workflows import WorkflowService

_logger = logging.getLogger(__name__)

__all__ = [
    "coordinator_profiles",
    "dedup_questions",
    "rewrite_refined",
    "run_interview",
    "run_refine_agent",
    "write_refined",
]


async def coordinator_profiles(
    service: "WorkflowService",
    run: WorkflowRun,
    issue: str,
    accumulated: list[QAEntry],
) -> list[str]:
    """Ask the coordinator which profiles to interview next.

    With ``refine_samples > 1`` the coordinator is polled several
    times and the picks are UNIONed (first-seen order preserved):
    a weak model that intermittently forgets a specialist still
    summons it if any sample does. A failed sample is skipped, not
    fatal. K=1 is exactly one call, as before.
    """
    samples = max(1, service.settings.refine_samples)
    slots = [
        StepSession(profile_id="coordinator", label="Coordinator", badge="sys")
        for _ in range(samples)
    ]
    service._show_sessions(run, slots)

    async def _one(slot) -> list[str]:
        text = await run_refine_agent(
            service,
            run,
            COORDINATOR_PROMPT.format(
                roster=roster_summary(),
                issue=issue,
                answers=render_qa(accumulated),
            ),
            slot,
            substep="refine.coordinator",
        )
        return [pid for pid in (extract_profiles(text) or []) if pid]

    picks = await asyncio.gather(
        *(_one(slot) for slot in slots), return_exceptions=True
    )
    ordered: list[str] = []
    for result in picks:
        if isinstance(result, BaseException):
            _logger.warning("coordinator sample failed: %r", result)
            continue
        for pid in result:
            if pid not in ordered:
                ordered.append(pid)
    return ordered


async def run_interview(
    service: "WorkflowService", run: WorkflowRun, body: str | None
) -> tuple[str, list[QAEntry]]:
    """Run coordinator-driven interview rounds until done.

    :returns: The issue text and the accumulated Q&A entries.
    """
    step = run.steps[0]
    # Loop state carried across rounds (and rebuilt on restart from the
    # persisted envelope): per-profile failure counts, the dynamic round
    # cap, and the profiles awaiting a retry (last round's soft failures).
    attempts: dict[str, int] = {}
    round_cap = MAX_REFINE_ROUNDS
    retry_targets: list[str] = []
    if step.status == "awaiting_input":
        # Recovered mid-interview: rebuild loop state from the
        # persisted envelope and consume the pending finalize.
        envelope = parse_envelope(step.deliverable or "")
        if envelope is None:
            raise InvalidWorkflowStateError("interview state lost")
        issue = envelope.issue
        accumulated = list(envelope.accumulated)
        round_no = step.refine_round
        attempts = dict(envelope.attempts)
        round_cap = envelope.round_cap
        retry_targets = [
            i.profile
            for i in envelope.questionnaire.issues
            if i.severity == "soft"
        ]
        answers = await service._control[run.id].replies.get()
        accumulated += to_entries(envelope.questionnaire, answers)
        round_no += 1
    else:
        if body is None:
            raise InvalidWorkflowStateError(
                "fresh refine needs the issue body"
            )
        issue = body
        accumulated = []
        round_no = 1

    while round_no <= round_cap:
        run.status = "refining"
        set_clock(run, "active", _now_utc())
        step.status = "running"
        service._save(run)
        # Coordinator clarification is bounded by the base cap; the extra
        # rounds a retry unlocks are for retries only.
        coord = (
            await coordinator_profiles(service, run, issue, accumulated)
            if round_no <= MAX_REFINE_ROUNDS
            else []
        )
        retries = [
            pid for pid in retry_targets
            if attempts.get(pid, 0) <= MAX_SPECIALIST_RETRIES
        ]
        # Union, coordinator first, order preserved, de-duplicated.
        profiles: list[str] = []
        for pid in [*coord, *retries]:
            if pid not in profiles:
                profiles.append(pid)
        if not profiles:
            break
        if retries:
            # Attempting a retry extends the interview by one round.
            round_cap = min(round_cap + 1, MAX_REFINE_ROUNDS_HARD)
        questionnaire = await generate_questions(
            service, run, issue, accumulated, profiles, attempts
        )
        retry_targets = [
            i.profile
            for i in questionnaire.issues
            if i.severity == "soft"
        ]
        # Present when there is anything to show — questions to answer or
        # a failure status (so a retry can be re-triggered on submit).
        if not questionnaire.questions and not questionnaire.issues:
            break
        step.refine_round = round_no
        step.deliverable = build_envelope(
            InterviewEnvelope(
                questionnaire=questionnaire,
                draft_answers={},
                accumulated=accumulated,
                issue=issue,
                attempts=attempts,
                round_cap=round_cap,
            )
        )
        step.active_sessions = []  # human's turn: chips off
        step.status = "awaiting_input"
        run.status = "awaiting_refine_input"
        set_clock(run, "waiting", _now_utc())
        service._save(run)
        answers = await service._control[run.id].replies.get()
        accumulated += to_entries(questionnaire, answers)
        round_no += 1
    return issue, accumulated


async def write_refined(
    service: "WorkflowService",
    run: WorkflowRun,
    issue: str,
    accumulated: list[QAEntry],
) -> str:
    """Write the refined issue and append the risk section."""
    slot = StepSession(profile_id="writer", label="Writer", badge="agent")
    service._show_sessions(run, [slot])
    text = await run_refine_agent(
        service,
        run,
        WRITE_REFINED_PROMPT.format(
            issue=issue, answers=render_qa(accumulated)
        ),
        slot,
    )
    body = extract_refined_issue(text) or text
    risks = render_assumptions_and_risks(accumulated)
    if risks:
        body = f"{body.rstrip()}\n\n{risks}"
    return body


async def rewrite_refined(
    service: "WorkflowService", run: WorkflowRun, current: str, feedback: str
) -> str:
    """Regenerate the refined issue from gate feedback."""
    slot = StepSession(profile_id="writer", label="Writer", badge="agent")
    service._show_sessions(run, [slot])
    text = await run_refine_agent(
        service,
        run,
        REFINE_FEEDBACK_PROMPT.format(current=current, feedback=feedback),
        slot,
    )
    return extract_refined_issue(text) or text
