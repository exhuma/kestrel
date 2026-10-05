"""External-projection planning and retry handling (feature 026, T066,
FR-033..FR-035).

Only four milestone kinds ever project to a task source by default
(FR-033): ordinary claims, retries, and routine completions never reach
this module at all (FR-034) — a caller decides *that* something is
projection-worthy; this service only makes recording and retrying that
decision durable and idempotent. Actually posting to a task source is a
later phase's concern (the old driver's own task-source/notification
code, replaced only at the Phase 10 clean break) — this is the ledger it
will be built on.
"""
from __future__ import annotations

import hashlib
import uuid

from app.documents import Document
from app.models_board_records import ExternalProjectionRecord
from app.persistence.board_projection_store import BoardProjectionStore

#: FR-033's closed vocabulary of default-projected milestones.
VALID_PROJECTION_KINDS = frozenset(
    {"gate", "escalation", "approved_artifact", "delivery"}
)


class UnsupportedProjectionKindError(Exception):
    """Raised when a projection kind isn't one FR-033 allows."""


class ProjectionsService:
    """Plans, resolves, and retries external-projection ledger entries."""

    def __init__(self, store: BoardProjectionStore) -> None:
        self._store = store

    def plan(
        self,
        workflow_id: str,
        kind: str,
        idempotency_key: str,
        payload: Document,
    ) -> ExternalProjectionRecord:
        """Plan one projection, or return the already-recorded one.

        :param payload: The safe content that will be sent; only its hash
            is retained (integrity check, never the content itself).
        :raises UnsupportedProjectionKindError: If *kind* is not one of
            :data:`VALID_PROJECTION_KINDS`.
        """
        if kind not in VALID_PROJECTION_KINDS:
            raise UnsupportedProjectionKindError(
                f"unsupported projection kind: {kind}"
            )
        payload_hash = hashlib.sha256(
            repr(payload).encode("utf-8")
        ).hexdigest()
        return self._store.plan(
            ExternalProjectionRecord(
                id=f"projection-{uuid.uuid4().hex[:8]}",
                workflow_id=workflow_id,
                kind=kind,
                idempotency_key=idempotency_key,
                payload_hash=payload_hash,
            )
        )

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

    def owned_external_ids(self, workflow_id: str) -> list[tuple[str, str]]:
        """Return ``(kind, external_id)`` for every external resource
        Kestrel owns for *workflow_id* — the cleanup boundary (FR-035)."""
        return self._store.owned_external_ids(workflow_id)
