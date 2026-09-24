"""Tests for FeedbackDispatcher handling feedback on completed runs."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models_workflow import Step, WorkflowRun, WorkflowStep
from app.persistence.tables import FeedbackItemRow
from app.services.feedback.dispatch import FeedbackDispatcher
from app.services.ingestion import BoardIntake, IngestionService
from app.storage.registry import SessionRegistry
from tests.conftest import (
    _FakeDismissals,
    _FakeFeedbackStore,
    _FakeGit,
    _FakeGitHub,
    _FakeRunner,
    _service,
    _wait,
)

_DONE_PR_NUMBER = 9


def _review_item(
    workflow_id="wf-1", body="please fix the bug"
) -> FeedbackItemRow:
    """Build queued review-origin feedback for a completed workflow."""
    return FeedbackItemRow(
        external_id="r1",
        workflow_id=workflow_id,
        task_ref="o/r#5",
        origin="review",
        author="reviewer",
        body=body,
        state="queued",
        created_at=datetime.now(timezone.utc),
    )


class _UnusedBoard:
    """Never exercised: this file only tests the unchanged successor path."""

    def create_workflow_from_intake(self, intake):
        raise NotImplementedError


class _UnusedQuarantine:
    async def intake_for_new_task(self, intake):
        raise NotImplementedError


def _ingestion_for(svc) -> IngestionService:
    """Wire real successor-run creation to a service's own registry."""
    return IngestionService(
        svc.settings,
        svc,
        _FakeDismissals(),
        BoardIntake(_UnusedQuarantine(), _UnusedBoard()),
    )


def _done_run(**overrides) -> WorkflowRun:
    """Build a completed run with a finished workflow step sequence."""
    defaults = dict(
        id="wf-1",
        repo="o/r",
        task_ref="o/r#5",
        status="done",
        branch="kestrel/issue-5",
        base_branch="main",
        steps=[WorkflowStep(name=s, status="done") for s in Step.sequence()],
    )
    defaults.update(overrides)
    return WorkflowRun(**defaults)


def _successor_of(svc, parent: WorkflowRun) -> WorkflowRun:
    """Return the only run in a service other than the supplied parent."""
    return next(run for run in svc.list() if run.id != parent.id)


@pytest.mark.asyncio
async def test_review_origin_open_pr_resumes_the_branch() -> None:
    """An open request resumes the completed branch with its feedback."""
    gh = _FakeGitHub()
    gh.pr_state = "open"
    svc = _service(gh, _FakeRunner(SessionRegistry(), []), _FakeGit())
    svc.workflows.create(_done_run(pr_number=_DONE_PR_NUMBER))
    resumed: list[tuple[str, str]] = []
    svc.resume_with_feedback = lambda wid, body: resumed.append((wid, body))
    store = _FakeFeedbackStore()
    item = _review_item()
    store.claim(item)

    FeedbackDispatcher(svc, store).dispatch(item)
    await _wait(lambda: resumed)

    assert resumed == [("wf-1", "please fix the bug")]
    assert store.items["r1"].state == "dispatched"


@pytest.mark.asyncio
@pytest.mark.parametrize("pr_state", ["merged", "closed"])
async def test_done_run_with_a_finished_pr_starts_a_linked_successor(
    pr_state: str,
) -> None:
    """A closed or merged request starts a successor rather than reviving."""
    gh = _FakeGitHub()
    gh.pr_state = pr_state
    svc = _service(gh, _FakeRunner(SessionRegistry(), []), _FakeGit())
    parent = _done_run(pr_number=_DONE_PR_NUMBER)
    svc.workflows.create(parent)
    store = _FakeFeedbackStore()
    item = _review_item(body="@kestrel also handle the null case")
    store.claim(item)

    FeedbackDispatcher(svc, store, _ingestion_for(svc)).dispatch(item)
    await _wait(lambda: len(svc.list()) > 1)

    successor = _successor_of(svc, parent)
    assert successor.parent_run_id == parent.id
    assert successor.task_ref == parent.task_ref
    assert successor.repo == parent.repo
    assert successor.branch != parent.branch
    assert store.items["r1"].state == "applied"


@pytest.mark.asyncio
async def test_done_merged_pr_with_no_ingestion_wired_stays_queued() -> None:
    """Without successor creation, feedback remains queued without crashing."""
    gh = _FakeGitHub()
    gh.pr_state = "merged"
    svc = _service(gh, _FakeRunner(SessionRegistry(), []), _FakeGit())
    svc.workflows.create(_done_run(pr_number=_DONE_PR_NUMBER))
    store = _FakeFeedbackStore()
    item = _review_item()
    store.claim(item)

    FeedbackDispatcher(svc, store).dispatch(item)
    await _wait(lambda: store.items["r1"].state == "queued")

    assert len(svc.list()) == 1
    assert store.items["r1"].state == "queued"


@pytest.mark.asyncio
async def test_review_origin_falls_back_to_parsing_pr_url() -> None:
    """A pre-migration completed row resolves its pull request from its URL."""
    gh = _FakeGitHub()
    gh.pr_state = "open"
    svc = _service(gh, _FakeRunner(SessionRegistry(), []), _FakeGit())
    svc.workflows.create(
        _done_run(pr_number=None, pr_url="https://github.com/o/r/pull/9")
    )
    resumed: list[tuple[str, str]] = []
    svc.resume_with_feedback = lambda wid, body: resumed.append((wid, body))
    store = _FakeFeedbackStore()
    item = _review_item()
    store.claim(item)

    FeedbackDispatcher(svc, store).dispatch(item)
    await _wait(lambda: resumed)

    assert resumed == [("wf-1", "please fix the bug")]


@pytest.mark.asyncio
async def test_done_with_no_pr_at_all_starts_a_linked_successor() -> None:
    """A completed run without a request starts a successor directly."""
    svc = _service(
        _FakeGitHub(), _FakeRunner(SessionRegistry(), []), _FakeGit()
    )
    parent = _done_run(pr_number=None, pr_url=None)
    svc.workflows.create(parent)
    store = _FakeFeedbackStore()
    item = _review_item()
    store.claim(item)

    FeedbackDispatcher(svc, store, _ingestion_for(svc)).dispatch(item)
    await _wait(lambda: len(svc.list()) > 1)

    successor = _successor_of(svc, parent)
    assert successor.parent_run_id == parent.id
    assert store.items["r1"].state == "applied"
