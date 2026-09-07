"""Tests for PRD delivery + PRD-rejection dismissal (feature 003, US2)."""
from __future__ import annotations

import pytest

from app.config import Settings
from app.services.workflows import WorkflowService
from app.storage.registry import SessionRegistry
from app.storage.workflow_registry import WorkflowRegistry
from tests.conftest import (
    _FakeDismissals,
    _FakeGit,
    _FakeGitHub,
    _FakeNotifier,
    _FakeRunner,
    _refine_noquestions,
    _wait,
)


class _FakeJiraSource:
    """A Jira TaskSource stand-in recording attachments + comments."""

    def __init__(self, body: str) -> None:
        self._body = body
        self.attachments: list[tuple[str, str]] = []
        self.comments: list[str] = []
        #: Follow-up RFCs created via create_subtask (gap_analysis,
        #: feature 012), each (title, body).
        self.subtasks: list[tuple[str, str]] = []

    async def get_task(self, ref):
        from app.ports import Task
        return Task(ref=ref, title="RFC title", body=self._body)

    async def post_comment(self, ref, body):
        self.comments.append(body)
        return "url"

    async def attach(self, ref, name, content):
        self.attachments.append((name, content))

    async def publish_refined(self, ref, content):
        self.attachments.append(("PRD.md", content))

    async def create_subtask(self, parent_ref, title, body):
        self.subtasks.append((title, body))
        return f"RFC-{len(self.subtasks) + 1}"

    def deep_link_ref(self, ref):
        return f"https://jira/browse/{ref}"


class _FakeJiraHost:
    async def get_default_branch(self, repo):
        return "main"

    def clone_remote(self, repo):
        return f"https://gitlab/{repo}.git"

    def git_credential(self):
        return ("oauth2", "glpat")

    async def open_change_request(self, repo, *, head, base, title, body,
                                  draft=True):
        return "https://gitlab/mr/1"


def _jira_svc(source, host, runner, dismissals=None):
    return WorkflowService(
        settings=Settings(git_base="https://github.com", github_token="t"),
        sessions=runner.sessions,
        workflows=WorkflowRegistry(),
        backends=runner,
        git=_FakeGit(),
        github=_FakeGitHub(),
        notifier=_FakeNotifier(),
        dismissals=dismissals,
        sources={"jira-issue": source},
        code_hosts={"jira-issue": host},
    )


@pytest.mark.asyncio
async def test_jira_run_attaches_prd_on_approval() -> None:
    """Ensure an approved PRD is attached to the Jira RFC (FR-011).

    Approval publishes the PRD immediately, before gap_analysis ever runs
    — so this still holds even though a plain ticket's run now always
    ends by decomposing at gap_analysis rather than reaching design/
    code/verify/deliver (FR-014); there is no change-request link to
    post back for the original ticket any more, only the
    technical-analysis summary (FR-012).
    """
    source = _FakeJiraSource(body="vague RFC")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "<UNDERSTANDING>the PRD</UNDERSTANDING>",
        *_refine_noquestions("the PRD"),
        "<TECH_ANALYSIS>analysis</TECH_ANALYSIS>",  # gap_analysis
        "<CONTAINMENT>{\"verdicts\": []}</CONTAINMENT>",  # critic
    ])
    svc = _jira_svc(source, _FakeJiraHost(), runner)
    wid = await svc.create(
        "team/svc", None, source="jira-issue", task_ref="RFC-1",
        base_branch="main",
    )
    await _wait(lambda: svc.get(wid).status == "awaiting_describe_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "decomposed")
    assert ("PRD.md", "the PRD") in source.attachments
    # The technical-analysis summary was posted back to the RFC.
    assert any("analysis" in c for c in source.comments)


@pytest.mark.asyncio
async def test_github_run_publishes_refined_to_issue_body() -> None:
    """Ensure a GitHub run writes the refined body + sentinel (not attach).

    See test_jira_run_attaches_prd_on_approval: publish happens at
    approval time, before the run decomposes at gap_analysis (FR-014).
    """
    gh = _FakeGitHub(body="vague issue")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "<UNDERSTANDING>refined</UNDERSTANDING>",
        *_refine_noquestions("refined"),
        "<TECH_ANALYSIS>analysis</TECH_ANALYSIS>",  # gap_analysis
        "<CONTAINMENT>{\"verdicts\": []}</CONTAINMENT>",  # critic
    ])
    svc = WorkflowService(
        settings=Settings(git_base="https://github.com", github_token="t"),
        sessions=runner.sessions, workflows=WorkflowRegistry(),
        backends=runner, git=_FakeGit(), github=gh, notifier=_FakeNotifier(),
    )
    wid = await svc.create("o/r", 5, source="github-issue")
    await _wait(lambda: svc.get(wid).status == "awaiting_describe_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "decomposed")
    assert gh.updated is not None and "kestrel:refined" in gh.updated


@pytest.mark.asyncio
async def test_prd_rejection_ends_rejected_and_writes_dismissal() -> None:
    """Ensure a rejected PRD ends the run rejected + records a dismissal."""
    source = _FakeJiraSource(body="vague RFC")
    dismissals = _FakeDismissals()
    runner = _FakeRunner(
        SessionRegistry(),
        outputs=[
            "<UNDERSTANDING>prd</UNDERSTANDING>",
            *_refine_noquestions("prd"),
        ],
    )
    svc = _jira_svc(source, _FakeJiraHost(), runner, dismissals=dismissals)
    wid = await svc.create(
        "team/svc", None, source="jira-issue", task_ref="RFC-1",
        base_branch="main",
    )
    await _wait(lambda: svc.get(wid).status == "awaiting_describe_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.reject(wid)
    await _wait(lambda: svc.get(wid).status == "rejected")
    assert dismissals.is_dismissed("RFC-1")
