"""Approved tasks wait to be handed to kestrel, and follow their work
items: handed over, done by a person, or given back (#99)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from app.documents import EMPTY_DOCUMENT, Document
from app.models_board import CardRelation, WorkCard
from app.persistence.board_artifact_store import BoardArtifactStore
from app.persistence.board_gate_store import BoardGateStore
from app.persistence.board_projection_store import BoardProjectionStore
from app.persistence.board_store import BoardStore
from app.ports import WorkItemState
from app.services.board.artifacts import ArtifactsService
from app.services.board.coordinator import CoordinatorService
from app.services.board.gates import GatesService
from app.services.board.handback import HandbackDeps
from app.services.board.handover_poll import (
    HandoverDeps,
    HandoverPollService,
)
from app.services.board.projections import (
    ProjectionRequest,
    ProjectionsService,
)
from app.services.board.service import BoardService
from app.services.board.task_heads import DONE_BY_PERSON
from app.services.task_sources import TaskSourceRegistry
from tests.board_test_support import board_session_factory
from tests.test_board_decomposition import _WORKFLOW

pytestmark = pytest.mark.integration

_HANDED = WorkItemState(handed_to_kestrel=True, done=False)
_DONE = WorkItemState(handed_to_kestrel=False, done=True)
_A_PERSONS = WorkItemState(handed_to_kestrel=False, done=False)


@dataclass
class _Source:
    """A task source that says who has each work item."""

    states: dict[str, WorkItemState] = field(default_factory=dict)
    down: bool = False
    asked: list[list[str]] = field(default_factory=list)
    comments: list[tuple[str, str]] = field(default_factory=list)

    def supports_handover(self) -> bool:
        return True

    async def work_item_states(
        self, refs: list[str]
    ) -> dict[str, WorkItemState]:
        if self.down:
            raise RuntimeError("Jira is down")
        self.asked.append(sorted(refs))
        return {ref: self.states[ref] for ref in refs if ref in self.states}

    async def post_comment(self, ref: str, body: Document) -> str:
        self.comments.append((ref, body.plain_text()))
        return f"comment-{len(self.comments)}"


@dataclass
class _Workspace:
    """Where kestrel's work on the request is."""

    def branch_name(self, workflow_id: str) -> str:
        return f"kestrel/board/{workflow_id}"

    async def last_commit(self, _workflow_id: str) -> str | None:
        return "abc1234 Add the table"


@dataclass
class _Rig:
    store: BoardStore
    source: _Source
    poll: HandoverPollService

    def state(self, card_id: str) -> str:
        return self.store.get_card(card_id).state

    def gates(self) -> list[WorkCard]:
        return [
            c for c in self.store.list_cards("wf-1")
            if c.kind == "policy_risk_gate"
        ]


def _rig(tmp_path: Path) -> _Rig:
    """Two approved tasks on a hand-over source, t2 after t1, each with
    its verification. Only t1's work item exists yet (DEV-1)."""
    factory = board_session_factory(tmp_path)
    store = BoardStore(factory)
    board = BoardService(store)
    artifacts = ArtifactsService(store, BoardArtifactStore(factory), board)
    projections = ProjectionsService(BoardProjectionStore(factory))
    store.create_workflow(replace(_WORKFLOW, source="jira-issue"))
    for card in (
        _card("h1", "implementation", "t1"),
        _card("v1", "verification", "t1", state="waiting_dependency"),
        _card("h2", "implementation", "t2"),
        _card("v2", "verification", "t2", state="waiting_dependency"),
    ):
        store.create_card(card)
    for card_id, depends_on in (("v1", "h1"), ("v2", "h2"), ("h2", "h1")):
        store.add_relation(
            CardRelation(card_id, depends_on), created_by_action="test"
        )
    _created(projections, "t1", "DEV-1")
    source = _Source()
    poll = HandoverPollService(HandoverDeps(
        handback=HandbackDeps(
            store=store, board=board, projections=projections,
            gates=GatesService(
                store, BoardGateStore(factory), board, artifacts
            ),
            workspace=_Workspace(),
        ),
        task_sources=TaskSourceRegistry({"jira-issue": source}, {}),
        coordinator=CoordinatorService(store, board),
        interval_seconds=0,
    ))
    return _Rig(store, source, poll)


def _card(
    card_id: str, kind: str, node: str, state: str = "waiting_handover"
) -> WorkCard:
    return WorkCard(
        id=card_id, workflow_id="wf-1", kind=kind, title=f"Task {node}",
        state=state, task_node_id=node,
    )


def _created(projections: ProjectionsService, node: str, ref: str) -> None:
    """Record that *node*'s work item exists as *ref*."""
    record = projections.plan(ProjectionRequest(
        "wf-1", "owner/repo#1", "work_item", f"work_item:wf-1:{node}",
        EMPTY_DOCUMENT,
    ))
    projections.complete(record.id, external_id=ref)


@pytest.mark.asyncio
async def test_a_handed_over_task_becomes_ready(tmp_path: Path) -> None:
    """Ensure an item assigned to kestrel moves its head card on, and the
    cascade makes it ready: it has no prerequisites."""
    rig = _rig(tmp_path)
    rig.source.states["DEV-1"] = _HANDED

    await rig.poll.poll_once()

    assert rig.state("h1") == "ready"
    assert rig.state("v1") == "waiting_dependency"


@pytest.mark.asyncio
async def test_an_open_prerequisite_keeps_a_handed_over_task_waiting(
    tmp_path: Path,
) -> None:
    """Ensure hand-over does not skip the dependency order."""
    rig = _rig(tmp_path)
    _created(rig.poll._deps.handback.projections, "t2", "DEV-2")
    rig.source.states["DEV-2"] = _HANDED

    await rig.poll.poll_once()

    assert rig.state("h2") == "waiting_dependency"
    assert rig.state("h1") == "waiting_handover"


@pytest.mark.asyncio
async def test_a_task_a_person_finished_is_done_and_frees_its_dependents(
    tmp_path: Path,
) -> None:
    """Ensure a done item finishes its task without running: head done,
    verification cancelled, and the task that waited on it starts."""
    rig = _rig(tmp_path)
    rig.store.set_card_state("h2", "waiting_dependency")
    rig.source.states["DEV-1"] = _DONE

    await rig.poll.poll_once()

    head = rig.store.get_card("h1")
    assert (head.state, head.wait_reason) == ("done", DONE_BY_PERSON)
    assert head.attempt_count == 0
    assert rig.state("v1") == "cancelled"
    assert rig.state("h2") == "ready"


@pytest.mark.asyncio
async def test_a_task_given_back_after_kestrel_took_it_stops_and_escalates(
    tmp_path: Path,
) -> None:
    """Ensure a claimed task whose item went back to a person gets no new
    work, one note on its item (across passes), and one escalation to
    the change owner."""
    rig = _rig(tmp_path)
    rig.store.set_card_state("h1", "claimed")
    rig.source.states["DEV-1"] = _A_PERSONS

    await rig.poll.poll_once()
    # The running turn finishes, and a fix of the same task follows it.
    rig.store.set_card_state("h1", "done")
    rig.store.create_card(_card("fix", "implementation", "t1", state="ready"))
    await rig.poll.poll_once()

    assert rig.state("v1") == "cancelled"
    assert rig.state("fix") == "cancelled"
    (ref, note), = rig.source.comments
    assert ref == "DEV-1"
    assert "kestrel/board/wf-1" in note
    assert "abc1234 Add the table" in note
    (gate,) = rig.gates()
    assert gate.source_card_id == "h1"
    assert gate.state == "awaiting_human"
    assert "DEV-1" in gate.title


@pytest.mark.asyncio
async def test_a_task_whose_item_is_not_created_yet_keeps_waiting(
    tmp_path: Path,
) -> None:
    """Ensure a task with no work item yet is neither read nor moved."""
    rig = _rig(tmp_path)
    rig.source.states["DEV-1"] = _A_PERSONS

    await rig.poll.poll_once()

    assert rig.source.asked == [["DEV-1"]]
    assert rig.state("h2") == "waiting_handover"


@pytest.mark.asyncio
async def test_a_source_that_cannot_be_read_changes_nothing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Ensure a source error is logged as a warning and tried again on
    the next pass, without raising or moving anything."""
    rig = _rig(tmp_path)
    rig.source.states["DEV-1"] = _HANDED
    rig.source.down = True

    with caplog.at_level(logging.WARNING, "kestrel.board.handover_poll"):
        await rig.poll.poll_once()

    assert rig.state("h1") == "waiting_handover"
    (record,) = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert record.workflow_id == "wf-1"

    rig.source.down = False
    await rig.poll.poll_once()
    assert rig.state("h1") == "ready"


@pytest.mark.asyncio
async def test_every_decision_is_in_the_decision_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Ensure a hand-over decision is logged at INFO with its request,
    task, work item and decision as attributes."""
    rig = _rig(tmp_path)
    rig.source.states["DEV-1"] = _HANDED

    with caplog.at_level(logging.INFO, "kestrel.board.decisions"):
        await rig.poll.poll_once()

    (record,) = [
        r for r in caplog.records if r.name == "kestrel.board.decisions"
    ]
    assert record.levelno == logging.INFO
    assert (record.workflow_id, record.task_node_id, record.work_item) == (
        "wf-1", "t1", "DEV-1",
    )
    assert record.decision == "handed_over"


@pytest.mark.asyncio
async def test_a_finished_request_is_not_read(tmp_path: Path) -> None:
    """Ensure nothing is asked of the source once every card is over."""
    rig = _rig(tmp_path)
    for card in rig.store.list_cards("wf-1"):
        rig.store.set_card_state(card.id, "cancelled")

    await rig.poll.poll_once()

    assert rig.source.asked == []
