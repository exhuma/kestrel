"""When kestrel says what on the ticket (feature 046, User Story 2).

``BoardService`` calls :meth:`AnnouncementService.schedule` after every
mutation, the way it wakes the coordinator. A pass then looks at the
request's history and says, once, whatever it has not yet said: a gate
that opened, the request ending badly. Everything goes through the
projection ledger, whose idempotency keys make every announcement
at-most-once across passes and restarts, and whose stored payload lets a
failed post be retried (``projection_retry.py``).

kestrel never changes the status of an ingested ticket (constitution,
access model, fourth constraint): nothing here, or anywhere it calls,
touches ``TaskSource.transition``.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass

from app.documents import Document
from app.models_board import CardState, WorkCard
from app.persistence.board_store import BoardStore
from app.ports import TaskSource
from app.services.board.announcements import status
from app.services.board.announcements.common import (
    DEFAULT_MARKER,
    Context,
    People,
    named,
)
from app.services.board.announcements.content import GateContent, Plan
from app.services.board.phases import CANCELLED, FAILED, outcome_of
from app.services.board.projections import (
    ProjectionRequest,
    ProjectionsService,
)
from app.services.board.write_back import post_projection
from app.services.task_sources import TaskSourceRegistry

_logger = logging.getLogger("kestrel.board.announcements")

#: The event ``GatesService.create_gate`` records when a gate opens.
GATE_OPENED = "gate.opened"

Build = Callable[[Context], Document]


@dataclass(frozen=True)
class AnnouncementDeps:
    """What the service reads and posts through, bundled for the
    argument limit."""

    store: BoardStore
    content: GateContent
    projections: ProjectionsService
    task_sources: TaskSourceRegistry
    base_url: str = ""
    #: What a reply on the ticket carries (``Settings.feedback_marker``).
    marker: str = DEFAULT_MARKER


class AnnouncementService:
    """Posts what the people on a ticket need to know, once each."""

    def __init__(self, deps: AnnouncementDeps) -> None:
        self._deps = deps
        self._lock = asyncio.Lock()
        self._running: set[asyncio.Task[None]] = set()

    def schedule(self, workflow_id: str) -> None:
        """Look at *workflow_id* in the background (the board's mutation
        hook). Without a running event loop there is nothing to do."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self.announce(workflow_id))
        self._running.add(task)
        task.add_done_callback(self._running.discard)

    async def announce(self, workflow_id: str) -> None:
        """One pass: say what has happened on *workflow_id* and has not
        been said yet. Never raises: an announcement that cannot be
        made must not fail the board change that prompted it."""
        try:
            await self._announce(workflow_id)
        except Exception:
            _logger.exception(
                "workflow %s: announcement pass failed", workflow_id
            )

    async def delivered(
        self, workflow_id: str, card_id: str, location: str
    ) -> None:
        """Tell the change owner the work is delivered."""
        await self.post(
            workflow_id, "delivery", f"delivery:{card_id}",
            lambda ctx: status.delivered(ctx, location),
        )

    async def escalated(
        self, workflow_id: str, key: str, summary: str
    ) -> None:
        """Say something needs the coordinator's attention."""
        await self.post(
            workflow_id, "escalation", key,
            lambda ctx: status.escalation(ctx, summary),
        )

    async def gate_decided(
        self, workflow_id: str, card: WorkCard, decision: str
    ) -> None:
        """Say a gate was decided in kestrel."""
        await self.post(
            workflow_id, "gate", f"gate:{card.id}",
            lambda ctx: status.gate_decided(ctx, decision, card.title),
        )

    async def ci_changed(
        self, workflow_id: str, key: str, detail: str | None
    ) -> None:
        """Say the change request's required checks failed (*detail*
        says how) or, with no detail, now pass."""
        await self.post(
            workflow_id, "status", key,
            lambda ctx: (
                status.ci_repaired(ctx) if detail is None
                else status.ci_failed(ctx, detail)
            ),
        )

    async def post(
        self, workflow_id: str, kind: str, key: str, build: Build
    ) -> None:
        """Post one announcement unless the ledger already has it.

        The ticket is read for who is on it only when there is something
        to say, and under a lock, so two passes never both post the same
        key. Never raises: a comment that cannot be made must not fail
        what prompted it.
        """
        async with self._lock:
            try:
                await self._post(workflow_id, kind, key, build)
            except Exception:
                _logger.exception(
                    "workflow %s: %s could not be posted", workflow_id, key
                )

    async def _post(
        self, workflow_id: str, kind: str, key: str, build: Build
    ) -> None:
        deps = self._deps
        if deps.projections.recorded(key):
            return
        workflow = deps.store.get_workflow(workflow_id)
        source = (
            deps.task_sources.sources.get(workflow.source)
            if workflow is not None else None
        )
        if source is None:
            _logger.warning(
                "workflow %s: no task source; %s not posted", workflow_id, key
            )
            return
        ctx = await self._context(workflow_id, workflow.task_ref, source)
        await post_projection(
            ProjectionRequest(
                workflow_id=workflow_id, task_ref=workflow.task_ref,
                kind=kind, idempotency_key=key, payload=build(ctx),
            ),
            source, deps.projections,
        )

    async def _announce(self, workflow_id: str) -> None:
        store = self._deps.store
        opened = {
            event.card_id for event in store.list_events(workflow_id)
            if event.event_type == GATE_OPENED and event.card_id
        }
        cards = store.list_cards(workflow_id)
        plans: dict[str, Plan] = {}
        for card in cards:
            if card.id in opened and card.state == CardState.AWAITING_HUMAN:
                plan = self._deps.content.plan(card)
                if plan is not None:
                    plans.setdefault(plan.key, plan)
        for plan in plans.values():
            await self.post(workflow_id, "gate_opened", plan.key, plan.build)
        await self._announce_outcome(workflow_id, cards)

    async def _announce_outcome(
        self, workflow_id: str, cards: list[WorkCard]
    ) -> None:
        """Tell the change owner when the request has ended badly.

        A cancelled request is announced only when a decision was
        rejected: a board between two steps (work done, the next card not
        yet created) also reads as "stopped", and a comment cannot be
        taken back.
        """
        outcome = outcome_of(cards)
        rejected = _rejected_gates(cards)
        if outcome == CANCELLED and not rejected:
            return
        if outcome not in (FAILED, CANCELLED):
            return
        reason = _reason(outcome, cards, rejected)
        await self.post(
            workflow_id, "status", f"status:outcome:{workflow_id}",
            lambda ctx: status.ended(ctx, outcome, reason),
        )

    async def _context(
        self, workflow_id: str, task_ref: str, source: TaskSource
    ) -> Context:
        deps = self._deps
        try:
            task = await source.get_task(task_ref)
        except Exception:
            _logger.warning(
                "workflow %s: could not read the ticket for its people",
                workflow_id, exc_info=True,
            )
            people = People(known=False)
        else:
            people = People(named(task.reporter), named(task.change_owner))
        return Context(workflow_id, people, deps.base_url, deps.marker)


def _rejected_gates(cards: list[WorkCard]) -> list[str]:
    """The titles of the decisions that were rejected."""
    return [
        c.title for c in cards
        if c.kind.endswith("_gate") and c.state == CardState.CANCELLED.value
    ]


def _reason(outcome: str, cards: list[WorkCard], rejected: list[str]) -> str:
    if outcome == FAILED:
        failed = [
            c.title for c in cards if c.state == CardState.FAILED.value
        ]
        return "What failed: " + "; ".join(failed) + "."
    return "A decision was rejected: " + "; ".join(rejected) + "."
