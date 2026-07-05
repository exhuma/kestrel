"""Write-through persistence for workflow runs."""
from __future__ import annotations

from functools import lru_cache

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.models_workflow import WorkflowRun, WorkflowStep
from app.persistence.db import get_sessionmaker
from app.persistence.tables import (
    NotificationRow,
    WorkflowRunRow,
    WorkflowStepRow,
)


class WorkflowStore:
    """Persists workflow runs and their steps."""

    def __init__(
        self, factory: sessionmaker[Session]
    ) -> None:
        self._factory = factory

    def save(self, run: WorkflowRun) -> None:
        """
        Upsert a run and all of its steps.

        Called at every state transition, so the database
        always holds the latest checkpoint.

        :param run: The run to persist.
        """
        with self._factory.begin() as db:
            db.merge(
                WorkflowRunRow(
                    id=run.id,
                    repo=run.repo,
                    issue_number=run.issue_number,
                    issue_title=run.issue_title,
                    base_branch=run.base_branch,
                    branch=run.branch,
                    workspace=run.workspace,
                    status=run.status,
                    pr_url=run.pr_url,
                    error=run.error,
                )
            )
            for i, step in enumerate(run.steps):
                db.merge(
                    WorkflowStepRow(
                        workflow_id=run.id,
                        position=i,
                        name=step.name,
                        session_id=step.session_id,
                        status=step.status,
                        deliverable=step.deliverable,
                        model=step.model,
                        refine_round=step.refine_round,
                    )
                )

    def delete(self, workflow_id: str) -> None:
        """
        Delete a run with its steps and notifications (children first).

        :param workflow_id: Unique id of the run to delete.
        """
        with self._factory.begin() as db:
            db.execute(
                delete(NotificationRow).where(
                    NotificationRow.workflow_id == workflow_id
                )
            )
            db.execute(
                delete(WorkflowStepRow).where(
                    WorkflowStepRow.workflow_id == workflow_id
                )
            )
            row = db.get(WorkflowRunRow, workflow_id)
            if row is not None:
                db.delete(row)

    def load_all(self) -> list[WorkflowRun]:
        """
        Load all persisted runs with their steps.

        :returns: Fully hydrated runs, steps in order.
        """
        with self._factory() as db:
            runs: list[WorkflowRun] = []
            for row in db.scalars(select(WorkflowRunRow)):
                stmt = (
                    select(WorkflowStepRow)
                    .where(
                        WorkflowStepRow.workflow_id == row.id
                    )
                    .order_by(WorkflowStepRow.position)
                )
                steps = [
                    WorkflowStep(
                        name=s.name,
                        session_id=s.session_id,
                        status=s.status,
                        deliverable=s.deliverable,
                        model=s.model,
                        refine_round=s.refine_round,
                    )
                    for s in db.scalars(stmt)
                ]
                runs.append(
                    WorkflowRun(
                        id=row.id,
                        repo=row.repo,
                        issue_number=row.issue_number,
                        issue_title=row.issue_title,
                        base_branch=row.base_branch,
                        branch=row.branch,
                        workspace=row.workspace,
                        status=row.status,
                        steps=steps,
                        pr_url=row.pr_url,
                        error=row.error,
                    )
                )
            return runs


@lru_cache
def get_workflow_store() -> WorkflowStore:
    """
    Return the process-wide WorkflowStore singleton.

    :returns: The cached workflow store instance.
    """
    return WorkflowStore(get_sessionmaker())
