"""Delivery: push a clean verification's branch and open a change request
(feature 026, T069).

Deliberately automatic — no human gate, unlike ``decomposition_gate``
(T068). Pushing kestrel's own worktree branch and opening a *draft*
change request is low-risk and reversible: nothing merges on its own,
and a draft signals "here it is" without implying it already passed
human review. A workflow's required CI checks (T052,
``app/services/board/ci_poll.py``) may trigger further deliveries after
this one — each just pushes and updates the existing change request
rather than opening a second one, decided from ``workflow``'s own
``change_request_number`` (set by the caller after the first delivery).
Only the first delivery writes the body, with the branch's screenshots
(feature 043, ``delivery_body``); a later one leaves it as it is.
"""
from __future__ import annotations

from app.models_board import Workflow
from app.ports import CodeHost
from app.services.board.delivery_body import pr_body, read_screenshots
from app.services.board.workspace import WorkspaceService


async def deliver(
    workflow: Workflow, code_host: CodeHost, workspace: WorkspaceService
) -> str:
    """Push *workflow*'s branch and open (or update) its delivery.

    :returns: A human-readable delivery location for the write-back
        comment and (via ``app.services.github.change_request_number``)
        for the caller to record — a change-request URL, or a "local
        branch published"/"updated" note for a code host that can't open
        one (the local task source's bare-repo target) or already has.
    :raises GitError: If the underlying git push fails.
    """
    branch = await workspace.push(workflow.id, code_host.git_credential())
    if not code_host.supports_change_requests():
        return f"local branch published: {branch}"
    if workflow.change_request_number is not None:
        number = workflow.change_request_number
        return f"updated existing change request #{number}"
    screenshots = await read_screenshots(workspace, workflow.id)
    body = pr_body(
        workflow.task_ref,
        screenshots,
        lambda path: code_host.file_url(workflow.repo, branch, path),
    )
    return await code_host.open_change_request(
        workflow.repo,
        head=branch,
        base=workflow.base_branch,
        title=f"{workflow.title} ({workflow.task_ref})",
        body=body,
        draft=True,
    )
