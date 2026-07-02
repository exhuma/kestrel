"""Registry of workflow runs with optional persistence."""
from __future__ import annotations

from functools import lru_cache

from app.models_workflow import WorkflowRun
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

    def save(self, run: WorkflowRun) -> None:
        """
        Persist a run's current state.

        Called at every workflow state transition; a no-op
        when the registry has no store (unit tests).

        :param run: The run to checkpoint.
        """
        if self._store is not None:
            self._store.save(run)

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
