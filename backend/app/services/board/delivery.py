"""Delivery: push a clean verification's branch and open a change request
(feature 026, T069).

Deliberately automatic — no human gate, unlike ``decomposition_gate``
(T068). Pushing kestrel's own worktree branch and opening a *draft*
change request is low-risk and reversible: nothing merges on its own,
and a draft signals "here it is" without implying it already passed
human review.

A later delivery (requested changes, a clarification, a CI repair)
pushes to the same change request, rewrites kestrel's section of its
description (``delivery_body``), and comments on it: the commits it
brought, or that nothing needed changing, with the coder's summary
(``delivery_rounds``).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.models_board import Workflow
from app.ports import CodeHost
from app.services.board.delivery_body import kestrel_section, read_screenshots
from app.services.board.delivery_rounds import (
    RoundHistory,
    round_comment,
    round_line,
)
from app.services.board.workspace import WorkspaceService

_log = logging.getLogger("kestrel.board.delivery")


@dataclass(frozen=True)
class Delivered:
    """Where the delivery went, and its round's line for the history.

    :param location: A change-request URL for a new one, or a note.
    :param line: The later round's line, or ``None`` for the first
        delivery (and for a code host without change requests).
    """

    location: str
    line: str | None = None


async def deliver(
    workflow: Workflow,
    code_host: CodeHost,
    workspace: WorkspaceService,
    rounds: RoundHistory | None = None,
) -> Delivered:
    """Push *workflow*'s branch and open (or update) its change request.

    :raises GitError: If the underlying git push fails.
    """
    rounds = rounds or RoundHistory()
    commits = await workspace.unpushed_commits(workflow.id) or []
    await _warn_on_stray_files(workflow, workspace)
    branch = await workspace.push(workflow.id, code_host.git_credential())
    if not code_host.supports_change_requests():
        return Delivered(f"local branch published: {branch}")
    number = workflow.change_request_number
    line = round_line(rounds.current, commits) if number is not None else None
    history = rounds.lines + ((line,) if line else ())
    section = kestrel_section(
        workflow.task_ref, history,
        await read_screenshots(workspace, workflow.id),
        lambda path: code_host.file_url(workflow.repo, branch, path),
    )
    if number is None:
        return Delivered(await code_host.open_change_request(
            workflow.repo, head=branch, base=workflow.base_branch,
            title=f"{workflow.title} ({workflow.task_ref})",
            body=section, draft=True,
        ))
    await code_host.write_kestrel_section(workflow.repo, number, section)
    await code_host.comment_on_change_request(
        workflow.repo, number, round_comment(rounds.current, commits)
    )
    return Delivered(f"updated existing change request #{number}", line)


async def _warn_on_stray_files(
    workflow: Workflow, workspace: WorkspaceService
) -> None:
    """Say so when the branch commits agent tooling under ``.kestrel/``."""
    stray = await workspace.stray_kestrel_files(
        workflow.id, workflow.base_branch
    )
    if stray:
        _log.warning(
            "workflow %s: the branch commits files under .kestrel/ that are "
            "not screenshots (agent tooling?): %s",
            workflow.id, ", ".join(stray),
            extra={"workflow_id": workflow.id},
        )
