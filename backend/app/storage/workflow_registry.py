"""In-memory registry of workflow runs."""
from __future__ import annotations

from functools import lru_cache

from app.models_workflow import WorkflowRun


class WorkflowRegistry:
    """Stores workflow runs in insertion order."""

    def __init__(self) -> None:
        self._runs: dict[str, WorkflowRun] = {}

    def create(self, run: WorkflowRun) -> WorkflowRun:
        """Store a new run and return it."""
        self._runs[run.id] = run
        return run

    def get(self, workflow_id: str) -> WorkflowRun | None:
        """Return a run by id, or None."""
        return self._runs.get(workflow_id)

    def list(self) -> list[WorkflowRun]:
        """Return all runs in insertion order."""
        return list(self._runs.values())


@lru_cache
def get_workflow_registry() -> WorkflowRegistry:
    """Return the process-wide WorkflowRegistry singleton."""
    return WorkflowRegistry()
