"""Tests for the poll-reconciliation service."""
from __future__ import annotations

import pytest

from app.config import Settings
from app.config_models import TaskSourceConfig
from app.models_board import Workflow
from app.models_board_records import IntakeOutcome
from app.ports import Task
from app.services.exceptions import GitHubError
from app.services.github import Issue
from app.services.ingestion import BoardIntake, IngestionService
from app.services.reconcile import ReconcileService


class _FakeTaskSource:
    async def get_task(self, ref):
        return Task(ref=ref, title="t", body="b")

    def visibility(self):
        return "public"


class _FakeTaskSources:
    """A minimal ``TaskSourceRegistry`` double."""

    def __init__(self) -> None:
        self.sources = {"github-issue": _FakeTaskSource()}
        self.code_hosts: dict[str, object] = {}


class _FakeQuarantine:
    async def intake_for_new_task(self, intake):
        return IntakeOutcome(released=True, safe_content=intake.body)


class _FakeBoard:
    def __init__(self) -> None:
        self.calls = []
        self.workflows: list[Workflow] = []

    def create_workflow_from_intake(self, intake):
        self.calls.append(intake)
        workflow = Workflow(
            id=f"wf-{len(self.calls) - 1}",
            source=intake.source,
            task_ref=intake.task_ref,
            repo=intake.repo,
            base_branch=intake.base_branch,
            source_visibility=intake.source_visibility,
            title=intake.title,
        )
        self.workflows.append(workflow)
        return workflow

    def list_workflows(self) -> list[Workflow]:
        return self.workflows


class _FakeGates:
    def create_gate(self, workflow_id, **_kwargs):
        pass


def _board_intake() -> BoardIntake:
    return BoardIntake(_FakeQuarantine(), _FakeBoard(), _FakeGates())


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
        del repo, label, state
        self.calls += 1
        if self._fail:
            raise GitHubError("unreachable")
        return list(self._issues)

    async def list_issues(self, repo, *, state="open"):
        del repo, state
        self.calls += 1
        if self._fail:
            raise GitHubError("unreachable")
        return list(self._issues)


def _svc(github, dismissals, board_intake=None) -> ReconcileService:
    source = TaskSourceConfig(
        type="github", watched_repos=["o/r"], trigger_label="kestrel"
    )
    settings = Settings(_env_file=None, task_sources=[source])
    ingestion = IngestionService(
        settings,
        _FakeTaskSources(),
        dismissals,
        board_intake or _board_intake(),
    )
    return ReconcileService(source, github, ingestion, dismissals)


@pytest.mark.asyncio
async def test_starts_missing_run_once_and_is_idempotent() -> None:
    """Ensure a labelled issue starts one run; a second cycle starts none."""
    dis = _FakeDismissals()
    board_intake = _board_intake()
    svc = _svc(
        _FakeGitHub(issues=[Issue(5, "t", "b", labels=frozenset({"kestrel"}))]),
        dis,
        board_intake=board_intake,
    )
    await svc.run_cycle()
    await svc.run_cycle()
    assert [c.task_ref for c in board_intake.board.calls] == ["o/r#5"]


@pytest.mark.asyncio
async def test_dismissed_issue_is_skipped() -> None:
    """Ensure a dismissed, still-labelled issue is not started."""
    dis = _FakeDismissals()
    dis.add("o/r#5")
    board_intake = _board_intake()
    await _svc(
        _FakeGitHub(issues=[Issue(5, "t", "b", labels=frozenset({"kestrel"}))]),
        dis,
        board_intake=board_intake,
    ).run_cycle()
    assert board_intake.board.calls == []
    # Still labelled ⇒ dismissal stays.
    assert dis.is_dismissed("o/r#5") is True


@pytest.mark.asyncio
async def test_dismissal_cleared_when_label_removed() -> None:
    """Ensure a dismissal for an unlabelled issue is cleared."""
    dis = _FakeDismissals()
    dis.add("o/r#9")  # dismissed, but no longer labelled
    board_intake = _board_intake()
    await _svc(
        _FakeGitHub(issues=[Issue(5, "t", "b", labels=frozenset({"kestrel"}))]),
        dis,
        board_intake=board_intake,
    ).run_cycle()
    assert dis.is_dismissed("o/r#9") is False
    assert [c.task_ref for c in board_intake.board.calls] == ["o/r#5"]


@pytest.mark.asyncio
async def test_github_failure_is_isolated_and_recoverable() -> None:
    """Ensure a failing cycle starts nothing and the next cycle recovers."""
    dis = _FakeDismissals()
    github = _FakeGitHub(
        issues=[Issue(5, "t", "b", labels=frozenset({"kestrel"}))], fail=True
    )
    board_intake = _board_intake()
    svc = _svc(github, dis, board_intake=board_intake)
    await svc.run_cycle()  # must not raise
    assert board_intake.board.calls == []
    github._fail = False
    await svc.run_cycle()
    assert [c.task_ref for c in board_intake.board.calls] == ["o/r#5"]


@pytest.mark.asyncio
async def test_a_closed_issue_starts_nothing() -> None:
    """Ensure a closed issue is ignored, labelled or not."""
    board_intake = _board_intake()
    await _svc(
        _FakeGitHub(issues=[Issue(
            5, "t", "b", state="closed", labels=frozenset({"kestrel"})
        )]),
        _FakeDismissals(),
        board_intake=board_intake,
    ).run_cycle()
    assert board_intake.board.calls == []
