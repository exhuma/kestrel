"""Delivery: push a clean verification's branch and open a change request
(feature 026, T069).

Deliberately automatic — no human gate, unlike ``decomposition_gate``
(T068). Pushing kestrel's own worktree branch and opening a *draft*
change request is low-risk and reversible: nothing merges on its own,
and a draft signals "here it is" without implying it already passed
human review. A workflow ends here; there is no further board-domain
step once delivery succeeds.
"""
from __future__ import annotations

from app.models_board import Workflow
from app.ports import CodeHost
from app.services.board.workspace import WorkspaceService


async def deliver(
    workflow: Workflow, code_host: CodeHost, workspace: WorkspaceService
) -> str:
    """Push *workflow*'s branch and open (or describe) its delivery.

    :returns: A human-readable delivery location for the write-back
        comment — a change-request URL, or a "local branch published"
        note for a code host that can't open one (the local task
        source's bare-repo target).
    :raises GitError: If the underlying git push fails.
    """
    branch = await workspace.push(workflow.id, code_host.git_credential())
    if not code_host.supports_change_requests():
        return f"local branch published: {branch}"
    return await code_host.open_change_request(
        workflow.repo,
        head=branch,
        base=workflow.base_branch,
        title=f"{workflow.title} ({workflow.task_ref})",
        body=f"Implements {workflow.task_ref}\n\nOpened by kestrel.",
        draft=True,
    )
