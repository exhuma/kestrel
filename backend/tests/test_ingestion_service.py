"""Tests for the shared ingestion path (maybe_start_run)."""
from __future__ import annotations

import pytest

from app.config import Settings
from app.models_workflow import WorkflowRun
from app.services.ingestion import IngestionService


class _FakeWorkflows:
    """Minimal WorkflowService stand-in: records creates, lists runs."""

    def __init__(self, fail: bool = False) -> None:
        self.runs: list[WorkflowRun] = []
        self.created: list[tuple[str, int | None, str]] = []
        self._fail = fail

    def list(self) -> list[WorkflowRun]:
        return self.runs

    async def create(
        self,
        repo: str,
        issue_number: int | None = None,
        *,
        source: str = "manual",
        task_ref: str | None = None,
        base_branch: str | None = None,
    ) -> str:
        if self._fail:
            raise RuntimeError("create failed")
        rid = f"wf-{len(self.created)}"
        self.created.append((repo, issue_number, source))
        self.runs.append(
            WorkflowRun(
                id=rid, repo=repo, issue_number=issue_number, source=source,
                task_ref=task_ref or f"{repo}#{issue_number}",
            )
        )
        return rid


class _FakeDismissals:
    """In-memory dismissal store keyed by task_ref."""

    def __init__(self) -> None:
        self._d: set[str] = set()

    def add(self, task_ref: str) -> None:
        self._d.add(task_ref)

    def is_dismissed(self, task_ref: str) -> bool:
        return task_ref in self._d

    def all(self) -> list[str]:
        return list(self._d)

    def clear(self, task_ref: str) -> None:
        self._d.discard(task_ref)


def _service(
    wf: _FakeWorkflows, dismissals: _FakeDismissals
) -> IngestionService:
    settings = Settings(_env_file=None, watched_repos=["o/r"])
    return IngestionService(settings, wf, dismissals)


@pytest.mark.asyncio
async def test_starts_one_run_for_watched_repo() -> None:
    """Ensure a qualifying issue starts exactly one run tagged github-issue."""
    wf, dis = _FakeWorkflows(), _FakeDismissals()
    rid = await _service(wf, dis).maybe_start_run(source="github-issue", task_ref="o/r#5", code_repo="o/r", issue_number=5)
    assert rid == "wf-0"
    assert wf.created == [("o/r", 5, "github-issue")]


@pytest.mark.asyncio
async def test_ignores_unwatched_repo() -> None:
    """Ensure an unwatched repo starts nothing."""
    wf, dis = _FakeWorkflows(), _FakeDismissals()
    assert await _service(wf, dis).maybe_start_run(source="github-issue", task_ref="x/y#5", code_repo="x/y", issue_number=5) is None
    assert wf.created == []


@pytest.mark.asyncio
async def test_ignores_dismissed_issue() -> None:
    """Ensure a dismissed (repo, issue) starts nothing."""
    wf, dis = _FakeWorkflows(), _FakeDismissals()
    dis.add("o/r#5")
    assert await _service(wf, dis).maybe_start_run(source="github-issue", task_ref="o/r#5", code_repo="o/r", issue_number=5) is None
    assert wf.created == []


@pytest.mark.asyncio
async def test_never_starts_second_run_for_same_issue() -> None:
    """Ensure an existing run for the pair blocks a duplicate."""
    wf, dis = _FakeWorkflows(), _FakeDismissals()
    svc = _service(wf, dis)
    await svc.maybe_start_run(source="github-issue", task_ref="o/r#5", code_repo="o/r", issue_number=5)
    assert await svc.maybe_start_run(source="github-issue", task_ref="o/r#5", code_repo="o/r", issue_number=5) is None
    assert len(wf.created) == 1


@pytest.mark.asyncio
async def test_failed_create_leaves_no_run_or_dismissal() -> None:
    """Ensure a failed create leaves nothing for reconciliation to trip on."""
    wf, dis = _FakeWorkflows(fail=True), _FakeDismissals()
    with pytest.raises(RuntimeError):
        await _service(wf, dis).maybe_start_run(source="github-issue", task_ref="o/r#5", code_repo="o/r", issue_number=5)
    assert wf.runs == []
    assert dis.is_dismissed("o/r#5") is False
