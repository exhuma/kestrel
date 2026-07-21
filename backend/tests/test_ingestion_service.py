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
        self.created: list[tuple[str, int, str]] = []
        self._fail = fail

    def list(self) -> list[WorkflowRun]:
        return self.runs

    async def create(
        self, repo: str, issue_number: int, *, source: str = "manual"
    ) -> str:
        if self._fail:
            raise RuntimeError("create failed")
        rid = f"wf-{len(self.created)}"
        self.created.append((repo, issue_number, source))
        self.runs.append(
            WorkflowRun(
                id=rid, repo=repo, issue_number=issue_number, source=source
            )
        )
        return rid


class _FakeDismissals:
    """In-memory dismissal store."""

    def __init__(self) -> None:
        self._d: set[tuple[str, int]] = set()

    def add(self, repo: str, issue_number: int) -> None:
        self._d.add((repo, issue_number))

    def is_dismissed(self, repo: str, issue_number: int) -> bool:
        return (repo, issue_number) in self._d

    def clear(self, repo: str, issue_number: int) -> None:
        self._d.discard((repo, issue_number))


def _service(
    wf: _FakeWorkflows, dismissals: _FakeDismissals
) -> IngestionService:
    settings = Settings(_env_file=None, watched_repos=["o/r"])
    return IngestionService(settings, wf, dismissals)


@pytest.mark.asyncio
async def test_starts_one_run_for_watched_repo() -> None:
    """Ensure a qualifying issue starts exactly one run tagged github-issue."""
    wf, dis = _FakeWorkflows(), _FakeDismissals()
    rid = await _service(wf, dis).maybe_start_run("o/r", 5)
    assert rid == "wf-0"
    assert wf.created == [("o/r", 5, "github-issue")]


@pytest.mark.asyncio
async def test_ignores_unwatched_repo() -> None:
    """Ensure an unwatched repo starts nothing."""
    wf, dis = _FakeWorkflows(), _FakeDismissals()
    assert await _service(wf, dis).maybe_start_run("x/y", 5) is None
    assert wf.created == []


@pytest.mark.asyncio
async def test_ignores_dismissed_issue() -> None:
    """Ensure a dismissed (repo, issue) starts nothing."""
    wf, dis = _FakeWorkflows(), _FakeDismissals()
    dis.add("o/r", 5)
    assert await _service(wf, dis).maybe_start_run("o/r", 5) is None
    assert wf.created == []


@pytest.mark.asyncio
async def test_never_starts_second_run_for_same_issue() -> None:
    """Ensure an existing run for the pair blocks a duplicate."""
    wf, dis = _FakeWorkflows(), _FakeDismissals()
    svc = _service(wf, dis)
    await svc.maybe_start_run("o/r", 5)
    assert await svc.maybe_start_run("o/r", 5) is None
    assert len(wf.created) == 1


@pytest.mark.asyncio
async def test_failed_create_leaves_no_run_or_dismissal() -> None:
    """Ensure a failed create leaves nothing for reconciliation to trip on."""
    wf, dis = _FakeWorkflows(fail=True), _FakeDismissals()
    with pytest.raises(RuntimeError):
        await _service(wf, dis).maybe_start_run("o/r", 5)
    assert wf.runs == []
    assert dis.is_dismissed("o/r", 5) is False
