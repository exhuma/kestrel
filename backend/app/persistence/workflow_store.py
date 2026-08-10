"""Write-through persistence for workflow runs."""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models_workflow import (
    RoundChip,
    StepSession,
    WorkflowRun,
    WorkflowStep,
)
from app.persistence.db import get_sessionmaker
from app.persistence.tables import (
    NotificationRow,
    WorkflowRoundChipRow,
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
                    source=run.source,
                    task_ref=run.task_ref,
                    artifact_dir=run.artifact_dir,
                    boundary=run.boundary,
                    active_seconds=run.active_seconds,
                    wait_seconds=run.wait_seconds,
                    clock_state=run.clock_state,
                    clock_since=run.clock_since,
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
                        verify_round=step.verify_round,
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
                delete(WorkflowRoundChipRow).where(
                    WorkflowRoundChipRow.workflow_id == workflow_id
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

    def save_round_chips(
        self,
        workflow_id: str,
        step_name: str,
        chips: list[StepSession],
        retired_at: datetime,
    ) -> None:
        """
        Freeze a step's live chips into durable round history.

        A no-op when ``chips`` is empty (nothing to retire). The new
        group's ``round_index`` is one past the highest already recorded
        for this ``(workflow_id, step_name)`` pair, so each retire call
        becomes its own round. A chip still "running" when frozen is
        persisted as "error" — it's terminal history now, not a normal
        completion.

        :param workflow_id: Id of the run the chips belong to.
        :param step_name: Name of the step being retired.
        :param chips: The step's live chip set at the moment of retiring.
        :param retired_at: Timestamp to stamp every chip in this group.
        """
        if not chips:
            return
        with self._factory.begin() as db:
            highest = db.scalar(
                select(func.max(WorkflowRoundChipRow.round_index)).where(
                    WorkflowRoundChipRow.workflow_id == workflow_id,
                    WorkflowRoundChipRow.step_name == step_name,
                )
            )
            round_index = 0 if highest is None else highest + 1
            for chip in chips:
                db.add(
                    WorkflowRoundChipRow(
                        workflow_id=workflow_id,
                        step_name=step_name,
                        round_index=round_index,
                        profile_id=chip.profile_id,
                        label=chip.label,
                        badge=chip.badge,
                        session_id=chip.session_id,
                        status=(
                            "error" if chip.status == "running"
                            else chip.status
                        ),
                        error=chip.error,
                        retired_at=retired_at,
                    )
                )

    def load_round_chips(self, workflow_id: str) -> list[RoundChip]:
        """
        Load a run's retired round-chip history, oldest first.

        :param workflow_id: Id of the run to load history for.
        :returns: Frozen chips ordered by step, round, then insertion.
        """
        with self._factory() as db:
            stmt = (
                select(WorkflowRoundChipRow)
                .where(WorkflowRoundChipRow.workflow_id == workflow_id)
                .order_by(
                    WorkflowRoundChipRow.step_name,
                    WorkflowRoundChipRow.round_index,
                    WorkflowRoundChipRow.id,
                )
            )
            return [
                RoundChip(
                    step=r.step_name,
                    round_index=r.round_index,
                    profile_id=r.profile_id,
                    label=r.label,
                    badge=r.badge,
                    session_id=r.session_id,
                    status=r.status,
                    error=r.error,
                    retired_at=r.retired_at,
                )
                for r in db.scalars(stmt)
            ]

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
                        verify_round=s.verify_round,
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
                        source=row.source,
                        task_ref=row.task_ref,
                        artifact_dir=row.artifact_dir or "",
                        boundary=row.boundary,
                        active_seconds=row.active_seconds,
                        wait_seconds=row.wait_seconds,
                        clock_state=row.clock_state,
                        clock_since=row.clock_since,
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
