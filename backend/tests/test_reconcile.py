"""Tests for the poll-reconciliation service."""
from __future__ import annotations

import pytest

from app.config import Settings
from app.config_models import TaskSourceConfig
from app.models_board import AcceptedTaskIntake, IntakeOutcome, Workflow
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


class _FakeChildTasks:
    """Tracks linked child lifecycle state for reconciliation tests."""

    def __init__(self) -> None:
        """Create an empty child-state map."""
        self.states: dict[str, str] = {}
        self.latest: dict[str, str] = {}

    def record_run(self, task_ref: str, workflow_id: str) -> None:
        """Record the current run when its task is linked."""
        if task_ref in self.states:
            self.latest[task_ref] = workflow_id

    def observe_source_state(self, task_ref: str, state: str) -> None:
        """Record a state only for known linked tasks."""
        if task_ref in self.states:
            self.states[task_ref] = state

    def claim_reopen(self, task_ref: str, workflow_id: str) -> bool:
        """Claim a known closed child owned by the supplied run."""
        if self.states.get(task_ref) != "closed":
            return False
        if self.latest.get(task_ref) != workflow_id:
            return False
        self.states[task_ref] = "reopening"
        return True

    def complete_reopen(self, task_ref: str, workflow_id: str) -> None:
        """Complete a claimed reopen with its successor run."""
        self.states[task_ref] = "open"
        self.latest[task_ref] = workflow_id

    def release_reopen(self, task_ref: str) -> None:
        """Restore a failed claim to closed."""
        self.states[task_ref] = "closed"


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


def _board_intake() -> BoardIntake:
    return BoardIntake(_FakeQuarantine(), _FakeBoard())


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


def _svc(
    github, dismissals, children=None, board_intake=None
) -> ReconcileService:
    source = TaskSourceConfig(
        type="github", watched_repos=["o/r"], trigger_label="kestrel"
    )
    settings = Settings(_env_file=None, task_sources=[source])
    ingestion = IngestionService(
        settings,
        _FakeTaskSources(),
        dismissals,
        board_intake or _board_intake(),
        children,
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
async def test_closed_issue_observation_never_starts_normal_ingestion() -> None:
    """Reconciliation records a linked close without a duplicate run."""
    dis, children = _FakeDismissals(), _FakeChildTasks()
    board_intake = _board_intake()
    parent = board_intake.board.create_workflow_from_intake(
        _intake("o/r#5", "wf-parent-title")
    )
    children.states[parent.task_ref] = "open"
    children.latest[parent.task_ref] = parent.id
    await _svc(
        _FakeGitHub(issues=[Issue(5, "t", "b", state="closed")]),
        dis,
        children,
        board_intake=board_intake,
    ).run_cycle()
    assert children.states[parent.task_ref] == "closed"
    assert [c.task_ref for c in board_intake.board.calls] == ["o/r#5"]


@pytest.mark.asyncio
async def test_reconciliation_re_adopts_a_previously_closed_child() -> None:
    """A missed reopen creates one successor only after a recorded close."""
    dis, children = _FakeDismissals(), _FakeChildTasks()
    board_intake = _board_intake()
    parent = board_intake.board.create_workflow_from_intake(
        _intake("o/r#5", "wf-parent-title")
    )
    children.states[parent.task_ref] = "closed"
    children.latest[parent.task_ref] = parent.id
    svc = _svc(
        _FakeGitHub(issues=[Issue(5, "t", "b")]),
        dis,
        children,
        board_intake=board_intake,
    )

    await svc.run_cycle()
    await svc.run_cycle()

    parent_and_one_successor = 2
    successor_ids = [c.id for c in board_intake.board.workflows]
    assert len(successor_ids) == parent_and_one_successor
    assert children.latest[parent.task_ref] == successor_ids[-1]


def _intake(task_ref: str, title: str) -> AcceptedTaskIntake:
    return AcceptedTaskIntake(
        source="github-issue",
        task_ref=task_ref,
        repo="o/r",
        base_branch="main",
        source_visibility="public",
        title=title,
    )
