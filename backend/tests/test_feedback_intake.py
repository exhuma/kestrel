"""Tests for FeedbackIntakeService's pipeline (feature 013, US1)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.config import Settings
from app.models_workflow import WorkflowRun
from app.ports import Feedback
from app.services.feedback.intake import FeedbackIntakeService
from app.storage.workflow_registry import WorkflowRegistry
from tests.conftest import _FakeFeedbackStore


class _FakeSource:
    """Records acknowledge calls; optionally raises to exercise the
    best-effort guard."""

    def __init__(self, raise_on_ack: bool = False) -> None:
        self.acknowledged: list[str] = []
        self._raise = raise_on_ack

    async def acknowledge(
        self, feedback: Feedback, _token: str = "eyes"
    ) -> bool:
        if self._raise:
            raise RuntimeError("boom")
        self.acknowledged.append(feedback.external_id)
        return True


def _feedback(
    external_id="gh-issue-comment:o/r#1", body="@kestrel please fix this",
    author="octocat", origin="ticket",
) -> Feedback:
    return Feedback(
        external_id=external_id, origin=origin, author=author, body=body,
        created_at=datetime.now(timezone.utc),
    )


def _intake(
    settings=None, store=None, workflows=None, dispatch=None
) -> tuple[FeedbackIntakeService, list]:
    dispatched: list = []
    service = FeedbackIntakeService(
        settings or Settings(_env_file=None),
        store or _FakeFeedbackStore(),
        workflows or WorkflowRegistry(),
        dispatch or dispatched.append,
    )
    return service, dispatched


@pytest.mark.asyncio
async def test_unmarked_feedback_is_never_persisted() -> None:
    """A comment without the marker is discarded before persistence."""
    store = _FakeFeedbackStore()
    service, dispatched = _intake(store=store)

    await service.intake(
        _feedback(body="just a normal comment"), task_ref="o/r#1",
        source=_FakeSource(),
    )

    assert store.items == {}
    assert dispatched == []


@pytest.mark.asyncio
async def test_ignored_author_is_never_persisted() -> None:
    """An author on the denylist never produces a feedback_item row, even
    with the marker present."""
    store = _FakeFeedbackStore()
    settings = Settings(_env_file=None, feedback_ignore_authors=["kestrel-bot"])
    service, dispatched = _intake(settings=settings, store=store)

    await service.intake(
        _feedback(author="kestrel-bot"), task_ref="o/r#1", source=_FakeSource(),
    )

    assert store.items == {}
    assert dispatched == []


@pytest.mark.asyncio
async def test_bot_flag_is_never_persisted() -> None:
    """A caller-flagged bot author is discarded even without a denylist
    entry (GitHub's user.type == "Bot" guard)."""
    store = _FakeFeedbackStore()
    service, dispatched = _intake(store=store)

    await service.intake(
        _feedback(author="dependabot[bot]"), task_ref="o/r#1",
        source=_FakeSource(), is_bot=True,
    )

    assert store.items == {}
    assert dispatched == []


@pytest.mark.asyncio
async def test_marked_feedback_with_no_run_is_persisted_unrouted() -> None:
    """Ticket-origin feedback for a task_ref with no run yet is still
    persisted (workflow_id=None) — routing arrives if/when a run exists."""
    store = _FakeFeedbackStore()
    service, dispatched = _intake(store=store)

    await service.intake(
        _feedback(), task_ref="o/r#1", source=_FakeSource(),
    )

    item = store.items["gh-issue-comment:o/r#1"]
    assert item.workflow_id is None
    assert item.state == "queued"
    assert dispatched == [item]


@pytest.mark.asyncio
async def test_routes_to_the_newest_run_for_task_ref() -> None:
    """Ticket-origin feedback routes to the newest of several runs
    sharing the same task_ref."""
    workflows = WorkflowRegistry()
    workflows.create(WorkflowRun(id="wf-old", repo="o/r", task_ref="o/r#1"))
    workflows.create(WorkflowRun(id="wf-new", repo="o/r", task_ref="o/r#1"))
    store = _FakeFeedbackStore()
    service, _ = _intake(store=store, workflows=workflows)

    await service.intake(_feedback(), task_ref="o/r#1", source=_FakeSource())

    item = store.items["gh-issue-comment:o/r#1"]
    assert item.workflow_id == "wf-new"


@pytest.mark.asyncio
async def test_claim_dedups_a_race_between_transports() -> None:
    """A second intake call for the same external_id is a silent no-op —
    the dedup that guards a webhook/poll race or a re-delivery."""
    store = _FakeFeedbackStore()
    service, dispatched = _intake(store=store)

    await service.intake(_feedback(), task_ref="o/r#1", source=_FakeSource())
    await service.intake(_feedback(), task_ref="o/r#1", source=_FakeSource())

    assert len(store.items) == 1
    assert len(dispatched) == 1


@pytest.mark.asyncio
async def test_acknowledge_is_called_after_persisting() -> None:
    """A successful intake calls source.acknowledge with the feedback."""
    source = _FakeSource()
    service, _ = _intake()

    await service.intake(_feedback(), task_ref="o/r#1", source=source)

    assert source.acknowledged == ["gh-issue-comment:o/r#1"]


@pytest.mark.asyncio
async def test_failed_acknowledge_never_raises_or_blocks_persistence() -> None:
    """A raising acknowledge is swallowed — persistence already happened
    (FR-014's acknowledgment is observably separate from processing)."""
    store = _FakeFeedbackStore()
    service, dispatched = _intake(store=store)

    await service.intake(
        _feedback(), task_ref="o/r#1", source=_FakeSource(raise_on_ack=True),
    )

    assert len(store.items) == 1
    assert len(dispatched) == 1


@pytest.mark.asyncio
async def test_review_origin_is_not_routed_this_phase() -> None:
    """Review-origin feedback is persisted but not routed to a run this
    phase — that routing arrives with User Story 3's dispatch wiring."""
    workflows = WorkflowRegistry()
    workflows.create(WorkflowRun(id="wf-1", repo="o/r", task_ref="o/r#1"))
    store = _FakeFeedbackStore()
    service, _ = _intake(store=store, workflows=workflows)

    await service.intake(
        _feedback(origin="review"), task_ref="o/r#1", source=_FakeSource(),
    )

    item = store.items["gh-issue-comment:o/r#1"]
    assert item.workflow_id is None
