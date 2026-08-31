"""Tests for WorkflowService.task_label()/task_link() (feature 009): the
per-run identity/link surfaced by the run's task source, distinct from
rerunnable()'s visibility gate."""
from __future__ import annotations

from app.models_workflow import WorkflowRun
from app.services.fixture import FixtureTaskSource
from app.services.workflows import WorkflowService
from app.storage.registry import SessionRegistry
from app.storage.workflow_registry import WorkflowRegistry
from tests.conftest import (
    _FakeDismissals,
    _FakeGit,
    _FakeGitHub,
    _FakeNotifier,
    _FakeRunner,
    _settings,
)


def _service(sources=None) -> WorkflowService:
    runner = _FakeRunner(SessionRegistry(), outputs=[])
    return WorkflowService(
        settings=_settings(),
        sessions=runner.sessions,
        workflows=WorkflowRegistry(),
        backends=runner,
        git=_FakeGit(),
        github=_FakeGitHub(),
        notifier=_FakeNotifier(),
        dismissals=_FakeDismissals(),
        sources=sources,
    )


def test_task_label_and_link_for_github_run() -> None:
    """Ensure a GitHub-sourced run's label/link come from its task_ref."""
    svc = _service()
    run = WorkflowRun(
        id="wf-1", repo="o/r", issue_number=7,
        source="github-issue", task_ref="o/r#7",
    )

    assert svc.task_label(run) == "o/r#7"
    assert svc.task_link(run) == "https://github.com/o/r/issues/7"


def test_task_label_falls_back_when_task_ref_is_empty() -> None:
    """Ensure pre-003 rows (empty task_ref) still get a usable label."""
    svc = _service()
    run = WorkflowRun(
        id="wf-1", repo="o/r", issue_number=7,
        source="github-issue", task_ref="",
    )

    assert svc.task_label(run) == "o/r#7"


def test_task_link_is_none_for_a_source_with_no_link(tmp_path) -> None:
    """Ensure a fixture-sourced run's task_link is None, not a file path."""
    svc = _service(
        sources={"fixture-issue": FixtureTaskSource(str(tmp_path))}
    )
    run = WorkflowRun(
        id="wf-1", repo="me/sandbox", issue_number=None,
        source="fixture-issue", task_ref="fixture:hello-fixture",
    )

    assert svc.task_link(run) is None
    assert svc.task_label(run) == "hello-fixture"
