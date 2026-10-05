"""Tests for posting a planned external projection to its task source
(feature 026, T067).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.persistence.board_projection_store import BoardProjectionStore
from app.services.board.projections import ProjectionsService
from app.services.board.write_back import ProjectionRequest, post_projection
from tests.board_test_support import board_session_factory
from tests.document_helpers import doc

_PAYLOAD = doc("PRD approved.")


def _service(tmp_path: Path) -> ProjectionsService:
    factory = board_session_factory(tmp_path)
    return ProjectionsService(BoardProjectionStore(factory))


class _FakeTaskSource:
    def __init__(
        self, *, external_id: str = "comment-1", fails: bool = False
    ) -> None:
        self.calls: list[tuple[str, str]] = []
        self._external_id = external_id
        self._fails = fails

    async def post_comment(self, ref: str, body) -> str:
        self.calls.append((ref, body))
        if self._fails:
            raise RuntimeError("task source unreachable")
        return self._external_id


@pytest.mark.asyncio
async def test_posts_a_fresh_projection_and_completes_it(
    tmp_path: Path,
) -> None:
    projections = _service(tmp_path)
    task_source = _FakeTaskSource(external_id="comment-42")
    request = ProjectionRequest(
        workflow_id="wf-1", task_ref="owner/repo#1", kind="gate",
        idempotency_key="gate:card-1", payload=_PAYLOAD,
    )

    await post_projection(request, task_source, projections)

    assert task_source.calls == [("owner/repo#1", _PAYLOAD)]
    record = projections.retryable()
    assert record == []  # completed, not retryable


@pytest.mark.asyncio
async def test_a_second_call_for_the_same_key_does_not_post_again(
    tmp_path: Path,
) -> None:
    projections = _service(tmp_path)
    task_source = _FakeTaskSource()
    request = ProjectionRequest(
        workflow_id="wf-1", task_ref="owner/repo#1", kind="gate",
        idempotency_key="gate:card-1", payload=_PAYLOAD,
    )

    await post_projection(request, task_source, projections)
    await post_projection(request, task_source, projections)

    assert len(task_source.calls) == 1


@pytest.mark.asyncio
async def test_a_post_failure_is_recorded_as_retryable_not_raised(
    tmp_path: Path,
) -> None:
    projections = _service(tmp_path)
    task_source = _FakeTaskSource(fails=True)
    request = ProjectionRequest(
        workflow_id="wf-1", task_ref="owner/repo#1", kind="gate",
        idempotency_key="gate:card-1", payload=_PAYLOAD,
    )

    await post_projection(request, task_source, projections)  # must not raise

    assert len(projections.retryable()) == 1
