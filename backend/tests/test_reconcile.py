"""Tests for the poll-reconciliation service."""
from __future__ import annotations

import pytest

from app.config import Settings
from app.models_workflow import WorkflowRun
from app.services.exceptions import GitHubError
from app.services.github import Issue
from app.services.ingestion import IngestionService
from app.services.reconcile import ReconcileService


class _FakeWorkflows:
    def __init__(self) -> None:
        self.runs: list[WorkflowRun] = []
        self.created: list[tuple[str, int]] = []

    def list(self) -> list[WorkflowRun]:
        return self.runs

    async def create(self, repo, issue_number, *, source="manual"):
        rid = f"wf-{len(self.created)}"
        self.created.append((repo, issue_number))
        self.runs.append(
            WorkflowRun(id=rid, repo=repo, issue_number=issue_number,
                        source=source)
        )
        return rid


class _FakeDismissals:
    def __init__(self) -> None:
        self._d: set[str] = set()

    def add(self, task_ref):
        self._d.add(task_ref)

    def is_dismissed(self, task_ref):
        return task_ref in self._d

    def clear(self, task_ref):
        self._d.discard(task_ref)

    def all(self):
        return list(self._d)


class _FakeGitHub:
    def __init__(self, issues=None, fail=False) -> None:
        self._issues = issues or []
        self._fail = fail
        self.calls = 0

    async def list_issues_by_label(self, repo, label, *, state="open"):
        self.calls += 1
        if self._fail:
            raise GitHubError("unreachable")
        return list(self._issues)


def _svc(github, wf, dismissals) -> ReconcileService:
    settings = Settings(
        _env_file=None, watched_repos=["o/r"], trigger_label="kestrel"
    )
    ingestion = IngestionService(settings, wf, dismissals)
    return ReconcileService(settings, github, ingestion, dismissals)


@pytest.mark.asyncio
async def test_starts_missing_run_once_and_is_idempotent() -> None:
    """Ensure a labelled issue starts one run; a second cycle starts none."""
    wf, dis = _FakeWorkflows(), _FakeDismissals()
    svc = _svc(_FakeGitHub(issues=[Issue(5, "t", "b")]), wf, dis)
    await svc.run_cycle()
    await svc.run_cycle()
    assert wf.created == [("o/r", 5)]


@pytest.mark.asyncio
async def test_dismissed_issue_is_skipped() -> None:
    """Ensure a dismissed, still-labelled issue is not started."""
    wf, dis = _FakeWorkflows(), _FakeDismissals()
    dis.add("o/r#5")
    await _svc(_FakeGitHub(issues=[Issue(5, "t", "b")]), wf, dis).run_cycle()
    assert wf.created == []
    # Still labelled ⇒ dismissal stays.
    assert dis.is_dismissed("o/r#5") is True


@pytest.mark.asyncio
async def test_dismissal_cleared_when_label_removed() -> None:
    """Ensure a dismissal for an unlabelled issue is cleared."""
    wf, dis = _FakeWorkflows(), _FakeDismissals()
    dis.add("o/r#9")  # dismissed, but no longer labelled
    await _svc(_FakeGitHub(issues=[Issue(5, "t", "b")]), wf, dis).run_cycle()
    assert dis.is_dismissed("o/r#9") is False
    assert wf.created == [("o/r", 5)]


@pytest.mark.asyncio
async def test_github_failure_is_isolated_and_recoverable() -> None:
    """Ensure a failing cycle starts nothing and the next cycle recovers."""
    wf, dis = _FakeWorkflows(), _FakeDismissals()
    github = _FakeGitHub(issues=[Issue(5, "t", "b")], fail=True)
    svc = _svc(github, wf, dis)
    await svc.run_cycle()  # must not raise
    assert wf.created == []
    github._fail = False
    await svc.run_cycle()
    assert wf.created == [("o/r", 5)]
