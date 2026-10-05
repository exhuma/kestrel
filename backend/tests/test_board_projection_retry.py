"""A comment that failed to post is posted again, once (feature 046,
T022, research R7).

The ledger kept only a hash, so a failed post was lost for good. It now
keeps the document and where to post it, and ``ProjectionRetryService``
re-posts it with backoff. Taking a row on is one atomic update, so a
restart, a second loop or a repeated announcement pass never doubles it.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.documents import Document, Marker
from app.models_board import CardKind
from app.models_board_records import ExternalProjectionRecord
from app.persistence.board_time import now_utc
from app.services.board.projection_retry import (
    MAX_ATTEMPTS,
    ProjectionRetryService,
    due_at,
)
from app.services.task_sources import TaskSourceRegistry
from tests.announcement_support import (
    SOURCE,
    TASK_REF,
    WORKFLOW_ID,
    Stack,
    build_stack,
    open_gate,
    ticket,
)
from tests.document_helpers import doc

_INTERVAL = 120.0
_FAR_FUTURE = timedelta(days=30)
_SECOND_ATTEMPT = 2


def _failing(tmp_path: Path, failures: int) -> Stack:
    """A stack whose ticket refuses the first *failures* comments, with a
    gate waiting to be announced."""
    stack = build_stack(tmp_path, source=ticket(failures=failures))
    open_gate(stack, CardKind.PRD_GATE, None, "approve_prd")
    return stack


def _retrier(stack: Stack) -> ProjectionRetryService:
    return ProjectionRetryService(
        stack.projections, stack.store,
        TaskSourceRegistry({SOURCE: stack.source}, {}),
        interval_seconds=_INTERVAL,
    )


def _failed_record(stack: Stack):
    (record,) = stack.projections.retryable()
    return record


@pytest.mark.asyncio
async def test_a_failed_post_is_stored_with_its_payload_and_task_ref(
    tmp_path: Path,
) -> None:
    """Ensure the ledger keeps what it could not post, and where."""
    stack = _failing(tmp_path, failures=1)

    await stack.service.announce(WORKFLOW_ID)

    record = _failed_record(stack)
    assert stack.source.comments() == []
    assert record.task_ref == TASK_REF
    assert isinstance(record.payload, Document)
    assert "approve it" in record.payload.plain_text()
    assert record.attempts == 0
    assert "unreachable" in record.error


@pytest.mark.asyncio
async def test_the_announcement_pass_does_not_post_a_failed_key_again(
    tmp_path: Path,
) -> None:
    """Ensure a failed announcement waits for the retry loop rather than
    being posted by every later pass."""
    stack = _failing(tmp_path, failures=1)
    await stack.service.announce(WORKFLOW_ID)

    await stack.service.announce(WORKFLOW_ID)
    await stack.service.announce(WORKFLOW_ID)

    assert stack.source.comments() == []


@pytest.mark.asyncio
async def test_the_retry_loop_posts_it_once_the_ticket_answers(
    tmp_path: Path,
) -> None:
    """Ensure the stored comment reaches the ticket, with the document
    that was planned and the adapter's marker."""
    stack = _failing(tmp_path, failures=1)
    await stack.service.announce(WORKFLOW_ID)
    record = _failed_record(stack)
    due = due_at(record, _INTERVAL)

    posted = await _retrier(stack).poll_once(now=due)

    (comment,) = stack.source.comments()
    assert posted == 1
    assert comment.blocks == (*record.payload.blocks, Marker("posted"))
    assert stack.projections.retryable() == []


@pytest.mark.asyncio
async def test_a_retry_waits_longer_each_time_it_fails(
    tmp_path: Path,
) -> None:
    """Ensure backoff doubles with the attempts, so an outage is not
    hammered."""
    stack = _failing(tmp_path, failures=_SECOND_ATTEMPT)
    await stack.service.announce(WORKFLOW_ID)
    retrier = _retrier(stack)
    first = _failed_record(stack)
    early = first.updated_at + timedelta(seconds=_INTERVAL / 2)

    assert await retrier.poll_once(now=early) == 0  # not due yet
    assert await retrier.poll_once(now=due_at(first, _INTERVAL)) == 0
    second = _failed_record(stack)
    assert second.attempts == 1

    one_interval = second.updated_at + timedelta(seconds=_INTERVAL)
    assert await retrier.poll_once(now=one_interval) == 0  # doubled wait
    assert await retrier.poll_once(now=due_at(second, _INTERVAL)) == 1
    assert len(stack.source.comments()) == 1


@pytest.mark.asyncio
async def test_a_restart_never_posts_it_twice(tmp_path: Path) -> None:
    """Ensure a posted comment stays posted across restarts: a fresh loop
    (a restarted process) finds nothing to do."""
    stack = _failing(tmp_path, failures=1)
    await stack.service.announce(WORKFLOW_ID)
    await _retrier(stack).poll_once(now=now_utc(None) + _FAR_FUTURE)

    again = _retrier(stack)
    assert await again.poll_once(now=now_utc(None) + _FAR_FUTURE) == 0
    await stack.service.announce(WORKFLOW_ID)

    assert len(stack.source.comments()) == 1


@pytest.mark.asyncio
async def test_a_row_taken_on_is_not_taken_on_again(tmp_path: Path) -> None:
    """Ensure two loops (or a restart mid-post) cannot both post a row:
    the take-on is atomic, and a crash mid-post leaves the row taken."""
    stack = _failing(tmp_path, failures=1)
    await stack.service.announce(WORKFLOW_ID)
    record = _failed_record(stack)

    assert stack.projections.begin_retry(record.id) is True
    assert stack.projections.begin_retry(record.id) is False

    # The process died after taking it on: the row is pending, and no
    # later loop posts it (a comment lost beats a comment doubled).
    later = now_utc(None) + _FAR_FUTURE
    assert await _retrier(stack).poll_once(now=later) == 0
    assert stack.source.comments() == []


@pytest.mark.asyncio
async def test_a_row_from_before_the_ledger_kept_payloads_is_left_alone(
    tmp_path: Path,
) -> None:
    """Ensure an old row, with no payload or task_ref, is never retried."""
    stack = build_stack(tmp_path)
    old = stack.projections._store.plan(ExternalProjectionRecord(
        id="projection-old", workflow_id=WORKFLOW_ID, kind="gate",
        idempotency_key="gate:old", payload_hash="h",
    ))
    stack.projections.fail(old.id, "boom")

    posted = await _retrier(stack).poll_once(
        now=now_utc(None) + _FAR_FUTURE
    )

    assert posted == 0
    assert stack.source.comments() == []


@pytest.mark.asyncio
async def test_a_row_that_keeps_failing_is_eventually_left_in_the_ledger(
    tmp_path: Path,
) -> None:
    """Ensure a comment the ticket never accepts stops being retried but
    stays visible as failed."""
    stack = _failing(tmp_path, failures=MAX_ATTEMPTS + _SECOND_ATTEMPT)
    await stack.service.announce(WORKFLOW_ID)
    retrier = _retrier(stack)

    for _ in range(MAX_ATTEMPTS + _SECOND_ATTEMPT):
        await retrier.poll_once(now=now_utc(None) + _FAR_FUTURE)

    record = _failed_record(stack)
    assert record.attempts == MAX_ATTEMPTS
    assert stack.source.comments() == []


def test_the_wait_is_the_interval_doubled_per_attempt() -> None:
    """Ensure the backoff is a pure function of the attempts."""
    last = datetime(2026, 10, 5, 12, 0)

    def record(attempts: int) -> ExternalProjectionRecord:
        return ExternalProjectionRecord(
            id="p", workflow_id="w", kind="status", idempotency_key="k",
            payload_hash="h", payload=doc("x"), task_ref="T",
            attempts=attempts, updated_at=last,
        )

    assert due_at(record(0), _INTERVAL) == last + timedelta(
        seconds=_INTERVAL
    )
    assert due_at(record(_SECOND_ATTEMPT), _INTERVAL) == last + timedelta(
        seconds=_INTERVAL * 4
    )
