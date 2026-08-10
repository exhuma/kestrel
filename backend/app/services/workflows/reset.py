"""Run-teardown family: abandon, delete, cleanup, rerun (feature 002/008).

Split out of ``service.py`` to keep that module within its length budget,
following the existing ``artifacts``/``gate``/``driver`` pattern: free
functions taking the owning ``WorkflowService`` explicitly rather than
methods, called from thin wrapper methods there.

All four share one core, :func:`abandon_common`: cancel the run's driver,
drop its sessions/workspace, and remove its registry record. ``delete``,
``cleanup``, and ``rerun`` each layer different remote-facing behavior on
top of that shared core — see each function's docstring.
"""
from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from app.models_workflow import WorkflowRun
from app.services.exceptions import RerunNotAllowedError

if TYPE_CHECKING:
    from app.services.workflows import WorkflowService


async def abandon_common(
    service: "WorkflowService", workflow_id: str
) -> WorkflowRun:
    """Cancel a run and drop every trace of its local work.

    Shared by :func:`delete`, :func:`cleanup`, and :func:`rerun`: cancels
    the driver task, then terminates and deletes every session that ran in
    the run's workspace (the coordinator, each specialist, plan,
    implement) — killing any in-flight subprocess and dropping the
    session's records, not just the latest one a step still points at.
    Forgets the control state, removes the registry record and its
    persisted rows, and deletes the cloned workspace. Deliberately never
    touches GitHub itself — callers decide separately whether to reach the
    remote (e.g. branch deletion).

    :param service: The owning :class:`WorkflowService`.
    :param workflow_id: Id of the run to abandon.
    :raises WorkflowNotFoundError: If the run is unknown.
    """
    run = service.get(workflow_id)
    task = service._tasks.pop(workflow_id, None)
    if task is not None and not task.done():
        task.cancel()
        with contextlib.suppress(BaseException):  # cancellation/late error
            await task
    # Every session a run spawned records cwd == run.workspace (the same
    # attribution SessionService.list_summaries uses), so match on that
    # to catch them all — not just the latest id each step points at.
    # Union in the step pointers defensively.
    session_ids = {
        record.session_id
        for record in service.sessions.list()
        if run.workspace and record.cwd == run.workspace
    }
    session_ids.update(
        step.session_id for step in run.steps if step.session_id
    )
    for session_id in session_ids:
        # A session may have run on any backend; each ignores ids it
        # doesn't own, so ask them all to stop it.
        for backend in service.backends.backends():
            backend.terminate(session_id)
        if service.sessions.get(session_id) is not None:
            service.sessions.remove(session_id)
    service._control.pop(workflow_id, None)
    service.workflows.remove(workflow_id)
    # Explicit user action: drop the workspace even in workflow_debug.
    await service._teardown_workspace(run, force=True)
    return run


async def delete(service: "WorkflowService", workflow_id: str) -> None:
    """
    Abandon a run: cancel it and drop every trace of its local work.

    Deliberately never touches GitHub — abandoning drops work only, it
    does not close issues, comment, or open/close PRs, and it leaves
    the branch (local mirror and remote) exactly as it was.

    :param service: The owning :class:`WorkflowService`.
    :param workflow_id: Id of the run to abandon.
    :raises WorkflowNotFoundError: If the run is unknown.
    """
    run = await abandon_common(service, workflow_id)
    # Dismiss the issue so a still-labelled ingested run is not
    # re-created by the webhook or reconciliation (feature 002,
    # FR-008a). Cleared when the trigger label is removed.
    if service.dismissals is not None:
        service.dismissals.add(
            run.task_ref or f"{run.repo}#{run.issue_number}"
        )


async def _delete_branch(service: "WorkflowService", run: WorkflowRun) -> None:
    """Force-delete a run's branch from both the local mirror and remote."""
    mirror = service._mirror_dir(run.repo)
    await service.git.delete_local_branch(mirror, run.branch)
    await service.git.delete_remote_branch(
        mirror, run.branch, service._code_host(run).git_credential()
    )


async def cleanup(service: "WorkflowService", workflow_id: str) -> None:
    """
    Fully reset a run so its task is picked up as new on the next poll.

    Unlike :func:`delete`, this reaches the remote: it also force-
    deletes the run's branch from both kestrel's local mirror and the
    actual GitHub/GitLab remote (if it was ever pushed), and clears
    any dismissal instead of adding one — so ingestion/reconciliation
    treats the underlying ticket as brand new.

    :param service: The owning :class:`WorkflowService`.
    :param workflow_id: Id of the run to clean up.
    :raises WorkflowNotFoundError: If the run is unknown.
    """
    run = await abandon_common(service, workflow_id)
    await _delete_branch(service, run)
    if service.dismissals is not None:
        service.dismissals.clear(
            run.task_ref or f"{run.repo}#{run.issue_number}"
        )


async def rerun(service: "WorkflowService", workflow_id: str) -> str:
    """
    Discard a run and immediately start a fresh one for the same task.

    Refused unless the run's task source is private (feature 008) — the
    safety property that keeps a public GitHub/Jira ticket's history
    append-only. Otherwise identical to :func:`cleanup` (abandon,
    force-delete the branch, clear the dismissal) except the replacement
    run starts synchronously instead of waiting for the next poll —
    calling ``service.create`` directly rather than routing through
    ``IngestionService`` sidesteps the circular dependency that service
    already has back onto this one.

    :param service: The owning :class:`WorkflowService`.
    :param workflow_id: Id of the run to discard and replace.
    :raises WorkflowNotFoundError: If the run is unknown.
    :raises RerunNotAllowedError: If the run's task source is public.
    """
    run = service.get(workflow_id)
    if service._task_source(run).visibility() != "private":
        raise RerunNotAllowedError(workflow_id)
    run = await abandon_common(service, workflow_id)
    await _delete_branch(service, run)
    task_ref = run.task_ref or f"{run.repo}#{run.issue_number}"
    if service.dismissals is not None:
        service.dismissals.clear(task_ref)
    return await service.create(
        run.repo,
        run.issue_number,
        source=run.source,
        task_ref=task_ref,
        base_branch=run.base_branch or None,
    )
