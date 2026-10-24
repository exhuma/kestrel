"""A board stack with a recording ticket, for announcement tests
(feature 046, User Story 2)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from app.documents import Document, Marker, Text, document, paragraph
from app.models_board import CardKind, CardRelation, WorkCard, Workflow
from app.persistence.board_artifact_content_store import (
    BoardArtifactContentStore,
)
from app.persistence.board_artifact_store import BoardArtifactStore
from app.persistence.board_gate_store import BoardGateStore
from app.persistence.board_projection_store import BoardProjectionStore
from app.persistence.board_store import BoardStore
from app.ports import Person, Task
from app.services.board.announcements.content import GateContent
from app.services.board.announcements.service import (
    AnnouncementDeps,
    AnnouncementService,
)
from app.services.board.artifacts import ArtifactDraft, ArtifactsService
from app.services.board.gates import GateRequirements, GatesService
from app.services.board.projections import ProjectionsService
from app.services.board.service import BoardService
from app.services.board.specialists import SpecialistRoster
from app.services.task_source_utils import as_posted
from app.services.task_sources import TaskSourceRegistry
from tests.board_test_support import board_session_factory
from tests.interview_support import specialist

BASE_URL = "https://kestrel.example"
TASK_REF = "KEY-1"
WORKFLOW_ID = "wf-1"
REPORTER = Person("acc-reporter", "Rita Reporter")
CHANGE_OWNER = Person("acc-owner", "Carl Owner")
SOURCE = "jira"


class RecordingSource:
    """A ticket that records every comment, as the adapter would post it
    (marker added), and every status transition it is asked for."""

    def __init__(
        self,
        task: Task | None,
        *,
        failures: int = 0,
        unreadable: bool = False,
    ) -> None:
        self.task = task
        self.posted: list[tuple[str, Document]] = []
        self.transitions: list[tuple[str, object]] = []
        self.read_refs: list[str] = []
        self._failures = failures
        self._unreadable = unreadable

    async def get_task(self, ref: str) -> Task:
        self.read_refs.append(ref)
        if self._unreadable:
            raise RuntimeError("ticket unreachable")
        assert self.task is not None
        return self.task

    async def post_comment(self, ref: str, body: Document) -> str:
        if self._failures:
            self._failures -= 1
            raise RuntimeError("ticket unreachable")
        self.posted.append((ref, as_posted(body, True)))
        return f"comment-{len(self.posted)}"

    async def transition(self, ref: str, event: object) -> bool:
        self.transitions.append((ref, event))
        return True

    def comments(self) -> list[Document]:
        return [body for _ref, body in self.posted]


@dataclass
class Stack:
    """Everything an announcement test drives and inspects."""

    store: BoardStore
    board: BoardService
    gates: GatesService
    artifacts: ArtifactsService
    projections: ProjectionsService
    service: AnnouncementService
    source: RecordingSource
    opened: list[str]


def ticket(
    *,
    reporter: Person | None = REPORTER,
    change_owner: Person | None = CHANGE_OWNER,
    failures: int = 0,
    unreadable: bool = False,
) -> RecordingSource:
    """A recording ticket with these people on it; it refuses its first
    *failures* comments, or cannot be read at all."""
    task = Task(
        TASK_REF, "Add export", document(paragraph(Text("x"))),
        reporter=reporter, change_owner=change_owner,
    )
    return RecordingSource(task, failures=failures, unreadable=unreadable)


def build_stack(
    tmp_path: Path,
    *,
    base_url: str = BASE_URL,
    source: RecordingSource | None = None,
) -> Stack:
    """A migrated database, the board services, and an announcement
    service over a recording ticket."""
    factory = board_session_factory(tmp_path)
    store = BoardStore(factory)
    opened: list[str] = []
    board = BoardService(store, on_gate_opened=opened.append)
    artifacts = ArtifactsService(
        store, BoardArtifactStore(factory), board,
        BoardArtifactContentStore(tmp_path / "artifacts"),
    )
    gates = GatesService(
        store, BoardGateStore(factory), board, artifacts,
        required=GateRequirements(prd=True, cab1=True, decomposition=True),
    )
    store.create_workflow(Workflow(
        id=WORKFLOW_ID, source=SOURCE, task_ref=TASK_REF, repo="o/r",
        base_branch="main", source_visibility="private", title="Add export",
        task_body=document(paragraph(Text("Please add CSV export."))),
    ))
    projections = ProjectionsService(BoardProjectionStore(factory))
    recording = source or ticket()
    roster = SpecialistRoster({
        "dba": specialist("dba", "refinement"),
        "infosec": specialist("infosec", "refinement"),
    })
    service = AnnouncementService(AnnouncementDeps(
        store=store,
        content=GateContent(store, gates, artifacts, roster),
        projections=projections,
        task_sources=TaskSourceRegistry({SOURCE: recording}, {}),
        base_url=base_url,
    ))
    return Stack(
        store, board, gates, artifacts, projections, service, recording, opened
    )


def producer(stack: Stack, kind: CardKind, *roles: str) -> WorkCard:
    """A finished card that produced something a gate asks about."""
    card = WorkCard(
        id=f"card-{kind.value}-{len(stack.store.list_cards(WORKFLOW_ID))}",
        workflow_id=WORKFLOW_ID, kind=kind.value, title=kind.value,
        state="done", eligible_roles=roles,
    )
    stack.store.create_card(card)
    return card


def questions_artifact(stack: Stack, card: WorkCard, count: int) -> str:
    """Store *count* questions as *card*'s question set; its id."""
    artifact = stack.artifacts.store_reference_artifact(_draft(
        card, "questions",
        json.dumps({"questions": [f"Question {n}?" for n in range(count)]}),
    ))
    return artifact.id


def _draft(card: WorkCard, name: str, content: str) -> ArtifactDraft:
    return ArtifactDraft(
        producer_card_id=card.id, logical_name=name, revision=1,
        content=content, trust="agent_output",
    )


def open_gate(
    stack: Stack, kind: CardKind, target: str | None, decision: str
) -> WorkCard:
    """Open a gate the way the board does."""
    return stack.gates.create_gate(
        WORKFLOW_ID, kind=kind.value, title=kind.value,
        requested_decision=decision, target_artifact_id=target,
    )


def open_document_gate(
    stack: Stack, kind: CardKind, producer_kind: CardKind, text: str
) -> WorkCard:
    """Open a gate on a document *text* that a card produced."""
    card = producer(stack, producer_kind, "pm")
    artifact = stack.artifacts.store_document(
        card.id, "draft", 1, document(paragraph(Text(text)))
    )
    return open_gate(stack, kind, artifact.id, "decide")


def add_plan(stack: Stack) -> WorkCard:
    """An interview plan card."""
    return producer(stack, CardKind.INTERVIEW_PLAN, "coordinator")


def open_interview_gate(
    stack: Stack, plan: WorkCard, persona: str, questions: int
) -> WorkCard:
    """One persona's interview of *plan*'s batch, its gate open."""
    refinement = producer(stack, CardKind.REFINEMENT, persona)
    stack.store.add_relation(
        CardRelation(card_id=refinement.id, depends_on_card_id=plan.id),
        created_by_action="test",
    )
    target = questions_artifact(stack, refinement, questions)
    return open_gate(stack, CardKind.REFINEMENT_GATE, target, "answer")


def marker_names(doc: Document) -> frozenset[str]:
    """The markers a posted comment carries."""
    return doc.markers()


POSTED = Marker("posted")


def announcing(
    store: BoardStore, projections: ProjectionsService, sources: dict
) -> AnnouncementService:
    """An announcement service for tests that only post what a dispatch
    pass hands it (a delivery, an escalation), never a gate's."""
    return AnnouncementService(AnnouncementDeps(
        store=store,
        content=cast(GateContent, None),
        projections=projections,
        task_sources=TaskSourceRegistry(sources, {}),
    ))
