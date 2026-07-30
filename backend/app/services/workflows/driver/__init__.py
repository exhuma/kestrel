"""The refine -> design -> code/verify -> deliver run state machine."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.backends.base import TurnRequest
from app.models_workflow import Step, StepSession, WorkflowRun
from app.policy import get_policy
from app.services.time_tracking import set_clock
from app.services.workflow_text import (
    extract_boundary,
    extract_plan,
    has_sentinel,
)
from app.services.workflows import interview, screenshots
from app.services.workflows.driver.code_verify import code_and_verify
from app.services.workflows.driver.escalate import fail_active_steps
from app.services.workflows.prompts import DESIGN_PROMPT
from app.services.workflows.sessions import _bind
from app.services.workflows.shared import _TRANSIENT, _now_utc

if TYPE_CHECKING:
    from app.services.workflows import WorkflowService

_logger = logging.getLogger(__name__)


class _Rejected(Exception):
    """Internal signal that a gate was rejected."""


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
        fail_active_steps(run)
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
            workflow_id, run.repo, run.issue_number,
            run.status,
        )
        run.status = "failed"
        run.error = str(exc)
        fail_active_steps(run)
        service._safe_save(run)
        await service._teardown_workspace(run)


async def drive(service: "WorkflowService", workflow_id: str) -> None:
    run = service.get(workflow_id)
    try:
        run.status = "cloning"
        set_clock(run, "active", _now_utc())
        service._save(run)
        task = await service._task_source(run).get_task(run.task_ref)
        run.issue_title = task.title
        if not run.base_branch:
            run.base_branch = await service._code_host(
                run
            ).get_default_branch(run.repo)
        service._save(run)
        code_host = service._code_host(run)
        remote = code_host.clone_remote(run.repo)
        mirror = service._mirror_dir(run.repo)
        await service.git.ensure_mirror(
            remote, mirror, code_host.git_credential()
        )
        await service.git.add_worktree(
            mirror, run.workspace, run.base_branch, run.branch
        )

        if has_sentinel(task.body):
            run.steps[0].status = "done"
            run.steps[0].deliverable = task.body
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
            workflow_id, run.task_ref, run.status,
        )
        run.status = "failed"
        run.error = str(exc)
        fail_active_steps(run)
        service._safe_save(run)
        await service._teardown_workspace(run)


async def continue_run(
    service: "WorkflowService",
    run: WorkflowRun,
    issue_body: str | None = None,
) -> None:
    """Run every unfinished phase, then deliver.

    refine (PRD approval gate) -> design -> autonomous code<->verify loop
    -> deliver. Everything after PRD approval is gateless (FR-014); the
    loop may escalate instead of delivering (FR-018/FR-020).
    """
    # Reserve this run's artifact folder once the worktree exists —
    # covers both the fresh drive and a resumed run (no-op if already
    # chosen and restored from the DB).
    service._ensure_artifact_dir(run)
    if run.steps[0].status != "done":
        await refine(service, run, issue_body)
    if run.steps[1].status != "done":
        await design(service, run)
    if run.steps[3].status != "done":
        escalated = await code_and_verify(service, run)
        if escalated:
            return
    await deliver(service, run)


async def refine(
    service: "WorkflowService", run: WorkflowRun, body: str | None = None
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
    """
    step = run.steps[0]
    step.model = get_policy().model_for(Step.REFINE)
    if step.status != "awaiting_approval":
        issue, accumulated = await interview.run_interview(
            service, run, body
        )
        step.deliverable = await interview.write_refined(
            service, run, issue, accumulated
        )
        step.active_sessions = []  # chips off at the gate
        step.status = "awaiting_approval"
        run.status = "awaiting_refine_approval"
        set_clock(run, "waiting", _now_utc())
        service._save(run)
    while True:
        decision = await service._await_gate(run.id)
        set_clock(run, "active", _now_utc())
        if decision.approved:
            final = decision.deliverable or (step.deliverable or "")
            source = service._task_source(run)
            # Publish the approved PRD to the ticket: GitHub writes the
            # refined body + sentinel; Jira attaches PRD.md (FR-011).
            await source.publish_refined(run.task_ref, final)
            # Upload the refine mockups too (Jira attaches them; GitHub
            # no-ops — they ride along committed in the PR). Best-effort.
            await screenshots.upload_screenshots(
                source, run, service.settings.screenshots_root, "refine"
            )
            step.deliverable = final
            step.status = "done"
            service._save(run)
            return
        if decision.refinement is None:
            raise _Rejected()
        step.deliverable = await interview.rewrite_refined(
            service, run, step.deliverable or "", decision.refinement
        )
        step.active_sessions = []  # chips off at the gate
        step.status = "awaiting_approval"
        run.status = "awaiting_refine_approval"
        set_clock(run, "waiting", _now_utc())
        service._save(run)


async def design(service: "WorkflowService", run: WorkflowRun) -> None:
    """Run the designer: produce a high-level design/plan. Gateless."""
    step = run.steps[1]
    prd = run.steps[0].deliverable or ""
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
    result = await service._run_turn_tracked(
        run,
        service.backends.backend_for(Step.DESIGN),
        TurnRequest(
            prompt=DESIGN_PROMPT.format(
                issue=service._artifact_slot(Step.DESIGN, run, "prd.md", prd)
            ),
            cwd=run.workspace,
            permission_mode="plan", model=model,
            resume_id=step.session_id,
        ),
        slot,
        _bind(step, slot),
    )
    design_text = extract_plan(result.final_text) or result.final_text
    step.deliverable = design_text
    # Classify the project's boundary for the verify step (feature 005).
    # A missing/malformed tag leaves boundary None — verify then falls
    # back to today's check-and-diff-judgment-only behaviour; this must
    # never fail the design step itself.
    run.boundary = extract_boundary(result.final_text)
    # Persist the design as the second handover artifact for code/verify.
    service._write_artifact(run, "design.md", design_text)
    step.active_sessions = []
    step.status = "done"
    service._save(run)


async def deliver(service: "WorkflowService", run: WorkflowRun) -> None:
    """Commit, push, open the change request, and finish the run."""
    run.status = "opening_pr"
    service._save(run)
    # Change-request metadata is source-aware: a GitHub run closes its
    # issue (#n); a Jira run references the RFC key (the ticket is in Jira).
    if run.issue_number is not None:
        commit_msg = f"Implement #{run.issue_number}"
        cr_title = f"{run.issue_title} (#{run.issue_number})"
        cr_body = f"Closes #{run.issue_number}\n\nOpened by kestrel."
    else:
        commit_msg = f"Implement {run.task_ref}"
        cr_title = f"{run.issue_title} ({run.task_ref})"
        cr_body = f"Implements {run.task_ref}\n\nOpened by kestrel."
    # The coder (or the loop's safety net) may already have committed
    # everything — e.g. a run accepted on its first round with no
    # trailing artifact writes since. An empty `git commit` errors, so
    # only commit when the tree is actually still dirty.
    if (await service.git.diff(run.workspace)).strip():
        await service.git.commit_all(run.workspace, commit_msg)
    await service.git.push(
        run.workspace, run.branch, service._code_host(run).git_credential()
    )
    run.pr_url = await service._code_host(run).open_change_request(
        run.repo,
        head=run.branch,
        base=run.base_branch,
        title=cr_title,
        body=cr_body,
    )
    run.status = "done"
    service._save(run)
    # Post the change-request link to the ticket (best-effort — FR-019).
    try:
        await service._task_source(run).post_comment(
            run.task_ref, f"Change request opened: {run.pr_url}"
        )
    except Exception:  # noqa: BLE001 — best-effort; run is already done
        _logger.exception("failed to post CR link for %s", run.task_ref)
    # Upload the verify screenshots to the ticket (Jira attaches them;
    # GitHub no-ops — they rode along in the pushed PR). Best-effort,
    # before teardown removes the worktree they live in.
    await screenshots.upload_screenshots(
        service._task_source(run), run,
        service.settings.screenshots_root, "verify",
    )
    # Work is pushed and the CR is open — the worktree is no longer
    # needed. Clean it up (closing the done-run leak, US3/FR-017).
    await service._teardown_workspace(run)
