"""Change-request delivery helpers for workflow runs."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.services.github import change_request_number
from app.services.workflows import screenshots

if TYPE_CHECKING:
    from app.models_workflow import WorkflowRun
    from app.services.workflows import WorkflowService

_logger = logging.getLogger(__name__)


def _change_request_texts(run: "WorkflowRun") -> tuple[str, str, str]:
    """Return commit, title, and body text appropriate for a run's source."""
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


def _supports_change_requests(code_host) -> bool:
    """Return host capability while retaining test doubles' default support."""
    return getattr(code_host, "supports_change_requests", lambda: True)()


async def _open_or_confirm_change_request(
    service: "WorkflowService", run: "WorkflowRun"
) -> bool:
    """Open a request unless the run already has one.

    Return whether the request was newly created.
    """
    code_host = service._code_host(run)
    if not _supports_change_requests(code_host):
        run.pr_url = f"local branch published: {run.branch}"
        return True
    if run.pr_number is not None:
        return False
    _, title, body = _change_request_texts(run)
    run.pr_url = await code_host.open_change_request(
        run.repo,
        head=run.branch,
        base=run.base_branch,
        title=title,
        body=body,
    )
    run.pr_number = change_request_number(run.pr_url)
    return True


def _delivery_message(run: "WorkflowRun", opened: bool, code_host) -> str:
    """Return the ticket comment describing this delivery's destination."""
    if not _supports_change_requests(code_host):
        return f"Branch published locally: {run.branch}"
    if opened:
        return f"Change request opened: {run.pr_url}"
    return f"Updated the change request: {run.pr_url}"


async def deliver(service: "WorkflowService", run: "WorkflowRun") -> None:
    """Commit, push, announce the change request, and clean up the workspace."""
    run.status = "opening_pr"
    service._save(run)
    commit_message, _, _ = _change_request_texts(run)
    if (await service.git.diff(run.workspace)).strip():
        await service.git.commit_all(run.workspace, commit_message)
    await service.git.push(
        run.workspace, run.branch, service._code_host(run).git_credential()
    )
    service.record_artifact(run, "remote_branch", run.branch, run.branch)
    opened = await _open_or_confirm_change_request(service, run)
    run.status = "awaiting_ci" if service.required_ci_statuses(run) else "done"
    service._save(run)
    await _post_delivery_comment(service, run, opened)
    await screenshots.upload_screenshots(
        service._task_source(run),
        run,
        service.settings.screenshots_root,
        "verify",
    )
    await service._teardown_workspace(run)


async def _post_delivery_comment(
    service: "WorkflowService", run: "WorkflowRun", opened: bool
) -> None:
    """Post the delivery location without failing an already-delivered run."""
    message = _delivery_message(run, opened, service._code_host(run))
    try:
        await service.post_comment(run, message, "delivery comment")
    except Exception:
        _logger.exception("failed to post CR link for %s", run.task_ref)
