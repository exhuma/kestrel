"""Every task source traverses the identical workflow (feature 003, US4)."""
from __future__ import annotations

import pytest

from app.config import Settings
from app.schemas import WorkflowDetail, WorkflowSummary
from app.services.workflows import WorkflowService
from app.storage.registry import SessionRegistry
from app.storage.workflow_registry import WorkflowRegistry
from tests.test_prd_delivery import _FakeJiraHost, _FakeJiraSource
from tests.test_workflow_service import (
    _FakeGit,
    _FakeGitHub,
    _FakeNotifier,
    _FakeRunner,
    _refine_noquestions,
    _verdict,
    _wait,
)


async def _drive_and_record(svc: WorkflowService, wid: str) -> list[str]:
    seen: list[str] = []

    # Poll the run's status transitions by watching the registry.
    async def watch() -> None:
        last = None
        while True:
            st = svc.get(wid).status
            if st != last:
                seen.append(st)
                last = st
            if st in ("done", "failed", "rejected", "escalated"):
                return
            import asyncio
            await asyncio.sleep(0.01)

    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await watch()
    return seen


@pytest.mark.asyncio
async def test_github_and_jira_traverse_identical_status_sequence() -> None:
    """Ensure a GitHub run and a Jira run traverse the same phases/gates."""
    # GitHub run.
    gh_runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("prd"), "<PLAN>d</PLAN>", "coded",
        _verdict(accept=True),
    ])
    gh_svc = WorkflowService(
        settings=Settings(git_base="https://github.com", github_token="t"),
        sessions=gh_runner.sessions, workflows=WorkflowRegistry(),
        backends=gh_runner, git=_FakeGit(), github=_FakeGitHub(body="vague"),
        notifier=_FakeNotifier(),
    )
    gh_wid = await gh_svc.create("o/r", 5)
    gh_seq = await _drive_and_record(gh_svc, gh_wid)

    # Jira run (Jira task source + GitLab-style code host).
    jira_runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("prd"), "<PLAN>d</PLAN>", "coded",
        _verdict(accept=True),
    ])
    jira_svc = WorkflowService(
        settings=Settings(git_base="https://github.com", github_token="t"),
        sessions=jira_runner.sessions, workflows=WorkflowRegistry(),
        backends=jira_runner, git=_FakeGit(), github=_FakeGitHub(),
        notifier=_FakeNotifier(),
        sources={"jira-issue": _FakeJiraSource(body="vague RFC")},
        code_hosts={"jira-issue": _FakeJiraHost()},
    )
    jira_wid = await jira_svc.create(
        "team/svc", None, source="jira-issue", task_ref="RFC-1",
        base_branch="main",
    )
    jira_seq = await _drive_and_record(jira_svc, jira_wid)

    # Identical process; only the bound source/host and surface differ.
    assert gh_seq == jira_seq
    assert gh_seq[-1] == "done"


def test_workflow_schemas_do_not_expose_source_or_task_ref() -> None:
    """Ensure source/task_ref are never in the API schema (FR-026)."""
    for model in (WorkflowDetail, WorkflowSummary):
        fields = set(model.model_fields)
        assert "source" not in fields
        assert "task_ref" not in fields
    # issue_number is nullable so a Jira run (no numeric id) serialises.
    assert WorkflowDetail.model_fields["issue_number"].annotation == (int | None)
