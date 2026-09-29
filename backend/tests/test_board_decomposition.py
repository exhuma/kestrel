"""Tests for decomposition-candidate parsing and routing (feature 026,
T068). Approval no longer publishes anything: see
``test_board_materialise.py`` (feature 031).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

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
    RoutingServices,
    parse_decomposition_result,
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


def _routing(tmp_path: Path) -> tuple[RoutingServices, WorkCard]:
    store, coordinator, gates, artifacts, card, _gate_store = _setup(
        tmp_path
    )
    return RoutingServices(store, coordinator, gates, artifacts), card


def _classified_block(
    *entries: str, summary: str = "Two small changes."
) -> str:
    return (
        "<DECOMPOSITION>{\"summary\": " + json.dumps(summary)
        + ", \"tasks\": [" + ",".join(entries) + "]}</DECOMPOSITION>"
    )


class TestRouting:
    def test_a_valid_proposal_creates_an_estimation_card_not_a_gate(
        self, tmp_path: Path
    ) -> None:
        """Ensure CAB-2 waits for estimates (feature 030, FR-005)."""
        services, card = _routing(tmp_path)
        text = _classified_block(
            '{"title": "Do X", "body": "details", '
            '"classification": "coding"}',
            '{"title": "Ask legal", "body": "sign-off", '
            '"classification": "manual"}',
        )

        route_decomposition_result(text, card, services)

        new_cards = [
            c for c in services.store.list_cards("wf-1") if c.id != "card-1"
        ]
        assert [c.kind for c in new_cards] == ["estimation"]
        estimation = new_cards[0]
        assert estimation.state == "ready"
        assert estimation.eligible_roles == ("developer",)
        assert estimation.workspace_permission == "read_only"
        assert estimation.title == "Estimate decomposition (2 tasks)"
        relations = services.store.list_relations("wf-1")
        assert [(r.card_id, r.depends_on_card_id) for r in relations] == [
            (estimation.id, "card-1")
        ]

    def test_the_stored_candidate_is_normalized(
        self, tmp_path: Path
    ) -> None:
        """Ensure ids are assigned before the estimator sees the tasks."""
        services, card = _routing(tmp_path)
        text = _classified_block(
            '{"title": "Do X", "body": "details", '
            '"classification": "coding"}',
        )

        route_decomposition_result(text, card, services)

        stored = json.loads(
            services.artifacts.latest_content_for_card(
                "card-1", "decomposition_candidate"
            )
        )
        assert stored["summary"] == "Two small changes."
        assert stored["tasks"][0]["task_node_id"] == "t1"
        assert stored["tasks"][0]["classification"] == "coding"

    @pytest.mark.parametrize(
        "text",
        [
            "no structured block here",
            _classified_block('{"title": "Do X", "body": "details"}'),
            _classified_block(
                '{"title": "Do X", "body": "d", "classification": "coding"}',
                summary="",
            ),
            _classified_block(
                '{"title": "A", "body": "a", "task_node_id": "x", '
                '"classification": "coding"}',
                '{"title": "B", "body": "b", "task_node_id": "x", '
                '"classification": "coding"}',
            ),
        ],
        ids=["no-block", "unclassified", "no-summary", "duplicate-id"],
    )
    def test_an_invalid_proposal_escalates_fail_closed(
        self, tmp_path: Path, text: str
    ) -> None:
        services, card = _routing(tmp_path)

        route_decomposition_result(text, card, services)

        new_cards = [
            c for c in services.store.list_cards("wf-1") if c.id != "card-1"
        ]
        assert [c.kind for c in new_cards] == ["coordinator_review"]


class TestEndToEndDispatchRouting:
    """A decomposition card's turn result creates an estimation card
    through the real dispatch_ready_work loop, not just
    route_decomposition_result called directly."""

    @pytest.mark.asyncio
    async def test_a_pm_turn_with_a_candidate_creates_an_estimation_card(
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
        backend = _FakeBackend(_classified_block(
            '{"title": "Do X", "body": "details", "classification": "coding"}'
        ))

        await dispatch_ready_work(
            "wf-1", services, lambda _s: backend, timeout_seconds=5
        )

        assert store.get_card("card-1").state == "done"
        new_cards = [c for c in store.list_cards("wf-1") if c.id != "card-1"]
        assert [c.kind for c in new_cards] == ["estimation"]
