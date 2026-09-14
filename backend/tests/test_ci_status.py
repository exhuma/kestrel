"""Required-CI normalization and state-transition tests."""
from __future__ import annotations

import pytest

from app.config_models import TaskSourceConfig
from app.models_workflow import WorkflowRun
from app.ports import RequiredCiStatus
from app.services.ci_status import github_status, gitlab_status
from app.services.workflows.ci import inspect_required_ci
from app.storage.registry import SessionRegistry
from tests.conftest import (
    _FakeGit,
    _FakeGitHub,
    _FakeRunner,
    _service,
    _settings,
)


def test_status_normalizers_preserve_wait_pass_and_failure() -> None:
    """Provider-native CI outcomes map to the three source-neutral states."""
    assert github_status("test", None).state == "pending"
    assert github_status("test", {"conclusion": "success"}).state == "passed"
    assert github_status("test", {"conclusion": "failure"}).state == "failed"
    assert gitlab_status("test", {"status": "running"}).state == "pending"
    assert gitlab_status("test", {"status": "success"}).state == "passed"
    assert gitlab_status("test", {"status": "failed"}).state == "failed"


class _CiHost:
    """A code-host double that supplies one fixed required-CI result set."""

    def __init__(self, statuses: list[RequiredCiStatus]) -> None:
        """Store normalized statuses returned by the CI capability."""
        self._statuses = statuses

    async def required_ci_statuses(self, _repo, _number, _names):
        """Return the fixed result set without contacting a provider."""
        return self._statuses


def _ci_service(statuses: list[RequiredCiStatus], budget: int = 2):
    """Build a workflow service with one configured required check."""
    service = _service(
        _FakeGitHub(), _FakeRunner(SessionRegistry(), []), _FakeGit(),
        settings=_settings(
            max_ci_repair_iterations=budget,
            task_sources=[
                TaskSourceConfig(
                    type="github", watched_repos=["o/r"],
                    required_ci_statuses=["tests"],
                )
            ],
        ),
    )
    service.code_hosts["github-issue"] = _CiHost(statuses)
    return service


@pytest.mark.asyncio
async def test_passing_required_ci_marks_run_technically_ready() -> None:
    """A fully passing configured set advances a delivered run terminally."""
    service = _ci_service([RequiredCiStatus("tests", "passed")])
    run = WorkflowRun(
        id="ci-pass", repo="o/r", pr_number=1, source="github-issue",
        status="awaiting_ci",
    )

    await inspect_required_ci(service, run)

    assert run.status == "technically_ready"


@pytest.mark.asyncio
async def test_pending_required_ci_keeps_run_waiting() -> None:
    """An incomplete required check never consumes the CI repair budget."""
    service = _ci_service([RequiredCiStatus("tests", "pending")])
    run = WorkflowRun(
        id="ci-wait", repo="o/r", pr_number=1, source="github-issue",
        status="awaiting_ci",
    )

    await inspect_required_ci(service, run)

    assert run.status == "awaiting_ci"
    assert run.ci_repair_round == 0


@pytest.mark.asyncio
async def test_exhausted_ci_budget_escalates_without_repair() -> None:
    """A failed check escalates once its independent repair budget is spent."""
    service = _ci_service([RequiredCiStatus("tests", "failed")], budget=1)
    run = WorkflowRun(
        id="ci-fail", repo="o/r", pr_number=1, source="github-issue",
        status="awaiting_ci", ci_repair_round=1,
    )

    await inspect_required_ci(service, run)

    assert run.status == "escalated"
    assert "repair budget" in (run.error or "")
