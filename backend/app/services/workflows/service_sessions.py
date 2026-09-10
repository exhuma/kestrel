"""Session and liveness methods mixed into ``WorkflowService``."""

from __future__ import annotations

import asyncio
from typing import Callable

from app.backends.base import Backend, TurnRequest, TurnResult
from app.models_workflow import (
    RoundChip,
    StepSession,
    WorkflowRun,
    WorkflowStep,
)
from app.policy import BackendPolicy
from app.services.workflows import liveness as wf_liveness
from app.services.workflows import sessions as sessions_mod
from app.services.workflows.shared import _now_utc
from app.storage.registry import SessionRegistry
from app.storage.workflow_registry import WorkflowRegistry


class WorkflowSessionService:
    """Provide workflow session tracking operations to the service host."""

    workflows: WorkflowRegistry
    sessions: SessionRegistry
    backends: BackendPolicy

    def _save(self, run: WorkflowRun) -> None:
        """Persist a run through the concrete workflow service."""
        raise NotImplementedError

    def get(self, workflow_id: str) -> WorkflowRun:
        """Retrieve a run through the concrete workflow service."""
        raise NotImplementedError

    def _retire_sessions(self, run: WorkflowRun, step: WorkflowStep) -> None:
        """Freeze live chips into durable history and clear the active set."""
        self.workflows.save_round_chips(
            run.id, step.name, step.active_sessions, _now_utc()
        )
        step.active_sessions = []

    def _show_sessions(
        self, run: WorkflowRun, slots: list[StepSession]
    ) -> None:
        """Publish refine sessions after retiring the previously active set."""
        step = run.steps[1]
        self._retire_sessions(run, step)
        step.active_sessions = slots
        self._save(run)

    def round_history(self, workflow_id: str) -> list[RoundChip]:
        """Return retired session chips for a run, oldest first."""
        return self.workflows.load_round_chips(workflow_id)

    def _watch_activity(
        self, run: WorkflowRun, session_id: str, slot: StepSession
    ) -> asyncio.Task:
        """Create activity tracking for one active session chip."""
        return sessions_mod.watch_activity(
            self.sessions, self._save, run, session_id, slot
        )

    async def _run_turn_tracked(
        self,
        run: WorkflowRun,
        backend: Backend,
        req: TurnRequest,
        slot: StepSession,
        bind: Callable[[str], None],
    ) -> TurnResult:
        """Run a backend turn while tracking activity on its session chip."""
        tracker = sessions_mod.ChipTracker(slot, bind, self._watch_activity)
        return await sessions_mod.run_turn_tracked(run, backend, req, tracker)

    async def poll_active_step(self, workflow_id: str) -> None:
        """Probe the live chips on a run's active step."""
        run = self.get(workflow_id)
        await wf_liveness.poll_active_step(
            self.backends.backend_for, self.sessions, self._save, run
        )
