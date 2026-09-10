"""Durable child-task identity, lifecycle state, and re-adoption claims."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from typing import Protocol

from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.db import get_sessionmaker
from app.persistence.tables import ChildTaskLinkRow


class ChildTaskLinks(Protocol):
    """Persistence contract used by publication and re-adoption services."""

    def record(self, parent_workflow_id: str, task_ref: str) -> None:
        """Persist one newly published child task reference."""
        ...

    def record_run(self, task_ref: str, workflow_id: str) -> None:
        """Record the latest run for a linked child task."""
        ...

    def observe_source_state(self, task_ref: str, state: str) -> None:
        """Persist one observed source lifecycle state."""
        ...

    def linked_refs(self, prefix: str) -> set[str]:
        """Return non-retired child refs belonging to one source prefix."""
        ...

    def observe_generation(self, task_ref: str, generation: str) -> bool:
        """Record a fixture generation and report a changed repeat value."""
        ...

    def claim_reopen(self, task_ref: str, workflow_id: str) -> bool:
        """Claim a closed-to-open transition for one newest child run."""
        ...

    def complete_reopen(self, task_ref: str, workflow_id: str) -> None:
        """Persist a successful successor as the current child run."""
        ...

    def release_reopen(self, task_ref: str) -> None:
        """Release a failed reopen claim for later retry."""
        ...

    def retirement_candidates(self, cutoff: datetime) -> list[tuple[str, str]]:
        """Return due ``(task_ref, latest_workflow_id)`` child tasks."""
        ...

    def mark_retired(self, task_ref: str, now: datetime) -> bool:
        """Persist retirement once and report whether this call marked it."""
        ...

    def is_retired(self, task_ref: str) -> bool:
        """Return whether monitoring has permanently retired ``task_ref``."""
        ...

    def is_linked(self, task_ref: str) -> bool:
        """Return whether ``task_ref`` is a non-retired published child."""
        ...

    def claim_retirement(self, task_ref: str) -> bool:
        """Claim one due child before its source notice is posted."""
        ...

    def release_retirement(self, task_ref: str) -> None:
        """Release a claim when its source notice cannot be posted."""
        ...


class ChildTaskStore:
    """Records published children and serializes reopen successor creation."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        """Create a store backed by ``factory`` transactions."""
        self._factory = factory

    def record(self, parent_workflow_id: str, task_ref: str) -> None:
        """Persist a newly published child as source-open and not yet run."""
        with self._factory.begin() as db:
            db.add(
                ChildTaskLinkRow(
                    task_ref=task_ref,
                    parent_workflow_id=parent_workflow_id,
                    source_state="open",
                )
            )

    def record_run(self, task_ref: str, workflow_id: str) -> None:
        """Set the newest run for a published child, if it is linked."""
        with self._factory.begin() as db:
            row = db.get(ChildTaskLinkRow, task_ref)
            if row is not None:
                row.latest_workflow_id = workflow_id

    def observe_source_state(self, task_ref: str, state: str) -> None:
        """Persist a child's current source state when it is monitored."""
        now = datetime.now(timezone.utc)
        with self._factory.begin() as db:
            row = db.get(ChildTaskLinkRow, task_ref)
            if row is None or row.retired_at is not None:
                return
            if state == "closed" and row.source_state not in {
                "closed",
                "retiring",
            }:
                row.closed_at = now
            elif state != "closed":
                row.closed_at = None
            row.source_state = state

    def claim_reopen(self, task_ref: str, workflow_id: str) -> bool:
        """Claim one eligible closed-to-open transition for ``workflow_id``."""
        with self._factory.begin() as db:
            result = db.execute(
                update(ChildTaskLinkRow)
                .where(
                    ChildTaskLinkRow.task_ref == task_ref,
                    ChildTaskLinkRow.latest_workflow_id == workflow_id,
                    ChildTaskLinkRow.source_state == "closed",
                    ChildTaskLinkRow.retired_at.is_(None),
                )
                .values(source_state="reopening")
            )
            return result.rowcount == 1

    def linked_refs(self, prefix: str) -> set[str]:
        """Return non-retired child references for a task-source prefix."""
        with self._factory() as db:
            rows = db.query(ChildTaskLinkRow.task_ref).filter(
                ChildTaskLinkRow.task_ref.startswith(prefix),
                ChildTaskLinkRow.retired_at.is_(None),
            )
            return {task_ref for (task_ref,) in rows}

    def observe_generation(self, task_ref: str, generation: str) -> bool:
        """Record a fixture generation and close a child on a changed value.

        The first value is only a baseline. A changed later value is the fixture
        source's explicit retrigger gesture and creates a close/open edge.
        """
        with self._factory.begin() as db:
            row = db.get(ChildTaskLinkRow, task_ref)
            if row is None or row.retired_at is not None:
                return False
            changed = (
                row.source_generation is not None
                and row.source_generation != generation
            )
            row.source_generation = generation
            if changed:
                row.source_state = "closed"
                row.closed_at = datetime.now(timezone.utc)
            return changed

    def complete_reopen(self, task_ref: str, workflow_id: str) -> None:
        """Store a claimed successor as the open child-run head."""
        with self._factory.begin() as db:
            row = db.get(ChildTaskLinkRow, task_ref)
            if row is not None:
                row.latest_workflow_id = workflow_id
                row.source_state = "open"
                row.closed_at = None

    def release_reopen(self, task_ref: str) -> None:
        """Make a failed successor creation eligible for a later retry."""
        with self._factory.begin() as db:
            row = db.get(ChildTaskLinkRow, task_ref)
            if row is not None and row.source_state == "reopening":
                row.source_state = "closed"

    def retirement_candidates(self, cutoff: datetime) -> list[tuple[str, str]]:
        """Return unretired closed children whose closure predates cutoff."""
        with self._factory() as db:
            rows = db.query(ChildTaskLinkRow).filter(
                ChildTaskLinkRow.source_state == "closed",
                ChildTaskLinkRow.closed_at <= cutoff,
                ChildTaskLinkRow.retired_at.is_(None),
                ChildTaskLinkRow.latest_workflow_id.is_not(None),
            )
            return [(row.task_ref, row.latest_workflow_id) for row in rows]

    def mark_retired(self, task_ref: str, now: datetime) -> bool:
        """Set ``retired_at`` once after the retirement notice is posted."""
        with self._factory.begin() as db:
            result = db.execute(
                update(ChildTaskLinkRow)
                .where(
                    ChildTaskLinkRow.task_ref == task_ref,
                    ChildTaskLinkRow.retired_at.is_(None),
                )
                .values(retired_at=now)
            )
            return result.rowcount == 1

    def is_retired(self, task_ref: str) -> bool:
        """Return whether a linked child has already been retired."""
        with self._factory() as db:
            row = db.get(ChildTaskLinkRow, task_ref)
            return row is not None and row.retired_at is not None

    def is_linked(self, task_ref: str) -> bool:
        """Return whether ``task_ref`` remains linked and unretired."""
        with self._factory() as db:
            row = db.get(ChildTaskLinkRow, task_ref)
            return row is not None and row.retired_at is None

    def claim_retirement(self, task_ref: str) -> bool:
        """Atomically reserve a closed child for one retirement notice."""
        with self._factory.begin() as db:
            result = db.execute(
                update(ChildTaskLinkRow)
                .where(
                    ChildTaskLinkRow.task_ref == task_ref,
                    ChildTaskLinkRow.source_state == "closed",
                    ChildTaskLinkRow.retired_at.is_(None),
                )
                .values(source_state="retiring")
            )
            return result.rowcount == 1

    def release_retirement(self, task_ref: str) -> None:
        """Return an unposted retirement claim to the closed state."""
        with self._factory.begin() as db:
            db.execute(
                update(ChildTaskLinkRow)
                .where(
                    ChildTaskLinkRow.task_ref == task_ref,
                    ChildTaskLinkRow.source_state == "retiring",
                )
                .values(source_state="closed")
            )


@lru_cache
def get_child_task_store() -> ChildTaskStore:
    """Return the process-wide ChildTaskStore singleton."""
    return ChildTaskStore(get_sessionmaker())
