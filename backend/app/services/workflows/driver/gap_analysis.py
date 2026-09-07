"""The gap_analysis step: technical analysis and decomposition into
self-contained follow-up tasks (feature 012).

Gateless and run-terminating on success — unlike refine, no human
approval gate sits here (matches design's existing autonomy). A single
rich analysis turn covers every technical altitude (engineering,
security, data, architecture, ops, test strategy) at once rather than
refine's parallel per-profile fan-out: gap_analysis is autonomous, so
refine's "don't overwhelm the human with duplicate questions" rationale
for that fan-out does not apply here. A dedicated self-containment
critic turn then stands in for the missing human reviewer, checking each
candidate follow-up task the way `critique_coverage` checks a folded
questionnaire for a lost stakeholder concern.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.backends.base import TurnRequest
from app.models_workflow import Step, StepSession, WorkflowRun, WorkflowStep
from app.policy import get_policy
from app.services.workflow_text import (
    append_subtask_sentinel,
    extract_containment_verdicts,
    extract_followup_tasks,
    extract_tech_analysis,
)
from app.services.workflows.prompts import (
    GAP_ANALYSIS_CRITIC_PROMPT,
    GAP_ANALYSIS_PROMPT,
    GAP_ANALYSIS_REVISION_PROMPT,
)
from app.services.workflows.sessions import _bind

if TYPE_CHECKING:
    from app.services.workflows import WorkflowService

_logger = logging.getLogger(__name__)

#: Bound on the self-containment revise-and-recheck cycle: one revision
#: pass is enough to fix a real gap (the revision turn is given the exact
#: reason); anything still failing after that is logged and published
#: anyway rather than looping — mirroring the project's other bounded
#: agent loops (MAX_REFINE_ROUNDS, max_verify_iterations).
_MAX_CONTAINMENT_PASSES = 2


@dataclass
class _Turn:
    """The collaborators every gap_analysis turn shares, bundled to stay
    under the 5-argument limit on the helper functions below."""

    service: "WorkflowService"
    wf_run: WorkflowRun
    step: WorkflowStep
    slot: StepSession

    async def send(self, prompt: str) -> str:
        """Run one turn against this step's slot; return its response."""
        model = get_policy().model_for(Step.GAP_ANALYSIS)
        result = await self.service._run_turn_tracked(
            self.wf_run,
            self.service.backends.backend_for(Step.GAP_ANALYSIS),
            TurnRequest(
                prompt=prompt,
                cwd=self.wf_run.workspace,
                permission_mode="plan",
                model=model,
                resume_id=None,
            ),
            self.slot,
            _bind(self.step, self.slot),
        )
        return result.final_text


def _render_tasks(tasks: list[dict[str, str]]) -> str:
    """Render candidate tasks as ``[index] title\\nbody`` for a prompt."""
    return "\n\n".join(
        f"[{i}] {t['title']}\n{t['body']}" for i, t in enumerate(tasks)
    )


def _failing_indices(
    tasks: list[dict[str, str]], verdicts: dict[int, dict]
) -> list[int]:
    """Indices whose verdict is explicitly self_contained=False."""
    return [
        i for i in range(len(tasks))
        if not verdicts.get(i, {"self_contained": True})["self_contained"]
    ]


def _apply_revisions(
    tasks: list[dict[str, str]], revised: list[dict[str, object]]
) -> None:
    """Merge a revision turn's output back into ``tasks``, in place."""
    for item in revised:
        index = item.get("index")
        if isinstance(index, int) and 0 <= index < len(tasks):
            tasks[index] = {
                "title": str(item.get("title", tasks[index]["title"])),
                "body": str(item.get("body", tasks[index]["body"])),
            }


async def _check_self_containment(
    turn: _Turn, tech_analysis: str, tasks: list[dict[str, str]]
) -> list[dict[str, str]]:
    """Revise any candidate task that fails the self-containment check.

    Runs the critic, and — when at least one task fails — one revision
    pass followed by one re-check, then accepts the result regardless
    (bounded by :data:`_MAX_CONTAINMENT_PASSES`; a task still failing
    after revision is logged, not looped on forever).
    """
    for _pass in range(_MAX_CONTAINMENT_PASSES):
        verdict_text = await turn.send(
            GAP_ANALYSIS_CRITIC_PROMPT.format(
                tech_analysis=tech_analysis, tasks=_render_tasks(tasks)
            )
        )
        verdicts = extract_containment_verdicts(verdict_text) or {}
        failing = _failing_indices(tasks, verdicts)
        if not failing:
            return tasks
        failing_payload = "\n\n".join(
            f"[{i}] {tasks[i]['title']}\n"
            f"Reason: {verdicts.get(i, {}).get('reason', '')}\n"
            f"{tasks[i]['body']}"
            for i in failing
        )
        revision_text = await turn.send(
            GAP_ANALYSIS_REVISION_PROMPT.format(
                tech_analysis=tech_analysis,
                all_tasks=_render_tasks(tasks),
                failing_tasks=failing_payload,
            )
        )
        _apply_revisions(tasks, extract_followup_tasks(revision_text) or [])
    _logger.warning(
        "workflow %s: gap_analysis published with unresolved "
        "self-containment gaps after %d passes",
        turn.wf_run.id, _MAX_CONTAINMENT_PASSES,
    )
    return tasks


async def run_gap_analysis(
    service: "WorkflowService", run: WorkflowRun
) -> None:
    """Run the gap_analysis step to completion.

    Produces a technical-analysis summary and one or more self-contained
    follow-up tasks, publishes both back to the task source, and ends the
    run (``run.status = "decomposed"``) without proceeding to design —
    the original ticket is never itself designed/coded/verified. A
    failure anywhere (including a create_subtask call after the
    self-containment gate passed) propagates to the caller and fails the
    run, exactly like any other unhandled exception during a gateless
    step — never a silently partial publish.
    """
    step = run.steps[2]
    prd = run.steps[1].deliverable or ""
    understanding = run.steps[0].deliverable or ""
    step.model = get_policy().model_for(Step.GAP_ANALYSIS)
    run.status = "analyzing"
    step.status = "running"
    slot = StepSession(
        profile_id="gap-analysis", label="Tech Analysis", badge="agent"
    )
    step.active_sessions = [slot]
    service._save(run)

    turn = _Turn(service=service, wf_run=run, step=step, slot=slot)
    analysis_text = await turn.send(
        GAP_ANALYSIS_PROMPT.format(prd=prd, understanding=understanding)
    )
    tech_analysis = extract_tech_analysis(analysis_text) or analysis_text
    tasks = extract_followup_tasks(analysis_text) or [
        {"title": run.issue_title or "Implement approved work", "body": prd}
    ]
    tasks = await _check_self_containment(turn, tech_analysis, tasks)

    service._write_artifact(run, "technical-analysis.md", tech_analysis)

    source = service._task_source(run)
    for task in tasks:
        body = append_subtask_sentinel(task["body"])
        await source.create_subtask(run.task_ref, task["title"], body)
    # Distinct from the per-follow-up create_subtask calls above: the
    # summary goes back to the *original* ticket, for human reference
    # (spec.md FR-012) — post_comment works uniformly across every
    # source, unlike attach (a GitHub no-op) or publish_refined (which
    # would overwrite the ticket body rather than add to it).
    await source.post_comment(
        run.task_ref, f"## Technical analysis\n\n{tech_analysis}"
    )

    service._retire_sessions(run, step)
    step.deliverable = tech_analysis
    step.status = "done"
    run.status = "decomposed"
    service._save(run)
