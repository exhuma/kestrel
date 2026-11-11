"""Posts one planned external projection to its task source (feature 026,
T067, FR-033).

``projections.py`` (T066) only makes the *decision* to project durable
and idempotent, per its own module docstring: "actually posting to a
task source is a later phase's concern." This module is that later
phase, for the one milestone kind wired so far: a resolved human gate.
"""
from __future__ import annotations

from app.documents import Document
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
        external_id = await deliver(
            request.kind, request.idempotency_key, task_source,
            request.task_ref, request.payload,
        )
    except Exception as exc:  # noqa: BLE001 — record, don't propagate
        projections.fail(record.id, str(exc))
        return
    projections.complete(record.id, external_id=external_id)


async def deliver(
    kind: str,
    idempotency_key: str,
    task_source: TaskSource,
    task_ref: str,
    payload: Document,
) -> str:
    """Put one projection on the ticket: an ``attachment`` as a file, named
    by the last part of its key (``attachment:<card>:PRD.md``); any other
    kind as a comment.

    :returns: What the source made of it (a URL or path).
    """
    if kind == "attachment":
        name = idempotency_key.rsplit(":", 1)[-1]
        return await task_source.attach_document(task_ref, name, payload)
    return await task_source.post_comment(task_ref, payload)
