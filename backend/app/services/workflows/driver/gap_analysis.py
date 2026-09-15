"""The gap_analysis step: propose and publish self-contained follow-up tasks.

The agent creates and critiques a candidate decomposition, then a human gate
holds that candidate before any task-source write.  The pending proposal lives
in the step deliverable so it uses the existing workflow checkpointing.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping, Sequence, cast

from app.backends.base import TurnRequest
from app.models_workflow import Step, StepSession, WorkflowRun, WorkflowStep
from app.policy import get_policy
from app.ports import SubtaskContextError, TaskSource
from app.review_requests import render_delta_summary
from app.services.exceptions import InvalidWorkflowStateError
from app.services.time_tracking import set_clock
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
from app.services.workflows.scope import evaluate_scope, refusal_message
from app.services.workflows.sessions import _bind
from app.services.workflows.shared import _now_utc, _Rejected

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
class _Candidate:
    """A reviewed technical analysis and the tasks it proposes to publish."""

    technical_analysis: str
    tasks: list[dict[str, object]]


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


def _render_tasks(tasks: list[dict[str, object]]) -> str:
    """Render candidate tasks as ``[index] title\\nbody`` for a prompt."""
    return "\n\n".join(
        f"[{i}] {t['title']}\n{t['body']}" for i, t in enumerate(tasks)
    )


def _failing_indices(
    tasks: list[dict[str, object]], verdicts: dict[int, dict]
) -> list[int]:
    """Indices whose verdict is explicitly self_contained=False."""
    return [
        i
        for i in range(len(tasks))
        if not verdicts.get(i, {"self_contained": True})["self_contained"]
    ]


def _apply_revisions(
    tasks: list[dict[str, object]], revised: Sequence[Mapping[str, object]]
) -> None:
    """Merge a revision turn's output back into ``tasks``, in place."""
    for item in revised:
        index = item.get("index")
        if isinstance(index, int) and 0 <= index < len(tasks):
            tasks[index] = tasks[index] | {
                "title": str(item.get("title", tasks[index]["title"])),
                "body": str(item.get("body", tasks[index]["body"])),
            }


def _encode_candidate(candidate: _Candidate) -> str:
    """Serialize a pending proposal into the step's durable deliverable."""
    return json.dumps(
        {
            "technical_analysis": candidate.technical_analysis,
            "tasks": candidate.tasks,
        }
    )


def _decode_candidate(deliverable: str) -> _Candidate:
    """Restore a pending proposal or reject malformed persisted state."""
    payload = json.loads(deliverable)
    analysis = payload["technical_analysis"]
    tasks = payload["tasks"]
    if not isinstance(analysis, str) or not isinstance(tasks, list):
        raise ValueError("invalid decomposition candidate")
    normalized = [
        {
            "id": str(task.get("id", f"TASK-{index + 1}")),
            "title": str(task["title"]),
            "body": str(task["body"]),
            "prerequisites": list(task.get("prerequisites", [])),
            **(
                {"published_ref": str(task["published_ref"])}
                if task.get("published_ref")
                else {}
            ),
        }
        for index, task in enumerate(tasks)
        if isinstance(task, dict)
    ]
    if not normalized or len(normalized) != len(tasks):
        raise ValueError("invalid decomposition candidate tasks")
    return _Candidate(technical_analysis=analysis, tasks=normalized)


async def _check_self_containment(
    turn: _Turn, tech_analysis: str, tasks: list[dict[str, object]]
) -> list[dict[str, object]]:
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
        revised = cast(
            Sequence[Mapping[str, object]],
            extract_followup_tasks(revision_text) or [],
        )
        _apply_revisions(tasks, revised)
    _logger.warning(
        "workflow %s: gap_analysis proposed tasks with unresolved "
        "self-containment gaps after %d passes",
        turn.wf_run.id,
        _MAX_CONTAINMENT_PASSES,
    )
    return tasks


async def run_gap_analysis(
    service: "WorkflowService", run: WorkflowRun
) -> None:
    """Create a candidate decomposition, await approval, then publish it.

    A request for changes reruns analysis before parking again.  A bare
    rejection raises the driver's usual terminal-rejection signal.
    """
    step = run.steps[2]
    if not run.prd_approved or not run.approved_prd:
        raise InvalidWorkflowStateError("gap analysis requires approved PRD")
    revised_from: str | None = None
    amendment = ""
    while True:
        if step.status != "awaiting_approval":
            await _create_candidate(service, run, step, revised_from, amendment)
            revised_from = None
            amendment = ""
        decision = await service._await_gate(run.id)
        set_clock(run, "active", _now_utc())
        if decision.approved:
            await _publish_candidate(service, run, step)
            return
        if decision.refinement is None:
            raise _Rejected()
        scope = await evaluate_scope(service, run, decision.refinement)
        if not scope.allowed:
            await service._task_source(run).post_comment(
                run.task_ref, refusal_message(scope)
            )
            step.status = "awaiting_approval"
            run.status = "awaiting_decomposition_approval"
            run.pending_gate_decision = None
            set_clock(run, "waiting", _now_utc())
            service._save(run)
            continue
        revised_from = step.deliverable
        amendment = decision.refinement
        step.status = "pending"


async def _create_candidate(
    service: "WorkflowService",
    run: WorkflowRun,
    step: WorkflowStep,
    revised_from: str | None,
    amendment: str,
) -> None:
    """Run analysis and containment checking, then checkpoint its proposal."""
    prd = run.approved_prd or ""
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
        GAP_ANALYSIS_PROMPT.format(
            prd=prd, understanding=understanding, amendment=amendment
        )
    )
    tech_analysis = extract_tech_analysis(analysis_text) or analysis_text
    fallback = [
        {
            "id": "TASK-1",
            "title": run.issue_title or "Implement approved work",
            "body": prd,
            "prerequisites": [],
        }
    ]
    extracted_tasks = extract_followup_tasks(analysis_text) or fallback
    tasks = cast(list[dict[str, object]], extracted_tasks)
    tasks = await _check_self_containment(turn, tech_analysis, tasks)

    service._write_artifact(run, "technical-analysis.md", tech_analysis)
    service._retire_sessions(run, step)
    step.deliverable = _encode_candidate(_Candidate(tech_analysis, tasks))
    if revised_from is not None:
        source = cast(TaskSource, service._task_source(run))
        await source.post_comment(
            run.task_ref,
            render_delta_summary(
                revised_from,
                step.deliverable,
                source.deep_link_ref(run.task_ref),
            ),
        )
    step.status = "awaiting_approval"
    run.status = "awaiting_decomposition_approval"
    set_clock(run, "waiting", _now_utc())
    service._save(run)


async def _publish_candidate(
    service: "WorkflowService", run: WorkflowRun, step: WorkflowStep
) -> None:
    """Publish the approved, checkpointed candidate and finish the run."""
    candidate = _decode_candidate(step.deliverable or "")

    source = cast(TaskSource, service._task_source(run))
    await service.git.push(
        run.workspace, run.branch, service._code_host(run).git_credential()
    )
    for task in candidate.tasks:
        task_ref = task.get("published_ref")
        if task_ref is None:
            body = append_subtask_sentinel(str(task["body"]))
            try:
                task_ref = await source.create_subtask(
                    run.task_ref, str(task["title"]), body
                )
            except SubtaskContextError as exc:
                task["published_ref"] = exc.task_ref
                step.deliverable = _encode_candidate(candidate)
                service._save(run)
                if service.child_tasks is not None:
                    _record_child(service, run, exc.task_ref, task)
                raise
            task["published_ref"] = task_ref
            step.deliverable = _encode_candidate(candidate)
            service._save(run)
            if service.child_tasks is not None:
                _record_child(service, run, task_ref, task)
            continue
        await source.complete_subtask(run.task_ref, str(task_ref))
    # Distinct from the per-follow-up create_subtask calls above: the
    # summary goes back to the *original* ticket, for human reference
    # (spec.md FR-012) — post_comment works uniformly across every
    # source, unlike attach (a GitHub no-op) or publish_refined (which
    # would overwrite the ticket body rather than add to it).
    await source.post_comment(
        run.task_ref, f"## Technical analysis\n\n{candidate.technical_analysis}"
    )

    step.status = "done"
    run.status = "decomposed"
    service._save(run)


def _record_child(
    service: "WorkflowService",
    run: WorkflowRun,
    task_ref: str,
    task: dict[str, object],
) -> None:
    """Persist a child source reference with its parent feature DAG metadata."""
    if service.child_tasks is None:
        return
    prerequisites = task.get("prerequisites", [])
    if not isinstance(prerequisites, list):
        prerequisites = []
    service.child_tasks.record(
        run.id,
        task_ref,
        str(task.get("id", "")),
        tuple(item for item in prerequisites if isinstance(item, str)),
        run.branch,
    )
