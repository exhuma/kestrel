"""Posts one planned external projection to its task source (feature 026,
T067, FR-033).

``projections.py`` (T066) only makes the *decision* to project durable
and idempotent, per its own module docstring: "actually posting to a
task source is a later phase's concern." This module is that later
phase, for the one milestone kind wired so far: a resolved human gate.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.ports import TaskSource
from app.services.board.projections import ProjectionsService


@dataclass(frozen=True)
class ProjectionRequest:
    """What to project and where. Bundled to keep
    :func:`post_projection`'s argument count within the repo's limit.

    :param kind: One of ``projections.VALID_PROJECTION_KINDS``.
    :param idempotency_key: Unique per real-world event (FR-033) — a
        second request for the same key is a no-op once the first
        completes.
    :param payload: The safe comment body to post.
    """

    workflow_id: str
    task_ref: str
    kind: str
    idempotency_key: str
    payload: str


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
    record = projections.plan(
        request.workflow_id, request.kind, request.idempotency_key,
        request.payload,
    )
    if record.state != "pending":
        return
    try:
        external_id = await task_source.post_comment(
            request.task_ref, request.payload
        )
    except Exception as exc:  # noqa: BLE001 — record, don't propagate
        projections.fail(record.id, str(exc))
        return
    projections.complete(record.id, external_id=external_id)
