"""Periodic CI-status polling and bounded repair dispatch (feature 026,
T052).

The board's only other background sweep, ``recovery.py``, watches its
own store for expired claim leases; this is the first "poll an external
provider on a timer" loop in the new architecture — required-CI status
is a property of an open change request, not of anything the board
mutates itself, so there is nothing for the usual mutation-driven
``_trigger_scheduling`` to react to.

Bounded exactly like the old (deleted) fixed driver's own
``workflows/ci.py``: a failing required check creates one ``coder``-
eligible repair card (reusing ``CardKind.IMPLEMENTATION``, the same kind
T051's verifier-triggered remediation uses — no new card kind needed),
up to ``max_ci_repair_iterations`` per delivery; past that, one
``coordinator_review`` escalation (fail closed, matching T051/T068's
own escalation pattern) and no further polling for that workflow.
"""
from __future__ import annotations

import asyncio
import logging

from app.config import Settings
from app.models_board import CardKind, Workflow
from app.persistence.board_store import BoardStore
from app.services.board.announcements.service import AnnouncementService
from app.services.board.coordinator import CoordinatorService, CreateCardAction
from app.services.task_sources import TaskSourceRegistry

_logger = logging.getLogger("kestrel.board.ci_poll")


class CiPollService:
    """Polls each delivered workflow's required CI checks; repairs or
    escalates a failure."""

    def __init__(
        self,
        store: BoardStore,
        coordinator: CoordinatorService,
        task_sources: TaskSourceRegistry,
        settings: Settings,
        *,
        announcements: AnnouncementService | None = None,
    ) -> None:
        self._store = store
        self._coordinator = coordinator
        self._task_sources = task_sources
        self._settings = settings
        self._announcements = announcements

    async def run_forever(self) -> None:
        """Poll every eligible workflow until cancelled."""
        while True:
            await self.poll_once()
            await asyncio.sleep(self._settings.board_ci_poll_interval_seconds)

    async def poll_once(self) -> None:
        """Check every currently-eligible workflow's required CI once."""
        for workflow in self._store.list_workflows():
            if self._eligible(workflow):
                await self._poll_one(workflow)

    def _eligible(self, workflow: Workflow) -> bool:
        if workflow.change_request_number is None:
            return False
        if workflow.ci_status == "passed":
            return False
        if not self._required_names(workflow):
            return False
        # <= , not <: a workflow already at the repair limit (every prior
        # round used on a repair, none yet escalated) still needs exactly
        # one more poll — the one that discovers the still-failing check
        # and escalates instead of repairing again. record_ci_status then
        # pushes ci_repair_round past the limit, which is what actually
        # stops further polling.
        limit = self._settings.max_ci_repair_iterations
        return workflow.ci_repair_round <= limit

    def _required_names(self, workflow: Workflow) -> list[str]:
        return self._settings.required_ci_statuses_for(
            workflow.source, workflow.repo
        )

    async def _poll_one(self, workflow: Workflow) -> None:
        code_host = self._task_sources.code_hosts.get(workflow.source)
        if code_host is None:
            return
        try:
            statuses = await code_host.required_ci_statuses(
                workflow.repo, workflow.change_request_number,
                self._required_names(workflow),
            )
        except Exception:  # noqa: BLE001 — one bad check must not stop others
            _logger.exception(
                "workflow %s: required-CI check failed", workflow.id
            )
            return
        if any(status.state == "pending" for status in statuses):
            self._store.record_ci_status(workflow.id, "pending")
            return
        if all(status.state == "passed" for status in statuses):
            self._store.record_ci_status(workflow.id, "passed")
            if workflow.ci_repair_round > 0:  # it had failed before
                await self._say(workflow, workflow.ci_repair_round, None)
            return
        round_number = self._store.record_ci_status(workflow.id, "failed")
        detail = "; ".join(
            f"{status.name}: {status.detail or 'no detail'}"
            for status in statuses
            if status.state == "failed"
        )
        await self._say(workflow, round_number, detail)
        if round_number > self._settings.max_ci_repair_iterations:
            self._escalate(workflow, detail)
        else:
            self._repair(workflow, detail)

    async def _say(
        self, workflow: Workflow, round_number: int, detail: str | None
    ) -> None:
        """Tell the ticket the required checks failed (*detail*) or are
        repaired (no detail), once per round of a delivery."""
        if self._announcements is None:
            return
        deliveries = [
            c for c in self._store.list_cards(workflow.id)
            if c.kind == CardKind.DELIVERY.value
        ]
        delivery = deliveries[-1].id if deliveries else workflow.id
        outcome = "repaired" if detail is None else "failed"
        await self._announcements.ci_changed(
            workflow.id, f"status:ci:{delivery}:{round_number}:{outcome}",
            detail,
        )

    def _repair(self, workflow: Workflow, detail: str) -> None:
        trigger = f"ci_repair:{workflow.id}:{workflow.ci_repair_round}"
        self._coordinator.apply_actions(
            workflow.id, trigger,
            [
                CreateCardAction(
                    kind=CardKind.IMPLEMENTATION.value,
                    title=f"Repair required CI: {detail}",
                    eligible_roles=("coder",),
                    workspace_permission="write",
                )
            ],
        )

    def _escalate(self, workflow: Workflow, detail: str) -> None:
        trigger = f"ci_repair:{workflow.id}:escalate"
        self._coordinator.apply_actions(
            workflow.id, trigger,
            [
                CreateCardAction(
                    kind=CardKind.COORDINATOR_REVIEW.value,
                    title=f"CI repair budget exhausted: {detail}",
                )
            ],
        )
