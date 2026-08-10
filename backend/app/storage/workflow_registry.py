"""Registry of workflow runs with optional persistence."""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache

from app.models_workflow import RoundChip, StepSession, WorkflowRun
from app.persistence.workflow_store import (
    WorkflowStore,
    get_workflow_store,
)


class WorkflowRegistry:
    """Stores workflow runs in insertion order."""

    def __init__(
        self, store: WorkflowStore | None = None
    ) -> None:
        self._runs: dict[str, WorkflowRun] = {}
        self._store = store

    def create(self, run: WorkflowRun) -> WorkflowRun:
        """
        Store a new run and return it.

        :param run: The run to register.
        :returns: The same run, for chaining.
        """
        self._runs[run.id] = run
        if self._store is not None:
            self._store.save(run)
        return run

    def get(self, workflow_id: str) -> WorkflowRun | None:
        """
        Return a run by id, or None.

        :param workflow_id: Unique id of the run.
        :returns: The run, or None if unknown.
        """
        return self._runs.get(workflow_id)

    def list(self) -> list[WorkflowRun]:
        """
        Return all runs in insertion order.

        :returns: All registered runs.
        """
        return list(self._runs.values())

    def remove(self, workflow_id: str) -> None:
        """
        Drop a run from the registry and its persisted rows.

        The write-through counterpart to :meth:`create`.

        :param workflow_id: Unique id of the run to remove.
        """
        self._runs.pop(workflow_id, None)
        if self._store is not None:
            self._store.delete(workflow_id)

    def save(self, run: WorkflowRun) -> None:
        """
        Persist a run's current state.

        Called at every workflow state transition; a no-op
        when the registry has no store (unit tests).

        :param run: The run to checkpoint.
        """
        if self._store is not None:
            self._store.save(run)

    def save_round_chips(
        self,
        workflow_id: str,
        step_name: str,
        chips: list[StepSession],
        retired_at: datetime,
    ) -> None:
        """
        Freeze a step's live chips into durable round history.

        A no-op when the registry has no store (unit tests).

        :param workflow_id: Id of the run the chips belong to.
        :param step_name: Name of the step being retired.
        :param chips: The step's live chip set at the moment of retiring.
        :param retired_at: Timestamp to stamp every chip in this group.
        """
        if self._store is not None:
            self._store.save_round_chips(
                workflow_id, step_name, chips, retired_at
            )

    def load_round_chips(self, workflow_id: str) -> list[RoundChip]:
        """
        Load a run's retired round-chip history, oldest first.

        Empty when the registry has no store (unit tests).

        :param workflow_id: Id of the run to load history for.
        :returns: Frozen chips ordered by step, round, then insertion.
        """
        if self._store is None:
            return []
        return self._store.load_round_chips(workflow_id)

    def preload(self, runs: list[WorkflowRun]) -> None:
        """
        Seed the registry with persisted runs.

        Does not write back to the store.

        :param runs: Runs loaded from persistence.
        """
        for run in runs:
            self._runs[run.id] = run


@lru_cache
def get_workflow_registry() -> WorkflowRegistry:
    """
    Return the process-wide WorkflowRegistry singleton.

    Preloads persisted runs so history survives restarts.
    Requires migrations (``uv run alembic upgrade head``).

    :returns: The cached workflow registry instance.
    """
    store = get_workflow_store()
    registry = WorkflowRegistry(store=store)
    registry.preload(store.load_all())
    return registry
