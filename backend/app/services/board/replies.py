"""A reply on the ticket decides a gate (feature 046, User Story 3).

The comment poll (``comment_poll.py``) hands every new comment on a
request's ticket to :meth:`ReplyService.consider`. Each reply is then:

1. **filtered** (``reply_rules.is_reply``): the marker, and not one of
   kestrel's own comments; comments written before the request existed
   are left alone;
2. **claimed** in the comment store, so it is acted on at most once;
3. **matched** to the gate that was open when it was written;
4. **checked for entitlement** against the reporter and change owner, read
   fresh from the ticket;
5. **screened** by the quarantine boundary, as its own identity
   (``gate-reply:{external id}``): a held reply decides nothing until the
   operator releases it (:meth:`ReplyService.continue_released`);
6. **read** by the liaison: approve, reject (with its reason), or unclear;
7. **decided** through ``GatesService.resolve``, exactly as the UI does,
   credited to its author.

Every outcome is answered on the ticket, once (``reply:{external id}``).
Replies are handled one at a time, in the order they were written, so
the first that decides wins and the rest are told it was already decided.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.models_board import WorkCard, Workflow
from app.models_board_records import IntakeOutcome
from app.persistence.board_store import BoardStore
from app.persistence.board_time import now_utc
from app.persistence.comment_store import (
    HELD,
    CommentStore,
    InboundComment,
    Outcome,
)
from app.ports import Feedback, Person, Task, TaskSource
from app.services.board.announcements import replies as answers
from app.services.board.announcements.service import AnnouncementService
from app.services.board.gate_decision import needs_reason
from app.services.board.gates import GatesService
from app.services.board.liaison import LiaisonAsk
from app.services.board.quarantine import ExistingWorkflowIntake
from app.services.board.reply_decision import (
    Reading,
    ReadsReplies,
    ReplyDecider,
    Settled,
)
from app.services.board.reply_rules import (
    OpenedGate,
    decider_role,
    decision_words,
    entitled,
    faces_ticket,
    gate_for,
    is_reply,
    past_decision,
)
from app.services.task_sources import TaskSourceRegistry

_logger = logging.getLogger("kestrel.board.replies")

_GATE_OPENED = "gate.opened"
_WORKFLOW_CREATED = "workflow.created"
#: The category a held reply's security review carries.
GATE_REPLY = "gate-reply"


class _Screens(Protocol):
    async def intake_for_existing_workflow(
        self, intake: ExistingWorkflowIntake
    ) -> IntakeOutcome: ...


@dataclass(frozen=True)
class ReplyDeps:
    """What replies are read, decided and answered through.

    :param channels: The reply channel of each task source that has one
        (``{"jira-issue": "jira"}``); other sources are never read.
    :param on_decided: Told of every gate a reply decided, for what the UI
        path does next (the approved PRD and breakdown comments).
    """

    store: BoardStore
    gates: GatesService
    comments: CommentStore
    quarantine: _Screens
    liaison: ReadsReplies
    announcements: AnnouncementService
    task_sources: TaskSourceRegistry
    channels: Mapping[str, str]
    marker: str
    on_decided: Callable[[str, WorkCard, str], None] | None = None


@dataclass(frozen=True)
class _Reply:
    """One reply being handled, with what it is about."""

    workflow: Workflow
    feedback: Feedback
    task: Task
    channel: str

    @property
    def author(self) -> Person:
        return self.feedback.author


class ReplyService:
    """Reads, decides and answers replies on a request's ticket."""

    def __init__(self, deps: ReplyDeps) -> None:
        self._deps = deps
        self._lock = asyncio.Lock()
        self._decider = ReplyDecider(deps.gates, deps.liaison)

    def channel_of(self, workflow: Workflow) -> str | None:
        """The reply channel of *workflow*'s source, if it has one."""
        return self._deps.channels.get(workflow.source)

    def source_of(self, workflow: Workflow) -> TaskSource | None:
        """*workflow*'s task source, when it has a reply channel."""
        if self.channel_of(workflow) is None:
            return None
        return self._deps.task_sources.sources.get(workflow.source)

    async def consider(self, workflow: Workflow, feedback: Feedback) -> bool:
        """Act on *feedback* if it is a new reply.

        :returns: Whether it was taken on (``False`` for a comment that is
            not a reply, or was considered before).
        :raises Exception: When the ticket cannot be read; nothing is
            claimed then, so the next poll tries again.
        """
        async with self._lock:
            if not self._is_new_reply(workflow, feedback):
                return False
            reply = await self._reply(workflow, feedback)
            if reply is None or not self._deps.comments.claim(
                InboundComment(
                    feedback.external_id, workflow.id,
                    feedback.author.account_id,
                )
            ):
                return False
            await self._settle(reply, key=f"reply:{feedback.external_id}")
            return True

    async def continue_released(self, review_id: str) -> bool:
        """Act on the reply security review *review_id* held, now that it
        is released: fetched again by its id, screened again (which
        passes, its content released), and handled as new.

        :returns: Whether *review_id* held a reply at all.
        """
        held = self._deps.comments.held_for_review(review_id)
        if held is None:
            return False
        async with self._lock:
            found = await self._refetch(held)
            if found is None:
                return True
            reply = await self._reply(*found)
            if reply is not None and self._deps.comments.reclaim_held(
                held.external_id
            ):
                await self._settle(
                    reply, key=f"reply:{held.external_id}:released"
                )
        return True

    async def discarded(self, review_id: str) -> bool:
        """Tell the ticket that the reply security review *review_id*
        held was discarded, and not acted on.

        :returns: Whether *review_id* held a reply at all.
        """
        held = self._deps.comments.held_for_review(review_id)
        if held is None or held.state != HELD:
            return held is not None
        author = Person(held.author_account_id)
        await self._deps.announcements.post(
            held.workflow_id, "reply", f"reply:{held.external_id}:discarded",
            lambda ctx: answers.discarded(ctx, author),
        )
        return True

    def _is_new_reply(self, workflow: Workflow, feedback: Feedback) -> bool:
        if not is_reply(feedback, self._deps.marker):
            return False
        if self._deps.comments.get(feedback.external_id) is not None:
            return False
        return now_utc(feedback.created_at) >= self._created_at(workflow)

    def _created_at(self, workflow: Workflow) -> datetime:
        events = self._deps.store.list_events(workflow.id)
        created = [
            e.created_at for e in events
            if e.event_type == _WORKFLOW_CREATED and e.created_at
        ]
        return min(created) if created else datetime.min

    async def _reply(
        self, workflow: Workflow, feedback: Feedback
    ) -> _Reply | None:
        source = self.source_of(workflow)
        channel = self.channel_of(workflow)
        if source is None or channel is None:
            return None
        task = await source.get_task(workflow.task_ref)
        return _Reply(workflow, feedback, task, channel)

    async def _refetch(
        self, held: InboundComment
    ) -> tuple[Workflow, Feedback] | None:
        workflow = self._deps.store.get_workflow(held.workflow_id)
        source = self.source_of(workflow) if workflow is not None else None
        if source is None:
            return None
        page = await source.list_comments(workflow.task_ref, None)
        for feedback in page.comments:
            if feedback.external_id == held.external_id:
                return workflow, feedback
        _logger.warning("held reply %s is gone", held.external_id)
        return None

    async def _settle(self, reply: _Reply, *, key: str) -> None:
        settled = await self._handle(reply)
        self._deps.comments.record_outcome(
            reply.feedback.external_id, settled.outcome
        )
        if settled.decided is not None and self._deps.on_decided:
            card, decision = settled.decided
            self._deps.on_decided(reply.workflow.id, card, decision)
        await self._deps.announcements.post(
            reply.workflow.id, "reply", key, settled.build
        )

    async def _handle(self, reply: _Reply) -> Settled:
        gate = gate_for(
            self._gates(reply.workflow.id), now_utc(reply.feedback.created_at)
        )
        settled = self._without_reading(reply, gate)
        if settled is not None or gate is None:
            return settled  # gate is None always settles: no gate
        screened = await self._deps.quarantine.intake_for_existing_workflow(
            ExistingWorkflowIntake(
                identity_ref=reply.feedback.external_id,
                category=f"{GATE_REPLY}:{reply.feedback.external_id}",
                content=reply.feedback.body,
                workflow=reply.workflow,
            )
        )
        if not screened.released:
            return _held(reply, gate, screened.security_review_id)
        return await self._decider.decide(
            gate, self._reading(reply, gate), self._past
        )

    def _without_reading(
        self, reply: _Reply, gate: OpenedGate | None
    ) -> Settled | None:
        """The outcomes that need neither screening nor the liaison."""
        author = reply.author
        if gate is None:
            return Settled(
                Outcome("no_gate"),
                lambda ctx: answers.no_gate(ctx, author),
            )
        card_id = gate.card.id
        if not entitled(gate.card.kind, author, reply.task):
            role = decider_role(gate.card.kind)
            return Settled(
                Outcome("refused", gate_card_id=card_id),
                lambda ctx: answers.refused(ctx, author, role),
            )
        if gate.is_interview:
            return Settled(
                Outcome("interview_pointer", gate_card_id=card_id),
                lambda ctx: answers.interview_pointer(ctx, author),
            )
        if not gate.is_open:
            return self._past(gate, author)
        return None

    def _past(self, gate: OpenedGate, author: Person) -> Settled:
        """The gate was decided before this reply could decide it."""
        past = past_decision(
            gate, self._deps.store.list_events(gate.card.workflow_id)
        )
        return Settled(
            Outcome("already_decided", gate_card_id=gate.card.id),
            lambda ctx: answers.already_decided(
                ctx, author, past.decision, (past.display_name, past.channel)
            ),
        )

    def _reading(self, reply: _Reply, gate: OpenedGate) -> Reading:
        decision, asked = decision_words(gate)
        return Reading(
            ask=LiaisonAsk(
                decision=decision, asked=asked,
                reason_required=needs_reason(gate.record.requested_decision),
                reply=reply.feedback.body, marker=self._deps.marker,
            ),
            author=reply.author,
            channel=reply.channel,
            external_id=reply.feedback.external_id,
        )

    def _gates(self, workflow_id: str) -> list[OpenedGate]:
        """The gates put on *workflow_id*'s ticket, with when each
        opened."""
        store = self._deps.store
        opened = {
            e.card_id: e.created_at
            for e in store.list_events(workflow_id)
            if e.event_type == _GATE_OPENED and e.card_id and e.created_at
        }
        found = []
        for card in store.list_cards(workflow_id):
            record = self._deps.gates.get_gate(card.id)
            if card.id in opened and record and faces_ticket(card):
                found.append(OpenedGate(card, record, opened[card.id]))
        return found


def _held(
    reply: _Reply, gate: OpenedGate, review_id: str | None
) -> Settled:
    author = reply.author
    return Settled(
        Outcome(HELD, gate_card_id=gate.card.id, security_review_id=review_id),
        lambda ctx: answers.held(ctx, author),
    )
