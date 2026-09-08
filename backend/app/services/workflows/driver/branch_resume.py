"""Resume an existing branch for review-feedback-driven re-entry.

``resume_with_feedback`` restores an already-delivered run's worktree onto
the SAME branch ``deliver()`` pushed (feature 013, US3), runs the triage
turn to decide which step the feedback concerns, rewinds the run to that
step, queues the triage-derived instruction where that step's own
existing feedback-drain point (US2's ``drain_feedback``) will pick it up,
and re-enters ``continue_run`` — the same drive loop every run goes
through, just picking up mid-pipeline instead of from a fresh clone.

The worktree-provisioning step is factored into two strategies —
:func:`_provision_existing_branch` (a run that has already pushed, i.e.
``run.pr_number`` is set) and :func:`_provision_fresh_branch` (an
``escalated`` run, which never got that far: feature 013, US4) — chosen
by :func:`resume_with_feedback` itself, so triage/rewind/continue_run
below either one stay identical regardless of which run reached this
seam.

Callers reach this through ``WorkflowService.resume_with_feedback``, not
directly: that thin wrapper owns spawning this as a tracked driver task
(mirroring ``create()``'s own control-setup + ``_spawn_driver`` pattern)
so ``app.services.feedback.dispatch`` — which every driver submodule is
itself imported by (see ``feedback/dispatch.py``'s module docstring on
the circular-import trap) — never needs to import this module directly.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.models_workflow import Step, WorkflowRun
from app.persistence.tables import FeedbackItemRow
from app.services.feedback.triage import triage_feedback
from app.services.workflows import artifacts
from app.services.workflows.driver import continue_run
from app.services.workflows.reentry import rewind_to

if TYPE_CHECKING:
    from app.services.workflows import WorkflowService

_logger = logging.getLogger(__name__)


async def _provision_existing_branch(
    service: "WorkflowService", run: WorkflowRun
) -> None:
    """Restore ``run``'s worktree onto its own, already-pushed branch.

    Refetches the mirror first (a human may have pushed their own commits
    onto the PR branch since ``deliver()`` last ran) so
    ``add_worktree_existing`` resumes a genuinely current branch.
    """
    code_host = service._code_host(run)
    remote = code_host.clone_remote(run.repo)
    mirror = service._mirror_dir(run.repo)
    await service.git.ensure_mirror(remote, mirror, code_host.git_credential())
    await service.git.add_worktree_existing(mirror, run.workspace, run.branch)


async def _provision_fresh_branch(
    service: "WorkflowService", run: WorkflowRun
) -> None:
    """Provision a brand-new worktree for ``run``, fresh off its base branch.

    The ``escalated`` fallback (feature 013, US4): escalation never
    pushes a branch (:func:`app.services.workflows.driver.escalate.escalate`
    tears the worktree down without delivering), so there is nothing to
    resume *onto* — this mirrors ``drive()``'s own initial
    ``add_worktree`` rather than :func:`_provision_existing_branch`.
    Force-deletes any local ref for ``run.branch`` first (best-effort,
    idempotent — see ``GitService.delete_local_branch``): the run's own
    earlier attempt already created that local branch in the mirror
    before escalating, and ``add_worktree -b`` fails outright on a branch
    that already exists.
    """
    code_host = service._code_host(run)
    remote = code_host.clone_remote(run.repo)
    mirror = service._mirror_dir(run.repo)
    await service.git.ensure_mirror(remote, mirror, code_host.git_credential())
    await service.git.delete_local_branch(mirror, run.branch)
    await service.git.add_worktree(
        mirror, run.workspace, run.base_branch, run.branch
    )


def _queue_triage_instruction(
    service: "WorkflowService", run: WorkflowRun, instruction: str
) -> None:
    """
    Queue ``instruction`` for the target step's own existing drain point.

    Reuses feature 013 US2's ``FeedbackStore``/``drain_feedback`` plumbing
    rather than inventing a second delivery path: whichever step
    :func:`rewind_to` targeted will drain this the same way it already
    drains ordinary mid-run ticket feedback, the first time its own
    boundary is reached. A no-op when the service has no feedback store
    configured (mirrors ``drain_feedback``'s own safe no-op).
    """
    store = service.feedback_store
    if store is None or not instruction:
        return
    item = FeedbackItemRow(
        external_id=f"triage:{run.id}:{uuid.uuid4().hex[:8]}",
        workflow_id=run.id,
        task_ref=run.task_ref,
        origin="review",
        author="kestrel-triage",
        body=instruction,
        state="queued",
        created_at=datetime.now(timezone.utc),
    )
    store.claim(item)


async def resume_with_feedback(
    service: "WorkflowService", workflow_id: str, feedback_body: str,
) -> None:
    """
    Resume ``workflow_id`` to apply feedback, reviving it from wherever
    it last left off.

    Mirrors mirror-``ensure`` -> (``add_worktree_existing`` or, for an
    ``escalated`` run with no PR yet, a fresh ``add_worktree`` off
    ``base_branch`` — feature 013, US4) -> ``_ensure_artifact_dir`` ->
    triage -> :func:`rewind_to` -> ``continue_run`` (feature 013, US3/
    US4). Called via ``WorkflowService.resume_with_feedback``, which has
    already set up this run's ``_control`` entry before spawning this as
    a driver task — mirroring ``create()``'s own control-setup +
    ``_spawn_driver`` order.

    :param service: The owning ``WorkflowService``.
    :param workflow_id: The run to resume — either already has a branch
        (has been through at least one ``drive()``/``deliver()`` pass,
        ``run.pr_number`` is set) or is ``escalated`` (never delivered,
        so ``run.pr_number`` is ``None`` — the sole signal this function
        branches on to pick a provisioning strategy).
    :param feedback_body: The raw feedback text driving this resume.
    """
    run = service.get(workflow_id)
    if run.pr_number is None:
        await _provision_fresh_branch(service, run)
    else:
        await _provision_existing_branch(service, run)
    service._ensure_artifact_dir(run)

    diffstat = await service.git.diff_stat(
        run.workspace, exclude=artifacts.ARTIFACT_ROOT, ref=run.base_branch
    )
    triage = await triage_feedback(
        service, run, feedback_body, diffstat=diffstat
    )
    step = Step(triage["step"])
    _logger.info(
        "resume_with_feedback run=%s target=%s reason=%s",
        run.id, step, triage["reason"],
    )
    rewind_to(run, step, triage["instruction"])
    _queue_triage_instruction(service, run, triage["instruction"])

    run.status = "pending"
    service._save(run)
    await continue_run(service, run)
