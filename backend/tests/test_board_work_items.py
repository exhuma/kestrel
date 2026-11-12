"""An approved plan's tasks become work items on the task source, once
each, with their order as links and one comment listing them (#64)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app.documents import Document, Text, document, paragraph
from app.models_board import CardRelation, WorkCard
from app.persistence.board_artifact_store import BoardArtifactStore
from app.persistence.board_projection_store import BoardProjectionStore
from app.persistence.board_store import BoardStore
from app.services.board.artifacts import ArtifactDraft, ArtifactsService
from app.services.board.materialise import (
    CLASSIFICATION_LOGICAL_NAME,
    TASK_SPEC_LOGICAL_NAME,
)
from app.services.board.projection_retry import ProjectionRetryService
from app.services.board.projections import ProjectionsService
from app.services.board.service import BoardService
from app.services.board.work_items import WorkItemDeps, WorkItemPublisher
from app.services.task_sources import TaskSourceRegistry
from tests.announcement_support import announcing
from tests.board_test_support import board_session_factory
from tests.test_board_decomposition import _WORKFLOW

pytestmark = pytest.mark.integration


@dataclass
class _Source:
    """A recording task source; ``failing`` titles fail to create."""

    failing: set[str] = field(default_factory=set)
    created: list[tuple[str, str, str]] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)
    handover: bool = False

    def supports_handover(self) -> bool:
        return self.handover

    async def create_subtask(
        self, parent_ref: str, title: str, _body: Document, key: str = ""
    ) -> str:
        if title in self.failing:
            raise RuntimeError("Jira is down")
        self.created.append((parent_ref, title, key))
        return f"DEV-{len(self.created)}"

    async def link_subtasks(self, blocking: str, blocked: str) -> None:
        self.links.append((blocking, blocked))

    async def post_comment(self, _ref: str, body: Document) -> str:
        self.comments.append(body.plain_text())
        return "comment"


@dataclass
class _Rig:
    store: BoardStore
    projections: ProjectionsService
    publisher: WorkItemPublisher
    source: _Source

    async def publish(self) -> None:
        await self.publisher.publish("wf-1")


def _rig(tmp_path: Path, *, handover: bool = False) -> _Rig:
    factory = board_session_factory(tmp_path)
    store = BoardStore(factory)
    board = BoardService(store)
    artifacts = ArtifactsService(store, BoardArtifactStore(factory), board)
    projections = ProjectionsService(BoardProjectionStore(factory))
    source = _Source(handover=handover)
    store.create_workflow(_WORKFLOW)
    publisher = WorkItemPublisher(WorkItemDeps(
        store=store, artifacts=artifacts, projections=projections,
        task_sources=TaskSourceRegistry({"github-issue": source}, {}),
        announcements=announcing(
            store, projections, {"github-issue": source}
        ),
        interval_seconds=0,
    ))
    _plan(store, artifacts)
    return _Rig(store, projections, publisher, source)


def _card(card_id: str, kind: str, node: str, **extra: str) -> WorkCard:
    return WorkCard(
        id=card_id, workflow_id="wf-1", kind=kind, title=extra.pop(
            "title", card_id
        ), state=extra.pop("state", "ready"), task_node_id=node, **extra,
    )


def _plan(store: BoardStore, artifacts: ArtifactsService) -> None:
    """Two approved tasks (the one planned for a person after the coding
    one), the coding task's verification, and a later round of requested
    changes."""
    for card in (
        _card("impl", "implementation", "t1", title="Add the table"),
        _card("check", "verification", "t1", title="Verify: Add the table"),
        _card("manual", "implementation", "t2", title="Tell support"),
        _card("later", "implementation", "changes-1", title="Fix a typo"),
    ):
        store.create_card(card)
    store.add_relation(CardRelation("check", "impl"), created_by_action="t")
    store.add_relation(CardRelation("manual", "impl"), created_by_action="t")
    artifacts.store_document(
        "impl", TASK_SPEC_LOGICAL_NAME, 1,
        document(paragraph(Text("Create the table."))),
    )
    for card_id, planned in (("impl", "coding"), ("manual", "manual")):
        artifacts.store_reference_artifact(ArtifactDraft(
            producer_card_id=card_id,
            logical_name=CLASSIFICATION_LOGICAL_NAME, revision=1,
            content=planned, trust="operator_approved",
        ))


@pytest.mark.asyncio
async def test_each_approved_task_gets_one_item(tmp_path: Path) -> None:
    """Ensure one item per task, the order as a link, and one comment
    listing each task with its item; later rounds get none."""
    rig = _rig(tmp_path)

    await rig.publish()

    assert [(t, k) for _p, t, k in rig.source.created] == [
        ("Add the table", "kestrel-wf-1-t1"),
        ("Tell support", "kestrel-wf-1-t2"),
    ]
    assert rig.source.links == [("DEV-1", "DEV-2")]
    (comment,) = rig.source.comments
    assert "DEV-1: Add the table (coding)" in comment
    assert "DEV-2: Tell support (for a person)" in comment
    assert "works the tasks inside this request" in comment
    assert rig.projections.external_id("work_item:wf-1:t1") == "DEV-1"


@pytest.mark.asyncio
async def test_on_a_hand_over_source_the_comment_says_how_to_hand_over(
    tmp_path: Path,
) -> None:
    """Ensure the breakdown says a task starts once its item is assigned
    to kestrel, where the source supports hand-over (#99)."""
    rig = _rig(tmp_path, handover=True)

    await rig.publish()

    (comment,) = rig.source.comments
    assert "once its item is assigned to kestrel" in comment


@pytest.mark.asyncio
async def test_publishing_again_creates_nothing(tmp_path: Path) -> None:
    """Ensure a second pass (the loop, a restart) repeats no step."""
    rig = _rig(tmp_path)
    await rig.publish()

    await rig.publish()

    assert [t for _p, t, _k in rig.source.created] == [
        "Add the table", "Tell support",
    ]
    assert rig.source.links == [("DEV-1", "DEV-2")]
    assert len(rig.source.comments) == 1


@pytest.mark.asyncio
async def test_a_failed_item_is_created_on_a_later_pass(tmp_path: Path) -> None:
    """Ensure nothing is linked or announced until every item exists, and
    a failed item is tried again."""
    rig = _rig(tmp_path)
    rig.source.failing = {"Tell support"}

    await rig.publish()

    assert [t for _p, t, _k in rig.source.created] == ["Add the table"]
    assert rig.source.links == []
    assert rig.source.comments == []

    rig.source.failing = set()
    await rig.publish()

    assert [t for _p, t, _k in rig.source.created] == [
        "Add the table", "Tell support",
    ]
    assert rig.source.links == [("DEV-1", "DEV-2")]
    assert len(rig.source.comments) == 1


@pytest.mark.asyncio
async def test_the_comment_retry_loop_leaves_work_items_alone(
    tmp_path: Path,
) -> None:
    """Ensure a failed work item is never posted as a comment."""
    rig = _rig(tmp_path)
    rig.source.failing = {"Tell support"}
    await rig.publish()
    retry = ProjectionRetryService(
        rig.projections, rig.store,
        TaskSourceRegistry({"github-issue": rig.source}, {}),
        interval_seconds=0,
    )

    assert await retry.poll_once() == 0
    assert rig.source.comments == []
