"""External-projection planning and retry handling (feature 026, T066,
FR-033..FR-035).

Only a closed set of milestone kinds ever project to a task source
(FR-033): ordinary claims, retries, and routine completions never reach
this module at all (FR-034) — a caller decides *that* something is
projection-worthy; this service only makes recording and retrying that
decision durable and idempotent. Since feature 046 the ledger keeps what
it posts (the document and where to post it), so a failed post can be
posted again later (``projection_retry.py``).
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime

from app.documents import Document
from app.models_board_records import ExternalProjectionRecord
from app.persistence.board_projection_store import BoardProjectionStore

#: FR-033's closed vocabulary of default-projected milestones, plus the
#: kinds feature 046 adds: a gate opening, a status line, a reply's
#: outcome; #64's: a file attached to the ticket, a work item, and a
#: link between two work items; and #99's: the note on a work item that
#: was given back to a person after kestrel took it.
VALID_PROJECTION_KINDS = frozenset(
    {
        "gate", "escalation", "approved_artifact", "delivery",
        "gate_opened", "status", "reply", "attachment", "work_item",
        "work_item_link", "handback",
    }
)
#: Kinds the work-item publisher creates and retries itself
#: (``work_items.py``); the comment retry loop leaves them alone.
WORK_ITEM_KINDS = frozenset({"work_item", "work_item_link"})


@dataclass(frozen=True)
class ProjectionRequest:
    """What to project and where. Bundled to keep the ledger's and
    :func:`~app.services.board.write_back.post_projection`'s argument
    counts within the repo's limit.

    :param kind: One of :data:`VALID_PROJECTION_KINDS`.
    :param idempotency_key: Unique per real-world event (FR-033) — a
        second request for the same key is a no-op once the first
        completes.
    :param payload: The safe comment body to post, as a document.
    """

    workflow_id: str
    task_ref: str
    kind: str
    idempotency_key: str
    payload: Document


class UnsupportedProjectionKindError(Exception):
    """Raised when a projection kind isn't one FR-033 allows."""


class ProjectionsService:
    """Plans, resolves, and retries external-projection ledger entries."""

    def __init__(self, store: BoardProjectionStore) -> None:
        self._store = store

    def plan(self, request: ProjectionRequest) -> ExternalProjectionRecord:
        """Plan one projection, or return the already-recorded one.

        The record keeps the payload and where to post it, so a failed
        post can be retried; the hash is an integrity check on it.

        :raises UnsupportedProjectionKindError: If the kind is not one
            of :data:`VALID_PROJECTION_KINDS`.
        """
        if request.kind not in VALID_PROJECTION_KINDS:
            raise UnsupportedProjectionKindError(
                f"unsupported projection kind: {request.kind}"
            )
        payload_hash = hashlib.sha256(
            repr(request.payload).encode("utf-8")
        ).hexdigest()
        return self._store.plan(
            ExternalProjectionRecord(
                id=f"projection-{uuid.uuid4().hex[:8]}",
                workflow_id=request.workflow_id,
                kind=request.kind,
                idempotency_key=request.idempotency_key,
                payload_hash=payload_hash,
                task_ref=request.task_ref,
                payload=request.payload,
            )
        )

    def recorded(self, idempotency_key: str) -> bool:
        """Whether a projection for *idempotency_key* is already in the
        ledger, whatever its state."""
        return self._store.get_by_idempotency_key(idempotency_key) is not None

    def completed_at(self, idempotency_key: str) -> datetime | None:
        """When the projection for *idempotency_key* was durably
        delivered (naive UTC), or ``None`` while it is unposted, failed
        or unknown."""
        record = self._store.get_by_idempotency_key(idempotency_key)
        if record is None or record.state != "completed":
            return None
        return record.updated_at

    def external_id(self, idempotency_key: str) -> str | None:
        """What the source made of a delivered projection (a comment URL,
        a work item's key), or ``None`` while it is not delivered."""
        record = self._store.get_by_idempotency_key(idempotency_key)
        if record is None or record.state != "completed":
            return None
        return record.external_id

    def record(self, idempotency_key: str) -> ExternalProjectionRecord | None:
        """The ledger row for *idempotency_key*, if there is one."""
        return self._store.get_by_idempotency_key(idempotency_key)

    def complete(
        self, projection_id: str, *, external_id: str | None = None
    ) -> ExternalProjectionRecord:
        """Resolve a projection as durably delivered."""
        return self._store.mark_completed(
            projection_id, external_id=external_id
        )

    def fail(self, projection_id: str, error: str) -> ExternalProjectionRecord:
        """Resolve a projection attempt as retryable."""
        return self._store.mark_failed(projection_id, error)

    def retryable(self) -> list[ExternalProjectionRecord]:
        """Return every projection currently eligible for retry."""
        return self._store.list_retryable()

    def begin_retry(self, projection_id: str) -> bool:
        """Take a failed projection on for another post; ``False`` when
        someone else already has, or it is no longer failed."""
        return self._store.begin_retry(projection_id)
