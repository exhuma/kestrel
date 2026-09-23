"""The describe -> refine -> technical_analysis -> design -> code/verify ->
deliver run state machine."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.backends.base import TurnRequest
from app.design_contract import (
    DesignContract,
    acceptance_markdown,
    check_contract_json,
    task_graph_json,
)
from app.documents import parse_markdown
from app.models_workflow import Step, StepSession, WorkflowRun
from app.policy import get_policy
from app.review_requests import render_delta_summary
from app.services.exceptions import InvalidWorkflowStateError
from app.services.feedback.dispatch import drain_feedback
from app.services.time_tracking import set_clock
from app.services.workflow_text import (
    extract_boundary,
    extract_design_contract,
    extract_plan,
    has_sentinel,
    has_subtask_sentinel,
)
from app.services.workflows import interview, screenshots
from app.services.workflows.driver.code_verify import code_and_verify
from app.services.workflows.driver.delivery import deliver
from app.services.workflows.driver.describe import describe
from app.services.workflows.driver.escalate import fail_active_steps
from app.services.workflows.driver.technical_analysis import (
    run_technical_analysis,
)
from app.services.workflows.prompts import (
    DESIGN_PROMPT,
    MID_RUN_FEEDBACK_APPENDIX,
)
from app.services.workflows.sessions import _bind
from app.services.workflows.shared import _TRANSIENT, _now_utc, _Rejected
from app.services.workflows.validation import (
    request_valid_output,
    required_tagged_text,
)

if TYPE_CHECKING:
    from app.services.workflows import WorkflowService

_logger = logging.getLogger(__name__)


async def recover(service: "WorkflowService") -> None:
    """
    Resume persisted runs after a process restart.

    Gate-parked runs (awaiting input or approval) get a
    fresh control and a driver task that re-enters at the
    gate. Runs that died mid-step are failed loudly —
    their subprocess is gone.

    Each run's recovery is isolated: one run raising here (e.g. a
    failing persist) is logged and skipped rather than aborting
    recovery for every other run — and, since this runs unguarded in
    the app's startup lifespan, rather than aborting the app's boot.
    """
    for run in service.workflows.list():
        try:
            service._recover_one(run)
        except Exception:
            _logger.exception(
                "workflow %s: failed to recover, skipping", run.id
            )


def recover_one(service: "WorkflowService", run: WorkflowRun) -> None:
    """Recover a single persisted run (see :func:`recover`)."""
    if run.status.startswith("awaiting_"):
        service._control[run.id] = service._new_control()
        service._spawn_driver(run.id, resume(service, run.id))
    elif run.status in _TRANSIENT:
        run.status = "failed"
        run.error = "backend restarted mid-step"
        fail_active_steps(service, run)
        service._save(run)


async def resume(service: "WorkflowService", workflow_id: str) -> None:
    """Re-enter a gate-parked run after recovery."""
    run = service.get(workflow_id)
    try:
        await continue_run(service, run)
    except _Rejected:
        run.status = "rejected"
        service._safe_save(run)
        # A rejected PRD is stop-and-dismiss (FR-012/FR-033): record a
        # dismissal so polling does not silently re-create the run while
        # the ticket still qualifies; the re-trigger gesture clears it.
        if service.dismissals is not None and run.task_ref:
            service.dismissals.add(run.task_ref)
        await service._teardown_workspace(run)
    except Exception as exc:
        _logger.exception(
            "workflow %s (%s#%s) failed during %s",
            workflow_id,
            run.repo,
            run.issue_number,
            run.status,
        )
        run.status = "failed"
        run.error = _failure_message(exc)
        fail_active_steps(service, run)
        service._safe_save(run)
        await service._teardown_workspace(run)


def _seed_from_sentinel(
    run: WorkflowRun, body: str, linked_child: bool = False
) -> bool:
    """Pre-mark steps done per the ticket body's sentinel, if any.

    A linked Kestrel-generated child with ``SUBTASK_SENTINEL`` already has a
    self-contained, parent-approved scope, so it skips describe, refine, and
    technical_analysis and begins at design. An unlinked subtask sentinel
    retains the historical gate behavior. A plain ``SENTINEL`` body (an
    already-refined ticket, e.g. a rerun) skips describe.

    :returns: True if any steps were pre-marked (the caller must persist
        and re-enter ``continue_run`` with no fresh issue body); False
        for an ordinary ticket with neither sentinel.
    """
    if has_subtask_sentinel(body):
        if linked_child:
            for idx in (0, 1, 2):
                run.steps[idx].status = "done"
            run.steps[1].deliverable = body
            run.prd_approved = True
            run.approved_prd = body
            return True
        for idx in (0, 2):
            run.steps[idx].status = "done"
        run.steps[1].deliverable = body
        run.steps[1].status = "awaiting_approval"
        run.status = "awaiting_refine_approval"
        return True
    if has_sentinel(body):
        run.steps[0].status = "done"
        run.steps[1].deliverable = body
        run.steps[1].status = "awaiting_approval"
        run.status = "awaiting_refine_approval"
        return True
    return False


async def drive(service: "WorkflowService", workflow_id: str) -> None:
    run = service.get(workflow_id)
    try:
        run.status = "cloning"
        set_clock(run, "active", _now_utc())
        service._save(run)
        task = await service._task_source(run).get_task(run.task_ref)
        run.issue_title = task.title
        if not run.base_branch:
            run.base_branch = await service._code_host(run).get_default_branch(
                run.repo
            )
        service._save(run)
        code_host = service._code_host(run)
        remote = code_host.clone_remote(run.repo)
        mirror = service._mirror_dir(run.repo)
        await service.git.ensure_mirror(
            remote, mirror, code_host.git_credential()
        )
        if run.base_branch and _is_linked_child(service, run):
            await service.git.ensure_remote_branch(
                mirror, run.base_branch, code_host.git_credential()
            )
        await service.git.add_worktree(
            mirror, run.workspace, run.base_branch, run.branch
        )
        service.record_artifact(run, "local_branch", run.branch, run.branch)

        if _seed_from_sentinel(run, task.body, _is_linked_child(service, run)):
            service._save(run)
            await continue_run(service, run)
        else:
            await continue_run(service, run, issue_body=task.body)
    except _Rejected:
        run.status = "rejected"
        service._safe_save(run)
        # A rejected PRD is stop-and-dismiss (FR-012/FR-033): record a
        # dismissal so polling does not silently re-create the run while
        # the ticket still qualifies; the re-trigger gesture clears it.
        if service.dismissals is not None and run.task_ref:
            service.dismissals.add(run.task_ref)
        await service._teardown_workspace(run)
    except Exception as exc:  # record, do not crash the loop
        _logger.exception(
            "workflow %s (%s) failed during %s",
            workflow_id,
            run.task_ref,
            run.status,
        )
        run.status = "failed"
        run.error = _failure_message(exc)
        fail_active_steps(service, run)
        service._safe_save(run)
        await service._teardown_workspace(run)


def _is_linked_child(service: "WorkflowService", run: WorkflowRun) -> bool:
    """Return whether ``run`` was started from persisted child DAG metadata."""
    child_tasks = service.child_tasks
    return (
        child_tasks is not None
        and child_tasks.scheduling_details(run.task_ref) is not None
    )


def _failure_message(exc: BaseException) -> str:
    """Return an actionable workflow failure message for any exception."""
    return str(exc).strip() or f"{type(exc).__name__} without details"


async def continue_run(
    service: "WorkflowService",
    run: WorkflowRun,
    issue_body: str | None = None,
) -> None:
    """Run every unfinished phase, then deliver.

    describe (understanding gate) -> refine (PRD approval gate) ->
    technical_analysis (decomposition approval gate) -> design ->
    autonomous code<->verify loop -> deliver. Everything after PRD
    approval is autonomous except for decomposition approval;
    technical_analysis, once genuinely run (not pre-marked done by a
    sentinel skip — see
    :func:`_seed_from_sentinel`), always ends the run, so the caller
    returns rather than falling through to design. The code<->verify
    loop may also escalate instead of delivering (FR-018/FR-020).

    Each not-yet-done step is preceded by a ``drain_feedback`` call
    (feature 013, US2/US3): a no-op on a fresh drive (nothing queued
    yet), but on a resumed/revived run it folds in whatever ticket or
    triage feedback was queued for this run with nowhere else to land —
    never mid-turn, only at a boundary this loop already reaches
    naturally. ``technical_analysis`` is a fan-out/reconcile/critic turn, not
    a single prompt like describe/refine/design, so feeding drained
    feedback into it is intentionally left for a follow-up rather than
    bolted on here.
    """
    # Reserve this run's artifact folder once the worktree exists —
    # covers both the fresh drive and a resumed run (no-op if already
    # chosen and restored from the DB).
    service._ensure_artifact_dir(run)
    if run.steps[0].status != "done":
        describe_feedback = drain_feedback(service, run)
        await describe(service, run, issue_body, feedback=describe_feedback)
    if run.steps[1].status != "done":
        refine_feedback = drain_feedback(service, run)
        await refine(service, run, feedback=refine_feedback)
    if run.steps[2].status != "done":
        await run_technical_analysis(service, run)
        return
    if run.steps[3].status != "done":
        design_feedback = drain_feedback(service, run)
        await design(service, run, feedback=design_feedback)
    if run.steps[5].status != "done":
        escalated = await code_and_verify(service, run)
        if escalated:
            return
    await deliver(service, run)


async def refine(
    service: "WorkflowService", run: WorkflowRun, feedback: str = ""
) -> None:
    """Drive the profile-aware refinement interview to an approved,
    refined issue.

    A coordinator picks the stakeholder profiles to interview each
    round; one sub-agent per profile (carrying that profile's
    persona) generates its questions; the human answers (with
    partial saves and waivers); the coordinator may open further
    rounds. A writer then folds every answer into the refined issue,
    to which the deterministic risk section is appended before the
    approval gate.

    :param feedback: Ticket/triage feedback drained at the boundary just
        before this step started (feature 013, US2/US3), folded into the
        seed when present. On a resume (this step already produced a
        deliverable once — a review-feedback triage re-opening an
        already-approved PRD), that prior deliverable is the seed; on a
        genuinely fresh run, the ticket's current body is (always
        re-fetched rather than threaded through from describe's gate,
        since a resumed coroutine may never have received the original
        body — the ticket is refine's one durable source until this same
        call publishes over it below).
    """
    step = run.steps[1]
    step.model = get_policy().model_for(Step.REFINE)
    if step.status != "awaiting_approval":
        if step.deliverable:
            seed = step.deliverable
        else:
            seed = (await service._task_source(run).get_task(run.task_ref)).body
        if feedback:
            seed += MID_RUN_FEEDBACK_APPENDIX.format(feedback=feedback)
        issue, accumulated = await interview.run_interview(service, run, seed)
        step.deliverable = await interview.write_refined(
            service, run, issue, accumulated
        )
        service._retire_sessions(run, step)  # chips off at the gate
        step.status = "awaiting_approval"
        run.status = "awaiting_refine_approval"
        set_clock(run, "waiting", _now_utc())
        service._save(run)
    while True:
        decision = await service._await_gate(run.id)
        set_clock(run, "active", _now_utc())
        if decision.approved:
            await _publish_refined(service, run, step, decision.deliverable)
            # Upload the refine mockups too (Jira attaches them; GitHub
            # no-ops — they ride along committed in the PR). Best-effort.
            await screenshots.upload_screenshots(
                service._task_source(run),
                run,
                service.settings.screenshots_root,
                "refine",
            )
            step.deliverable = decision.deliverable or (step.deliverable or "")
            step.status = "done"
            service._save(run)
            return
        if decision.refinement is None:
            raise _Rejected()
        previous = step.deliverable or ""
        _start_refine_revision(service, run, step)
        step.deliverable = await interview.rewrite_refined(
            service, run, step.deliverable or "", decision.refinement
        )
        source = service._task_source(run)
        await source.post_comment(
            run.task_ref,
            render_delta_summary(
                previous, step.deliverable, source.deep_link_ref(run.task_ref)
            ),
        )
        service._retire_sessions(run, step)  # chips off at the gate
        step.status = "awaiting_approval"
        run.status = "awaiting_refine_approval"
        set_clock(run, "waiting", _now_utc())
        service._save(run)


async def _publish_refined(
    service: "WorkflowService",
    run: WorkflowRun,
    step,
    deliverable: str | None,
) -> None:
    """Snapshot a task body before publishing the approved PRD."""
    final = deliverable or (step.deliverable or "")
    source = service._task_source(run)
    # A body snapshot permits adapters that publish in-place to restore exactly
    # the input seen by a new run. Attachment-only sources do not modify it.
    original = (await source.get_task(run.task_ref)).body
    service.record_artifact(
        run, "source_body", f"{run.task_ref}\0{original}", "published PRD",
        "restore",
    )
    await source.publish_refined(run.task_ref, parse_markdown(final))


def _start_refine_revision(
    service: "WorkflowService", run: WorkflowRun, step
) -> None:
    """Persist refine's active state before its feedback rewrite blocks."""
    run.status = "refining"
    step.status = "running"
    service._save(run)


async def design(
    service: "WorkflowService", run: WorkflowRun, feedback: str = ""
) -> None:
    """Run the designer: produce a high-level design/plan. Gateless.

    :param feedback: Ticket feedback drained at the boundary just before
        this step started (feature 013, US2) — folded into the prompt
        alongside the PRD, when present.
    """
    if not run.prd_approved:
        raise InvalidWorkflowStateError("design requires approved PRD")
    step = run.steps[3]
    prd = run.steps[1].deliverable or ""
    # Persist the approved PRD as a handover artifact, then reference it
    # (file-capable backend) or inline it (text-only) in the prompt.
    service._write_artifact(run, "prd.md", prd)
    model = get_policy().model_for(Step.DESIGN)
    step.model = model
    run.status = "designing"
    step.status = "running"
    slot = StepSession(profile_id="designer", label="Designer", badge="agent")
    step.active_sessions = [slot]
    service._save(run)
    prompt = DESIGN_PROMPT.format(
        issue=service._artifact_slot(Step.DESIGN, run, "prd.md", prd)
    )
    if feedback:
        prompt += MID_RUN_FEEDBACK_APPENDIX.format(feedback=feedback)
    async def send(attempt_prompt: str) -> str:
        """Run one design attempt and return the raw model response."""
        result = await service._run_turn_tracked(
            run,
            service.backends.backend_for(Step.DESIGN),
            TurnRequest(
                prompt=attempt_prompt,
                cwd=run.workspace,
                permission_mode="plan",
                model=model,
                resume_id=step.session_id,
            ),
            slot,
            _bind(step, slot),
        )
        return result.final_text

    raw_design = await request_valid_output(
        send, prompt, _valid_design, "design"
    )
    contract = extract_design_contract(raw_design)
    design_text = contract.plan if contract else extract_plan(raw_design) or ""
    step.deliverable = design_text
    # Classify the project's boundary for the verify step (feature 005).
    # A missing/malformed tag leaves boundary None — verify then falls
    # back to today's check-and-diff-judgment-only behaviour; this must
    # never fail the design step itself.
    run.boundary = (
        contract.boundary if contract else extract_boundary(raw_design)
    )
    # Persist the design as the second handover artifact for code/verify.
    service._write_artifact(run, "design.md", design_text)
    _write_design_contract_artifacts(service, run, contract)
    service._retire_sessions(run, step)
    step.status = "done"
    service._save(run)


def _valid_design(text: str) -> str:
    """Accept design output only when it carries a nonempty plan."""
    contract = extract_design_contract(text)
    if contract is not None and contract.plan.strip():
        return text
    required_tagged_text(text, "PLAN")
    return text


def _write_design_contract_artifacts(
    service: "WorkflowService",
    run: WorkflowRun,
    contract: DesignContract | None,
) -> None:
    """Persist structured handover files, with empty legacy compatibility."""
    contract = contract or DesignContract("legacy plan", None, [], [], [])
    service._write_artifact(run, "acceptance.md", acceptance_markdown(contract))
    service._write_artifact(run, "task-graph.json", task_graph_json(contract))
    service._write_artifact(
        run, "check-contract.json", check_contract_json(contract)
    )
