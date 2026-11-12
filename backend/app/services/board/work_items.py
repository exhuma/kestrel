"""An approved plan's tasks as work items on the task source (#64).

Once CAB-2 approves a breakdown, every approved task becomes a record a
person can work from without kestrel: a Jira sub-task of the request, or
an issue in the source's ``work_items_project`` linked to it (``jira.py``).
Prerequisites become "blocks" links, and one comment lists each task with
its item.

Every step is a row in the projection ledger, so a step is done once:
``work_item:<workflow>:<task>`` keeps the item's key (the card to item
mapping later status updates build on), and ``work_item_link:…`` each link.
A failed step is tried again by :meth:`WorkItemPublisher.run_forever`, which
also picks up a plan whose publishing never started (a restart right after
the approval). Each item carries a label made from its ledger key, so an
item created just before a crash is found again instead of doubled.
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable
from dataclasses import dataclass

from app.documents import (
    EMPTY_DOCUMENT,
    Document,
    ListItem,
    OrderedList,
    Text,
    document,
    paragraph,
)
from app.models_board import (
    CardState,
    RelationKind,
    WorkCard,
    Workflow,
)
from app.models_board_records import ExternalProjectionRecord
from app.persistence.board_store import BoardStore
from app.persistence.board_time import now_utc
from app.ports import TaskSource
from app.services.board.announcements.common import finish
from app.services.board.announcements.service import AnnouncementService
from app.services.board.artifacts import ArtifactsService
from app.services.board.candidate import MANUAL
from app.services.board.materialise import (
    CLASSIFICATION_LOGICAL_NAME,
    TASK_SPEC_LOGICAL_NAME,
)
from app.services.board.projection_retry import MAX_ATTEMPTS, due_at
from app.services.board.projections import (
    ProjectionRequest,
    ProjectionsService,
)
from app.services.board.task_heads import task_heads
from app.services.task_sources import TaskSourceRegistry

_log = logging.getLogger("kestrel.board.work_items")

_AT_ONCE = (
    "kestrel works the tasks inside this request and delivers them as one "
    "change."
)
_HANDOVER = (
    "kestrel starts a task once its item is assigned to kestrel, waits "
    "for the other items to be done, and delivers its own work as one "
    "change."
)
_UNSAFE_LABEL = re.compile(r"[^A-Za-z0-9_-]+")


@dataclass(frozen=True)
class WorkItemDeps:
    """What publishing reads and writes through, bundled for the
    argument limit."""

    store: BoardStore
    artifacts: ArtifactsService
    projections: ProjectionsService
    task_sources: TaskSourceRegistry
    announcements: AnnouncementService
    #: The retry loop's interval; a failed step waits longer each time.
    interval_seconds: float


class WorkItemPublisher:
    """Creates a request's work items, links and breakdown comment."""

    def __init__(self, deps: WorkItemDeps) -> None:
        self._deps = deps
        self._lock = asyncio.Lock()

    def schedule(self, workflow_id: str) -> None:
        """Publish *workflow_id*'s work items in the background."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.publish(workflow_id))

    async def run_forever(self) -> None:
        """Publish whatever is still missing, every interval: failed
        steps, and plans whose publishing never started."""
        while True:
            for workflow in self._deps.store.list_workflows():
                await self.publish(workflow.id)
            await asyncio.sleep(self._deps.interval_seconds)

    async def publish(self, workflow_id: str) -> None:
        """One pass. Never raises: a source that is down is tried again
        on a later pass."""
        async with self._lock:
            try:
                await self._publish(workflow_id)
            except Exception:
                _log.exception(
                    "workflow %s: work items could not be published",
                    workflow_id,
                )

    async def _publish(self, workflow_id: str) -> None:
        store = self._deps.store
        workflow = store.get_workflow(workflow_id)
        source = (
            self._deps.task_sources.sources.get(workflow.source)
            if workflow is not None else None
        )
        if workflow is None or source is None:
            return
        heads = _heads(store.list_cards(workflow_id))
        if not heads:
            return
        refs = {}
        for card in heads:
            ref = await self._item(workflow, source, card)
            if ref is not None:
                refs[card.id] = ref
        if len(refs) < len(heads):
            return  # the rest come on a later pass
        for blocking, blocked in _order(heads, store, workflow_id):
            await self._link(workflow, source, refs, (blocking, blocked))
        await self._announce(workflow, source, heads, refs)

    async def _item(
        self, workflow: Workflow, source: TaskSource, card: WorkCard
    ) -> str | None:
        """The task's item, created now if it has to be."""
        key = work_item_key(workflow.id, card.task_node_id or "")
        body = (
            self._deps.artifacts.latest_document_for_card(
                card.id, TASK_SPEC_LOGICAL_NAME
            )
            or document(paragraph(Text(card.title)))
        )
        record = self._take(workflow, "work_item", key, body)
        if record is None:
            return self._deps.projections.external_id(key)
        return await self._attempt(
            record,
            source.create_subtask(
                workflow.task_ref, card.title, body, key=_label(key)
            ),
        )

    async def _link(
        self,
        workflow: Workflow,
        source: TaskSource,
        refs: dict[str, str],
        pair: tuple[WorkCard, WorkCard],
    ) -> None:
        blocking, blocked = pair
        key = (
            f"work_item_link:{workflow.id}:{blocking.task_node_id}:"
            f"{blocked.task_node_id}"
        )
        record = self._take(workflow, "work_item_link", key, EMPTY_DOCUMENT)
        if record is not None:
            await self._attempt(
                record,
                source.link_subtasks(refs[blocking.id], refs[blocked.id]),
            )

    def _take(
        self, workflow: Workflow, kind: str, key: str, payload: Document
    ) -> ExternalProjectionRecord | None:
        """The ledger row to attempt now, or ``None`` when the step is
        done or its failure is not due for another try yet."""
        projections = self._deps.projections
        record = projections.plan(ProjectionRequest(
            workflow.id, workflow.task_ref, kind, key, payload
        ))
        if record.state == "pending":
            return record  # new, or cut short by a restart
        if record.state != "retryable_failure":
            return None
        due = due_at(record, self._deps.interval_seconds) <= now_utc(None)
        if record.attempts >= MAX_ATTEMPTS or not due:
            return None
        return record if projections.begin_retry(record.id) else None

    async def _attempt(
        self, record: ExternalProjectionRecord, call: Awaitable[object]
    ) -> str | None:
        """Run one step's source call and record how it went."""
        try:
            result = await call
        except Exception as exc:
            self._deps.projections.fail(record.id, str(exc))
            _log.warning(
                "workflow %s: %s failed: %s",
                record.workflow_id, record.idempotency_key, exc,
            )
            return None
        ref = result if isinstance(result, str) else ""
        self._deps.projections.complete(record.id, external_id=ref or None)
        _log.info(
            "workflow %s: %s done (%s)",
            record.workflow_id, record.idempotency_key, ref or "linked",
        )
        return ref

    async def _announce(
        self,
        workflow: Workflow,
        source: TaskSource,
        heads: list[WorkCard],
        refs: dict[str, str],
    ) -> None:
        nodes = ",".join(sorted(str(c.task_node_id) for c in heads))
        listing = breakdown(heads, Listing(
            refs, {card.id: self._who(card) for card in heads},
            handover=source.supports_handover(),
        ))
        await self._deps.announcements.post(
            workflow.id, "approved_artifact",
            f"approved_artifact:work_items:{workflow.id}:{nodes}",
            lambda ctx: finish(ctx, listing.blocks),
        )

    def _who(self, card: WorkCard) -> str:
        """Who the plan expects to do *card*'s task: information only;
        the work item's assignee decides (#99)."""
        planned = self._deps.artifacts.latest_content_for_card(
            card.id, CLASSIFICATION_LOGICAL_NAME
        )
        return "for a person" if planned == MANUAL else "coding"


@dataclass(frozen=True)
class Listing:
    """What the breakdown comment lists, by head card id.

    :param refs: Each task's work item.
    :param who: Who the plan expects to do each task.
    :param handover: Whether tasks wait to be handed to kestrel (#99).
    """

    refs: dict[str, str]
    who: dict[str, str]
    handover: bool = False


def work_item_key(workflow_id: str, task_node_id: str) -> str:
    """The ledger key of a task's work item; its row's ``external_id``
    is the item's ref once it is created."""
    return f"work_item:{workflow_id}:{task_node_id}"


def breakdown(heads: list[WorkCard], listing: Listing) -> Document:
    """The comment listing each approved task with its work item, and
    who the plan expects to do it."""
    intro = paragraph(Text(
        "Approved task breakdown (CAB-2). Each task has its own work item; "
        f"{_HANDOVER if listing.handover else _AT_ONCE}"
    ))
    items = tuple(
        ListItem((paragraph(Text(
            f"{listing.refs.get(card.id, '?')}: {card.title} "
            f"({listing.who.get(card.id, 'coding')})"
        )),))
        for card in heads
    )
    return document(intro, OrderedList(1, items))


def _heads(cards: list[WorkCard]) -> list[WorkCard]:
    """One card per approved task that is still part of the plan."""
    return [
        card for card in task_heads(cards)
        if card.state != CardState.CANCELLED.value
    ]


def _order(
    heads: list[WorkCard], store: BoardStore, workflow_id: str
) -> list[tuple[WorkCard, WorkCard]]:
    """``(blocking, blocked)`` for each prerequisite between two tasks."""
    by_id = {card.id: card for card in heads}
    return [
        (by_id[r.depends_on_card_id], by_id[r.card_id])
        for r in store.list_relations(workflow_id)
        if r.kind == RelationKind.DEPENDENCY
        and r.card_id in by_id and r.depends_on_card_id in by_id
    ]


def _label(key: str) -> str:
    """*key* as a Jira label: no spaces or colons."""
    return "kestrel-" + _UNSAFE_LABEL.sub("-", key.split(":", 1)[1])
