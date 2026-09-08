"""Tests for FeedbackPollService (feature 013, US1)."""
from __future__ import annotations

from datetime import datetime

import pytest

from app.config import Settings
from app.models_workflow import WorkflowRun
from app.notifications import Notifier
from app.ports import Feedback
from app.services.feedback.poll import FeedbackPollService
from app.services.git import GitService
from app.services.workflows import WorkflowService
from app.storage.registry import SessionRegistry
from app.storage.workflow_registry import WorkflowRegistry
from tests.conftest import _FakeFeedbackStore, _FakeGitHub, _FakeRunner


class _FakeNoopNotifier(Notifier):
    def notify(self, _run) -> None:
        return None


class _FakeFeedbackSource:
    """Controllable ``list_comments``/``acknowledge`` double, keyed by ref."""

    def __init__(self, items_by_ref: dict[str, list[Feedback]] | None = None,
                 fail_refs: set[str] | None = None) -> None:
        self.items_by_ref = items_by_ref or {}
        self.fail_refs = fail_refs or set()
        self.calls: list[tuple[str, str | None]] = []

    async def list_comments(
        self, ref: str, since: str | None = None
    ) -> list[Feedback]:
        self.calls.append((ref, since))
        if ref in self.fail_refs:
            raise RuntimeError("source unreachable")
        return self.items_by_ref.get(ref, [])

    async def acknowledge(
        self, _feedback: Feedback, _token: str = "eyes"
    ) -> bool:
        return False


class _FakeIntake:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def intake(self, feedback, *, task_ref, source=None, is_bot=False):
        self.calls.append({
            "task_ref": task_ref, "feedback": feedback,
            "source": source, "is_bot": is_bot,
        })


def _feedback(
    body="@kestrel hi", created="2026-01-01T00:00:00+00:00"
) -> Feedback:
    return Feedback(
        external_id=f"x:{created}", origin="ticket", author="a", body=body,
        created_at=datetime.fromisoformat(created),
    )


def _run(run_id: str, task_ref: str, status: str = "coding") -> WorkflowRun:
    return WorkflowRun(id=run_id, repo="o/r", task_ref=task_ref, status=status)


def _workflow_service(
    sources: dict, workflows: WorkflowRegistry
) -> WorkflowService:
    return WorkflowService(
        settings=Settings(_env_file=None),
        sessions=SessionRegistry(),
        workflows=workflows,
        backends=_FakeRunner(SessionRegistry(), []),
        git=GitService("t"),
        github=_FakeGitHub(),
        notifier=_FakeNoopNotifier(),
        sources=sources,
    )


@pytest.mark.asyncio
async def test_run_cycle_skips_terminal_runs() -> None:
    """A done/failed/rejected/escalated run is never polled."""
    source = _FakeFeedbackSource()
    workflows = WorkflowRegistry()
    for status in ("done", "failed", "rejected", "escalated"):
        workflows.create(_run(f"wf-{status}", f"o/r#{status}", status=status))
    svc = _workflow_service({"github-issue": source}, workflows)
    poll = FeedbackPollService(svc, _FakeFeedbackStore(), _FakeIntake())

    await poll.run_cycle()

    assert source.calls == []


@pytest.mark.asyncio
async def test_run_cycle_uses_the_stored_cursor() -> None:
    """list_comments is called with the persisted cursor for that ref."""
    source = _FakeFeedbackSource()
    workflows = WorkflowRegistry()
    workflows.create(_run("wf-1", "o/r#1"))
    svc = _workflow_service({"github-issue": source}, workflows)
    store = _FakeFeedbackStore()
    store.set_cursor("ticket:o/r#1", "2026-01-01T00:00:00+00:00")
    poll = FeedbackPollService(svc, store, _FakeIntake())

    await poll.run_cycle()

    assert source.calls == [("o/r#1", "2026-01-01T00:00:00+00:00")]


@pytest.mark.asyncio
async def test_run_cycle_advances_the_cursor_to_the_newest_item() -> None:
    """After new items are read, the cursor advances to the newest
    item's created_at."""
    items = [
        _feedback(created="2026-01-01T00:00:00+00:00"),
        _feedback(created="2026-01-03T00:00:00+00:00"),
        _feedback(created="2026-01-02T00:00:00+00:00"),
    ]
    source = _FakeFeedbackSource(items_by_ref={"o/r#1": items})
    workflows = WorkflowRegistry()
    workflows.create(_run("wf-1", "o/r#1"))
    svc = _workflow_service({"github-issue": source}, workflows)
    store = _FakeFeedbackStore()
    poll = FeedbackPollService(svc, store, _FakeIntake())

    await poll.run_cycle()

    assert store.cursor("ticket:o/r#1") == "2026-01-03T00:00:00+00:00"


@pytest.mark.asyncio
async def test_run_cycle_leaves_cursor_unchanged_with_no_new_items() -> None:
    """An empty read never overwrites the existing cursor."""
    source = _FakeFeedbackSource()
    workflows = WorkflowRegistry()
    workflows.create(_run("wf-1", "o/r#1"))
    svc = _workflow_service({"github-issue": source}, workflows)
    store = _FakeFeedbackStore()
    store.set_cursor("ticket:o/r#1", "2026-01-01T00:00:00+00:00")
    poll = FeedbackPollService(svc, store, _FakeIntake())

    await poll.run_cycle()

    assert store.cursor("ticket:o/r#1") == "2026-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_run_cycle_forwards_every_item_to_intake() -> None:
    """Every returned Feedback item is handed to the intake service with
    this run's task_ref and the same source it was read from."""
    items = [_feedback(), _feedback(created="2026-01-02T00:00:00+00:00")]
    source = _FakeFeedbackSource(items_by_ref={"o/r#1": items})
    workflows = WorkflowRegistry()
    workflows.create(_run("wf-1", "o/r#1"))
    svc = _workflow_service({"github-issue": source}, workflows)
    intake = _FakeIntake()
    poll = FeedbackPollService(svc, _FakeFeedbackStore(), intake)

    await poll.run_cycle()

    assert [c["task_ref"] for c in intake.calls] == ["o/r#1", "o/r#1"]
    assert [c["feedback"] for c in intake.calls] == items


@pytest.mark.asyncio
async def test_run_cycle_isolates_a_failing_source() -> None:
    """One run's list_comments failure does not stop the rest from
    being polled."""
    good_items = [_feedback()]
    source = _FakeFeedbackSource(
        items_by_ref={"o/r#2": good_items}, fail_refs={"o/r#1"},
    )
    workflows = WorkflowRegistry()
    workflows.create(_run("wf-1", "o/r#1"))
    workflows.create(_run("wf-2", "o/r#2"))
    svc = _workflow_service({"github-issue": source}, workflows)
    intake = _FakeIntake()
    poll = FeedbackPollService(svc, _FakeFeedbackStore(), intake)

    await poll.run_cycle()

    assert [c["task_ref"] for c in intake.calls] == ["o/r#2"]


@pytest.mark.asyncio
async def test_list_work_items_is_always_empty() -> None:
    """Feedback polling has no dry-run listing (it walks runs, not
    tickets awaiting ingestion) — required by the PollSource protocol."""
    poll = FeedbackPollService(
        _workflow_service({}, WorkflowRegistry()), _FakeFeedbackStore(),
        _FakeIntake(),
    )

    assert await poll.list_work_items() == []
