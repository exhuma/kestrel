"""Tests for decomposition-candidate parsing, routing, and publishing
(feature 026, T068).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.markers import SubtaskSentinel
from app.models_board import SpecialistDefinition, WorkCard, Workflow
from app.persistence.board_artifact_content_store import (
    BoardArtifactContentStore,
)
from app.persistence.board_artifact_store import BoardArtifactStore
from app.persistence.board_claims_store import BoardClaimsStore
from app.persistence.board_coordinator_store import BoardCoordinatorStore
from app.persistence.board_gate_store import BoardGateStore
from app.persistence.board_store import BoardStore
from app.services.board.artifacts import ArtifactsService
from app.services.board.claims import ClaimsService
from app.services.board.coordinator import CoordinatorService
from app.services.board.decomposition import (
    DecompositionResultError,
    DecompositionTask,
    parse_decomposition_result,
    publish_decomposition,
    route_decomposition_result,
)
from app.services.board.dispatch_ready import (
    DispatchServices,
    dispatch_ready_work,
)
from app.services.board.gates import GatesService
from app.services.board.service import BoardService
from app.services.board.specialists import SpecialistRoster
from tests.board_test_support import board_session_factory
from tests.test_board_scheduling import _FakeBackend

_WORKFLOW = Workflow(
    id="wf-1",
    source="github-issue",
    task_ref="owner/repo#1",
    repo="owner/repo",
    base_branch="main",
    source_visibility="public",
    title="Add a thing",
)


def _decomposition_block(*entries: str) -> str:
    return (
        "<DECOMPOSITION>{\"tasks\": [" + ",".join(entries) + "]}"
        "</DECOMPOSITION>"
    )


class TestParsing:
    def test_parses_well_formed_tasks(self) -> None:
        text = _decomposition_block(
            '{"title": "Do X", "body": "details", '
            '"task_node_id": "T1", "prerequisites": []}'
        )
        tasks = parse_decomposition_result(text)
        assert tasks == [
            DecompositionTask(
                title="Do X", body="details", task_node_id="T1",
                prerequisites=(),
            )
        ]

    def test_missing_tag_raises(self) -> None:
        with pytest.raises(DecompositionResultError):
            parse_decomposition_result("no structured block here")

    def test_malformed_json_raises(self) -> None:
        text = "<DECOMPOSITION>{not json}</DECOMPOSITION>"
        with pytest.raises(DecompositionResultError):
            parse_decomposition_result(text)

    def test_empty_task_list_raises(self) -> None:
        with pytest.raises(DecompositionResultError):
            parse_decomposition_result(_decomposition_block())

    def test_missing_required_field_raises(self) -> None:
        text = _decomposition_block('{"title": "Do X"}')
        with pytest.raises(DecompositionResultError):
            parse_decomposition_result(text)

    def test_prerequisites_default_to_empty(self) -> None:
        text = _decomposition_block('{"title": "Do X", "body": "y"}')
        assert parse_decomposition_result(text)[0].prerequisites == ()


def _setup(tmp_path: Path):
    factory = board_session_factory(tmp_path)
    store = BoardStore(factory)
    coordinator_store = BoardCoordinatorStore(factory)
    gate_store = BoardGateStore(factory)
    artifact_store = BoardArtifactStore(factory)
    content_store = BoardArtifactContentStore(tmp_path / "artifacts")
    board_service = BoardService(store)
    coordinator = CoordinatorService(store, coordinator_store, board_service)
    artifacts = ArtifactsService(
        store, artifact_store, board_service, content_store
    )
    gates = GatesService(store, gate_store, board_service, artifacts)
    store.create_workflow(_WORKFLOW)
    card = WorkCard(
        id="card-1", workflow_id="wf-1", kind="decomposition",
        title="Decompose", state="review", attempt_count=1,
    )
    store.create_card(card)
    return store, coordinator, gates, artifacts, card, gate_store


class TestRouting:
    def test_a_well_formed_proposal_creates_a_decomposition_gate(
        self, tmp_path: Path
    ) -> None:
        store, coordinator, gates, artifacts, card, gate_store = _setup(
            tmp_path
        )
        text = _decomposition_block(
            '{"title": "Do X", "body": "details"}',
            '{"title": "Do Y", "body": "more details"}',
        )

        route_decomposition_result(text, card, coordinator, gates, artifacts)

        new_cards = [c for c in store.list_cards("wf-1") if c.id != "card-1"]
        assert len(new_cards) == 1
        assert new_cards[0].kind == "decomposition_gate"
        assert new_cards[0].state == "awaiting_human"
        gate = gate_store.get_for_card(new_cards[0].id)
        assert gate is not None
        assert gate.target_artifact_id is not None

    def test_an_unparseable_proposal_escalates_fail_closed(
        self, tmp_path: Path
    ) -> None:
        store, coordinator, gates, artifacts, card, _gate_store = _setup(
            tmp_path
        )

        route_decomposition_result(
            "no structured block here", card, coordinator, gates, artifacts
        )

        new_cards = [c for c in store.list_cards("wf-1") if c.id != "card-1"]
        assert len(new_cards) == 1
        assert new_cards[0].kind == "coordinator_review"


class _FakeTaskSource:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, tuple]] = []
        self._next = 1

    async def create_subtask(
        self, parent_ref: str, title: str, body: str, markers=()
    ) -> str:
        self.calls.append((parent_ref, title, body, markers))
        ref = f"owner/repo#{100 + self._next}"
        self._next += 1
        return ref


class _FakeChildTasks:
    def __init__(self) -> None:
        self.recorded: list[dict] = []

    def record(
        self, parent_workflow_id, task_ref, task_node_id="",
        prerequisites=(), integration_branch="",
    ) -> None:
        self.recorded.append(
            {
                "parent_workflow_id": parent_workflow_id,
                "task_ref": task_ref,
                "task_node_id": task_node_id,
                "prerequisites": prerequisites,
                "integration_branch": integration_branch,
            }
        )


class TestPublishing:
    @pytest.mark.asyncio
    async def test_publishes_every_task_with_a_subtask_sentinel(self) -> None:
        task_source = _FakeTaskSource()
        child_tasks = _FakeChildTasks()
        candidate = (
            '{"tasks": [{"title": "Do X", "body": "details"}, '
            '{"title": "Do Y", "body": "more", "task_node_id": "T2", '
            '"prerequisites": ["T1"]}]}'
        )

        refs = await publish_decomposition(
            _WORKFLOW, candidate, task_source, child_tasks
        )

        published_task_count = 2
        assert refs == ["owner/repo#101", "owner/repo#102"]
        assert len(task_source.calls) == published_task_count
        for _parent, _title, _body, markers in task_source.calls:
            assert isinstance(markers[0], SubtaskSentinel)
        assert child_tasks.recorded[1]["task_node_id"] == "T2"
        assert child_tasks.recorded[1]["prerequisites"] == ("T1",)
        assert child_tasks.recorded[0]["parent_workflow_id"] == "wf-1"


class TestEndToEndDispatchRouting:
    """A decomposition card's turn result creates a gate through the
    real dispatch_ready_work loop, not just route_decomposition_result
    called directly."""

    @pytest.mark.asyncio
    async def test_a_pm_turn_with_a_candidate_creates_a_gate(
        self, tmp_path: Path,
    ) -> None:
        factory = board_session_factory(tmp_path)
        store = BoardStore(factory)
        claims_store = BoardClaimsStore(factory)
        coordinator_store = BoardCoordinatorStore(factory)
        gate_store = BoardGateStore(factory)
        board_service = BoardService(store)
        artifact_store = BoardArtifactStore(factory)
        content_store = BoardArtifactContentStore(tmp_path / "artifacts")
        pm = SpecialistDefinition(
            id="pm", label="pm", purpose="test role",
            allowed_card_types=("analysis", "decomposition"),
            required_abilities=(), model_policy="default",
            workspace_permission="read_only", retry_limit=1,
            prompt="You are the pm.",
        )
        roster = SpecialistRoster({"pm": pm})
        store.create_workflow(_WORKFLOW)
        store.create_card(
            WorkCard(
                id="card-1", workflow_id="wf-1", kind="decomposition",
                title="Decompose", state="ready", eligible_roles=("pm",),
            )
        )
        claims = ClaimsService(
            store=store, claims_store=claims_store, roster=roster,
            max_parallel_read_cards=4, default_lease_seconds=60,
            default_workspace_lease_seconds=600,
        )
        artifacts = ArtifactsService(
            store, artifact_store, board_service, content_store
        )
        coordinator = CoordinatorService(
            store, coordinator_store, board_service
        )
        gates = GatesService(store, gate_store, board_service, artifacts)
        services = DispatchServices(
            claims, roster, artifacts, coordinator=coordinator, gates=gates,
        )
        backend = _FakeBackend(_decomposition_block(
            '{"title": "Do X", "body": "details"}'
        ))

        await dispatch_ready_work(
            "wf-1", services, lambda _s: backend, timeout_seconds=5
        )

        assert store.get_card("card-1").state == "done"
        new_cards = [c for c in store.list_cards("wf-1") if c.id != "card-1"]
        assert len(new_cards) == 1
        assert new_cards[0].kind == "decomposition_gate"
