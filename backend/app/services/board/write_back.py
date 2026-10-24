"""Posts one planned external projection to its task source (feature 026,
T067, FR-033).

``projections.py`` (T066) only makes the *decision* to project durable
and idempotent, per its own module docstring: "actually posting to a
task source is a later phase's concern." This module is that later
phase, for the one milestone kind wired so far: a resolved human gate.
"""
from __future__ import annotations

from app.ports import TaskSource
from app.services.board.projections import (
    ProjectionRequest,
    ProjectionsService,
)


async def post_projection(
    request: ProjectionRequest,
    task_source: TaskSource,
    projections: ProjectionsService,
) -> None:
    """Plan, post, and resolve one projection.

    A no-op if ``request.idempotency_key`` already resolved to a
    ``completed`` (or currently-being-retried ``retryable_failure``)
    record — only a fresh or still-``pending`` plan is actually posted.
    A post failure is recorded as a retryable failure, never raised: a
    task-source outage must not be treated as though the board mutation
    that triggered this projection itself failed.
    """
    record = projections.plan(request)
    # A row a retry has taken on is that retry's to post, not ours.
    if record.state != "pending" or record.attempts:
        return
    try:
        external_id = await task_source.post_comment(
            request.task_ref, request.payload
        )
    except Exception as exc:  # noqa: BLE001 — record, don't propagate
        projections.fail(record.id, str(exc))
        return
    projections.complete(record.id, external_id=external_id)
