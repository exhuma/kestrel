"""The describe -> refine -> gap_analysis -> design -> code/verify ->
deliver run state machine."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.backends.base import TurnRequest
from app.models_workflow import Step, StepSession, WorkflowRun
from app.policy import get_policy
from app.services.feedback.dispatch import drain_feedback
from app.services.github import change_request_number
from app.services.time_tracking import set_clock
from app.services.workflow_text import (
    extract_boundary,
    extract_plan,
    has_sentinel,
    has_subtask_sentinel,
)
from app.services.workflows import interview, screenshots
from app.services.workflows.driver.code_verify import code_and_verify
from app.services.workflows.driver.describe import describe
from app.services.workflows.driver.escalate import fail_active_steps
from app.services.workflows.driver.gap_analysis import run_gap_analysis
from app.services.workflows.prompts import (
    DESIGN_PROMPT,
    MID_RUN_FEEDBACK_APPENDIX,
)
from app.services.workflows.sessions import _bind
from app.services.workflows.shared import _TRANSIENT, _now_utc, _Rejected

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
            workflow_id, run.repo, run.issue_number,
            run.status,
        )
        run.status = "failed"
        run.error = str(exc)
        fail_active_steps(service, run)
        service._safe_save(run)
        await service._teardown_workspace(run)


def _seed_from_sentinel(run: WorkflowRun, body: str) -> bool:
    """Pre-mark steps done per the ticket body's sentinel, if any.

    A ``SUBTASK_SENTINEL`` body (a gap_analysis follow-up task, feature
    012) skips describe/refine/gap_analysis entirely, landing at design.
    A plain ``SENTINEL`` body (an already-refined ticket, e.g. a rerun)
    skips describe/refine only, landing at gap_analysis. Either way the
    approved-PRD-equivalent text is seeded at steps[1], the slot design
    reads from.

    :returns: True if any steps were pre-marked (the caller must persist
        and re-enter ``continue_run`` with no fresh issue body); False
        for an ordinary ticket with neither sentinel.
    """
    if has_subtask_sentinel(body):
        for idx in (0, 1, 2):
            run.steps[idx].status = "done"
        run.steps[1].deliverable = body
        return True
    if has_sentinel(body):
        run.steps[0].status = "done"
        run.steps[1].status = "done"
        run.steps[1].deliverable = body
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

        if _seed_from_sentinel(run, task.body):
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
        fail_active_steps(service, run)
        service._safe_save(run)
        await service._teardown_workspace(run)


async def continue_run(
    service: "WorkflowService",
    run: WorkflowRun,
    issue_body: str | None = None,
) -> None:
    """Run every unfinished phase, then deliver.

    describe (understanding gate) -> refine (PRD approval gate) ->
    gap_analysis (gateless, run-terminating on success) -> design ->
    autonomous code<->verify loop -> deliver. Everything after PRD
    approval is gateless (FR-007/FR-014); gap_analysis, once genuinely
    run (not pre-marked done by a sentinel skip — see
    :func:`_seed_from_sentinel`), always ends the run, so the caller
    returns rather than falling through to design. The code<->verify
    loop may also escalate instead of delivering (FR-018/FR-020).

    Each not-yet-done step is preceded by a ``drain_feedback`` call
    (feature 013, US2/US3): a no-op on a fresh drive (nothing queued
    yet), but on a resumed/revived run it folds in whatever ticket or
    triage feedback was queued for this run with nowhere else to land —
    never mid-turn, only at a boundary this loop already reaches
    naturally. ``gap_analysis`` is a fan-out/reconcile/critic turn, not
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
        await run_gap_analysis(service, run)
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
            seed = (
                await service._task_source(run).get_task(run.task_ref)
            ).body
        if feedback:
            seed += MID_RUN_FEEDBACK_APPENDIX.format(feedback=feedback)
        issue, accumulated = await interview.run_interview(
            service, run, seed
        )
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
        service._retire_sessions(run, step)  # chips off at the gate
        step.status = "awaiting_approval"
        run.status = "awaiting_refine_approval"
        set_clock(run, "waiting", _now_utc())
        service._save(run)


async def design(
    service: "WorkflowService", run: WorkflowRun, feedback: str = ""
) -> None:
    """Run the designer: produce a high-level design/plan. Gateless.

    :param feedback: Ticket feedback drained at the boundary just before
        this step started (feature 013, US2) — folded into the prompt
        alongside the PRD, when present.
    """
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
    result = await service._run_turn_tracked(
        run,
        service.backends.backend_for(Step.DESIGN),
        TurnRequest(
            prompt=prompt,
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
    service._retire_sessions(run, step)
    step.status = "done"
    service._save(run)


def _change_request_texts(run: WorkflowRun) -> tuple[str, str, str]:
    """(commit_msg, cr_title, cr_body), source-aware.

    A GitHub run closes its issue (#n); a Jira run references the RFC key
    (the ticket is in Jira).
    """
    if run.issue_number is not None:
        return (
            f"Implement #{run.issue_number}",
            f"{run.issue_title} (#{run.issue_number})",
            f"Closes #{run.issue_number}\n\nOpened by kestrel.",
        )
    return (
        f"Implement {run.task_ref}",
        f"{run.issue_title} ({run.task_ref})",
        f"Implements {run.task_ref}\n\nOpened by kestrel.",
    )


async def _open_or_confirm_change_request(
    service: "WorkflowService", run: WorkflowRun
) -> bool:
    """
    Open the change request, unless one is already open for this run.

    Idempotent for a resumed run (feature 013, US3): when ``run.pr_number``
    is already set — this run has been through ``deliver()`` once before
    and the caller (``feedback/dispatch.py``) only resumes it when that
    request is still open — this is a second delivery pass onto the SAME
    branch. Opening a second change request would fork the review thread
    the human is already on, so this skips straight to just having pushed.

    :returns: ``True`` if a NEW change request was opened this call
        (governs which landing comment ``deliver`` posts).
    """
    if run.pr_number is not None:
        return False
    _, cr_title, cr_body = _change_request_texts(run)
    run.pr_url = await service._code_host(run).open_change_request(
        run.repo, head=run.branch, base=run.base_branch,
        title=cr_title, body=cr_body,
    )
    run.pr_number = change_request_number(run.pr_url)
    return True


async def deliver(service: "WorkflowService", run: WorkflowRun) -> None:
    """Commit, push, open (or confirm) the change request, and finish."""
    run.status = "opening_pr"
    service._save(run)
    commit_msg, _, _ = _change_request_texts(run)
    # The coder (or the loop's safety net) may already have committed
    # everything — e.g. a run accepted on its first round with no
    # trailing artifact writes since. An empty `git commit` errors, so
    # only commit when the tree is actually still dirty.
    if (await service.git.diff(run.workspace)).strip():
        await service.git.commit_all(run.workspace, commit_msg)
    await service.git.push(
        run.workspace, run.branch, service._code_host(run).git_credential()
    )
    opened = await _open_or_confirm_change_request(service, run)
    run.status = "done"
    service._save(run)
    # Post the change-request link to the ticket (best-effort — FR-019).
    # A resumed run (idempotent path above) gets an "Updated" comment
    # instead — never a second "opened" announcement for the same request.
    message = (
        f"Change request opened: {run.pr_url}" if opened
        else f"Updated the change request: {run.pr_url}"
    )
    try:
        await service._task_source(run).post_comment(run.task_ref, message)
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
